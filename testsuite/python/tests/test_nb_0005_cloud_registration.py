############################################################################
# Copyright (C) Nebius
############################################################################
"""Refresh slurmd-supplied fields when a CLOUD node resumes from power save.

POWERING_UP registration updates last_response before applying these fields,
so boot_time > last_response alone cannot detect the new boot. Check both the
node's Topology= field and the topology plugin's actual switch membership.
"""

import re
import time

import pytest

import atf

pytestmark = pytest.mark.slow

NODE = "node1"
RESUME_TIMEOUT = 60


@pytest.fixture(scope="module", autouse=True)
def setup():
    atf.require_auto_config("configures a CLOUD node and starts slurmd manually")
    for component in ("sbin/slurmctld", "sbin/slurmd"):
        atf.require_version((26, 5), component)
    atf.require_config_parameter("AccountingStorageType", "accounting_storage/none")
    atf.require_config_parameter("SelectType", "select/cons_tres")
    atf.require_config_parameter("SelectTypeParameters", "CR_CPU")
    atf.require_config_parameter("ReturnToService", 1)
    atf.require_config_parameter("ResumeProgram", "/bin/true")
    atf.require_config_parameter("SuspendProgram", "/bin/true")
    # INFINITE disables automatic job-triggered resume as well as suspend.
    atf.require_config_parameter("SuspendTime", 300)
    atf.require_config_parameter("SuspendTimeout", 5)
    atf.require_config_parameter("ResumeTimeout", RESUME_TIMEOUT)
    atf.require_config_parameter_includes("SlurmctldParameters", "idle_on_node_suspend")
    atf.require_config_parameter(
        "NodeName", {NODE: {"State": "CLOUD", "CPUs": 1, "RealMemory": 64}}
    )
    atf.require_config_parameter(
        "PartitionName", {"cloud": {"Nodes": NODE, "Default": "yes", "State": "UP"}}
    )
    atf.require_config_file(
        "topology.yaml",
        f"""
- topology: tree_topo
  cluster_default: true
  tree:
    switches:
      - switch: sw_root
        children: sw_unknown,sw_alpha,sw_gamma,sw_admin
      - switch: sw_unknown
        nodes: {NODE}
      - switch: sw_alpha
      - switch: sw_gamma
      - switch: sw_admin
""",
    )


@pytest.fixture(autouse=True)
def cloud_node(setup):
    # Each test begins with a powered-down node and no slurmd.
    atf.start_slurmctld(clean=True)
    atf.ensure_node_directories(NODE)
    yield
    atf.cancel_all_jobs(quiet=True)
    atf.stop_slurmctld(quiet=True, also_slurmds=True)


def _start_slurmd(switch, value, boot=False):
    atf.run_command(
        f"{atf.properties['slurm-sbin-dir']}/slurmd -N {NODE} "
        f"{'-b ' if boot else ''}--conf 'Topology=tree_topo:{switch}' "
        f"--extra=extra-{value} --instance-id=id-{value} --instance-type=type-{value}",
        user="root",
        fatal=True,
    )


def _stop_slurmd():
    executable = f"{atf.properties['slurm-sbin-dir']}/slurmd"
    for pid in atf.pids_from_exe(executable):
        atf.run_command(f"kill {pid}", user="root", fatal=True)
    atf.repeat_until(
        lambda: atf.pids_from_exe(executable),
        lambda pids: not pids,
        fatal=True,
    )


def _assert_switch(expected):
    output = atf.run_command_output("scontrol show topology tree_topo", fatal=True)
    switches = set()
    for line in output.splitlines():
        match = re.match(r"SwitchName=(\S+) Level=0 .*Nodes=(\S+)", line)
        if match and NODE in atf.node_range_to_list(match.group(2)):
            switches.add(match.group(1))
    assert switches == {expected}, output


def _assert_fields(switch, value):
    node = atf.get_nodes()[NODE]
    expected = {
        "topology": f"tree_topo:{switch}",
        "extra": f"extra-{value}",
        "instance_id": f"id-{value}",
        "instance_type": f"type-{value}",
    }
    assert {field: node.get(field) for field in expected} == expected
    assert not {"DOWN", "DRAIN", "INVALID_REG"} & set(node["state"]), node
    _assert_switch(switch)


