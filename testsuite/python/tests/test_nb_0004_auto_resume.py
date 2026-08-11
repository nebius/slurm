############################################################################
# Copyright (C) Nebius
############################################################################
"""Verify that AutoResume=off keeps powered-down nodes out of scheduling."""

import pytest

import atf

pytestmark = pytest.mark.slow

node_name = "node1"


@pytest.fixture(scope="module", autouse=True)
def setup():
    atf.require_auto_config("configures a powered-down cloud node")
    atf.require_config_parameter("AccountingStorageType", "accounting_storage/none")
    atf.require_config_parameter("SelectType", "select/cons_tres")
    atf.require_config_parameter("SelectTypeParameters", "CR_CPU")
    atf.require_config_parameter("TreeWidth", 65533)
    atf.require_config_parameter("ResumeProgram", "/bin/true")
    atf.require_config_parameter("SuspendProgram", "/bin/true")
    atf.require_config_parameter("SuspendTime", 10)
    atf.require_config_parameter("ResumeTimeout", 10)
    atf.require_config_parameter("SuspendTimeout", 10)
    atf.require_config_parameter_includes(
        "SlurmctldParameters", "idle_on_node_suspend"
    )
    atf.require_config_parameter(
        "NodeName",
        {node_name: {"AutoResume": "off", "State": "CLOUD"}},
    )
    atf.require_config_parameter(
        "PartitionName", {"cloud": {"Nodes": node_name, "Default": "yes"}}
    )

    # A CLOUD node starts without a slurmd and is therefore POWERED_DOWN.
    atf.start_slurmctld(clean=True)

    yield

    atf.cancel_all_jobs(quiet=True)
    atf.stop_slurmctld(quiet=True, also_slurmds=True)


def _node_state():
    return set(atf.get_node_parameter(node_name, "state"))


def test_auto_resume_off():
    """A queued job cannot auto-resume the node, but an admin still can."""
    assert {"CLOUD", "IDLE", "POWERED_DOWN"} <= _node_state()

    job_id = atf.submit_job_sbatch("--wrap 'hostname'", fatal=True)

    # Detect the regression immediately if either the scheduler allocates the
    # node or the power-save thread starts resuming it. The expected result is
    # a timeout with the job still PENDING and the node still POWERED_DOWN.
    unexpectedly_resumed = atf.repeat_until(
        lambda: (
            atf.get_job_parameter(job_id, "JobState", quiet=True),
            _node_state(),
        ),
        lambda status: status[0] != "PENDING"
        or bool({"ALLOCATED", "POWER_UP", "POWERING_UP"} & status[1]),
        timeout=5,
        xfail=True,
        fatal=True,
    )
    assert not unexpectedly_resumed
    assert atf.get_job_parameter(job_id, "JobState", quiet=True) == "PENDING"
    assert {"IDLE", "POWERED_DOWN"} <= _node_state()

    atf.run_command(
        f"scontrol update nodename={node_name} state=POWER_UP",
        fatal=True,
        user="slurm",
    )
    assert atf.repeat_until(
        _node_state,
        lambda state: bool({"POWER_UP", "POWERING_UP"} & state),
        timeout=5,
        fatal=True,
    ), "An explicit administrator power-up must bypass AutoResume=off"