def _admin_override():
    atf.run_command(
        f"scontrol update NodeName={NODE} Topology=tree_topo:sw_admin "
        "Extra=extra-admin InstanceId=id-admin InstanceType=type-admin",
        user=atf.properties["slurm-user"],
        fatal=True,
    )
    _assert_fields("sw_admin", "admin")


def _power_down():
    _stop_slurmd()
    atf.run_command(
        f"scontrol update NodeName={NODE} State=POWER_DOWN_FORCE",
        user=atf.properties["slurm-user"],
        fatal=True,
    )
    atf.wait_for_node_state(NODE, "POWERED_DOWN", fatal=True)
    _assert_switch("sw_unknown")


@pytest.mark.parametrize("resume", ["scontrol", "job"])
def test_power_up_refreshes_fields(resume):
    """Both resume paths apply all four fields on the first and later boots."""
    assert {"CLOUD", "IDLE", "POWERED_DOWN"} <= set(
        atf.get_node_parameter(NODE, "state")
    )
    assert not atf.get_node_parameter(NODE, "topology")
    _assert_switch("sw_unknown")

    for switch in ("sw_alpha", "sw_gamma"):
        job_id = None
        if resume == "scontrol":
            atf.run_command(
                f"scontrol update NodeName={NODE} State=POWER_UP",
                user=atf.properties["slurm-user"],
                fatal=True,
            )
        else:
            job_id = atf.submit_job_sbatch(
                f"-p cloud -w {NODE} -N1 -n1 --mem=1 -t1 --wrap='/bin/true'",
                fatal=True,
            )

        # ResumeProgram deliberately does nothing: start slurmd only after
        # the power-save thread has set POWERING_UP, not merely POWER_UP.
        atf.wait_for_node_state(NODE, "POWERING_UP", fatal=True)
        _start_slurmd(switch, switch, boot=True)
        atf.wait_for_node_state(
            NODE, "POWERING_UP", reverse=True, timeout=RESUME_TIMEOUT, fatal=True
        )
        if job_id is not None:
            atf.wait_for_job_state(job_id, "COMPLETED", fatal=True)
        atf.wait_for_node_state(NODE, "IDLE", fatal=True)
        _assert_fields(switch, switch)

        # A normal daemon restart must still preserve administrator values.
        # Wait for a distinct start timestamp so assertions cannot see the
        # previous registration and accidentally pass before the new one.
        _admin_override()
        old_start = atf.get_node_parameter(NODE, "slurmd_start_time")
        old_second = old_start["number"] if isinstance(old_start, dict) else old_start
        _stop_slurmd()
        while int(time.time()) <= old_second:
            time.sleep(0.05)
        _start_slurmd(switch, switch)
        atf.repeat_until(
            lambda: atf.get_node_parameter(NODE, "slurmd_start_time"),
            lambda start: start and start != old_start,
            fatal=True,
        )
        _assert_fields("sw_admin", "admin")

        # Retain controller state between cycles. The next resume must
        # replace previous metadata even though last_response is nonzero.
        _power_down()


def test_powered_down_registration_refreshes_fields_without_reboot():
    """Out-of-band cloud startup can report the uptime of an existing host."""
    _start_slurmd("sw_alpha", "original")
    atf.wait_for_node_state(NODE, "POWERED_DOWN", reverse=True, fatal=True)
    atf.wait_for_node_state(NODE, "IDLE", fatal=True)
    _assert_fields("sw_alpha", "original")
    _admin_override()
    _power_down()

    # No POWERING_UP and no -b: the host boot predates last_response, so
    # was_powered_down must make the field-apply block run on registration.
    _start_slurmd("sw_gamma", "new")
    atf.wait_for_node_state(NODE, "POWERED_DOWN", reverse=True, fatal=True)
    atf.wait_for_node_state(NODE, "IDLE", fatal=True)
    _assert_fields("sw_gamma", "new")
