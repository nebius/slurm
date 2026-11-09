############################################################################
# Copyright (c) 2026 Nebius.
############################################################################
"""Recover saved node topology when a whole block disappears from the config."""

import shlex

import pytest
import yaml

import atf

pytestmark = pytest.mark.slow

STALE = "tree_topo:root:sw_stale,block_topo:b_stale"
KEEP = "tree_topo:root:sw_keep,block_topo:b_keep"
FALLBACKS = {
    "absent": None,
    "valid": KEEP,
    "invalid": "tree_topo:root:sw_other,block_topo:b_stale",
    "identical": STALE,
}


@pytest.fixture(scope="module", autouse=True)
def setup():
    atf.require_auto_config("removes blocks with persisted CLOUD node assignments")
    atf.require_version((26, 5), "sbin/slurmctld")
    atf.require_config_parameter("AccountingStorageType", "accounting_storage/none")
    atf.require_config_parameter("SelectType", "select/cons_tres")
    atf.require_config_parameter("SelectTypeParameters", "CR_CPU")
    atf.require_config_parameter("ResumeProgram", "/bin/true")
    atf.require_config_parameter("SuspendProgram", "/bin/true")
    atf.require_config_parameter("SuspendTime", "INFINITE")
    atf.require_config_parameter("ResumeTimeout", 3600)
    atf.require_config_parameter_includes(
        "SlurmctldParameters", ("power_save_interval", 1)
    )
    atf.require_config_parameter(
        "PartitionName",
        {"cloud": {"Nodes": "node[1-2]", "Default": "yes", "State": "UP"}},
    )


@pytest.fixture(scope="module")
def node_probe(setup):
    # Query the public API directly, without parsing the node display command.
    source = atf.module_tmp_path / "node_topology.c"
    binary = atf.module_tmp_path / "node_topology"
    source.write_text(
        r"""
#include <stdio.h>
#include <slurm/slurm.h>

int main(void)
{
    node_info_msg_t *msg = NULL;

    slurm_init(NULL);
    if (slurm_load_node(0, &msg, SHOW_ALL)) {
        slurm_perror("slurm_load_node");
        slurm_fini();
        return 1;
    }
    for (uint32_t i = 0; i < msg->record_count; i++) {
        node_info_t *node = &msg->node_array[i];

        if (!node->name)
            continue;
        printf("%s %s %d\n", node->name,
               node->topology_str ? node->topology_str : "-",
               !!(node->node_state & NODE_STATE_POWERING_UP));
    }
    slurm_free_node_info_msg(msg);
    slurm_fini();
    return 0;
}
"""
    )
    atf.compile_against_libslurm(
        shlex.quote(str(source)), shlex.quote(str(binary)), fatal=True
    )
    return shlex.quote(str(binary))


@pytest.fixture(autouse=True)
def stop_controller(setup):
    yield
    if atf.is_slurmctld_running(quiet=True):
        assert atf.stop_slurmctld(quiet=True) is None


def _configure_nodes(fallback, state="CLOUD"):
    first = {
        "State": state,
        "CPUs": 1,
        "RealMemory": 64,
        "NodeAddr": "127.0.0.1",
    }
    if fallback:
        first["Topology"] = fallback
    atf.require_config_parameter(
        "NodeName",
        {
            "node1": first,
            "node2": {
                "State": state,
                "CPUs": 1,
                "RealMemory": 64,
                "NodeAddr": "127.0.0.1",
            },
        },
    )


def _write_topology(stale_block):
    switches = ["sw_unknown", "sw_keep", "sw_other"]
    blocks = [
        {"block": "unknown", "nodes": "node[1-2]"},
        {"block": "b_keep"},
    ]
    if stale_block:
        switches.append("sw_stale")
        blocks.append({"block": "b_stale"})
    config = [
        {
            "topology": "tree_topo",
            "tree": {
                "switches": [
                    {"switch": "root", "children": ",".join(switches)},
                    {"switch": "sw_unknown", "nodes": "node[1-2]"},
                ]
                + [{"switch": name} for name in switches if name != "sw_unknown"]
            },
        },
        {
            "topology": "block_topo",
            "cluster_default": True,
            "block": {"block_sizes": [2], "blocks": blocks},
        },
    ]
    atf.require_config_file("topology.yaml", yaml.safe_dump(config))


def _nodes(probe):
    output = atf.run_command_output(probe, fatal=True)
    nodes = {}
    for line in output.splitlines():
        name, topology, powering_up = line.split()
        nodes[name] = {
            "topology": None if topology == "-" else topology,
            "powering_up": powering_up == "1",
        }
    return nodes


def _topoconf():
    result = atf.run_command("scontrol show topoconf", quiet=True, timeout=5)
    if result["exit_code"]:
        return {}
    return {entry["topology"]: entry for entry in yaml.safe_load(result["stdout"])}


def _block_removed(config):
    block = config.get("block_topo", {}).get("block", {})
    return bool(block) and all(
        entry["block"] != "b_stale" for entry in block["blocks"]
    )


def _assert_membership(config, node, expected_tree, expected_block):
    leaves = config["tree_topo"]["tree"]["switches"]
    blocks = config["block_topo"]["block"]["blocks"]
    trees = {
        entry["switch"]
        for entry in leaves
        if not entry.get("children")
        and entry.get("nodes")
        and node in atf.node_range_to_list(entry["nodes"])
    }
    memberships = {
        entry["block"]
        for entry in blocks
        if entry.get("nodes") and node in atf.node_range_to_list(entry["nodes"])
    }
    assert trees == expected_tree, config
    assert memberships == expected_block, config


@pytest.mark.parametrize("lifecycle", ["restart", "foreground_reconfigure"])
@pytest.mark.parametrize("fallback", FALLBACKS)
def test_removed_block_recovers(lifecycle, fallback, node_probe, tmp_path):
    """Recover stale state, repair partial contexts, and process the next node."""
    _configure_nodes(FALLBACKS[fallback])
    _write_topology(stale_block=True)
    # Use the ATF startup helper once to initialize any required sackd too.
    atf.start_slurmctld(clean=True)
    if lifecycle == "foreground_reconfigure":
        assert atf.stop_slurmctld() is None
        log = shlex.quote(str(tmp_path / "slurmctld-foreground.log"))
        controller = shlex.quote(f"{atf.properties['slurm-sbin-dir']}/slurmctld")
        atf.run_command(
            f"{controller} -D > {log} 2>&1 < /dev/null &",
            user=atf.properties["slurm-user"],
            fatal=True,
        )
        atf.repeat_until(
            lambda: atf.is_slurmctld_running(quiet=True),
            lambda running: running,
            fatal=True,
        )

    # POWERING_UP clears POWERED_DOWN, allowing topology to be restored from
    # state without slurmd. The long resume timeout prevents a topology reset.
    atf.run_command(
        "scontrol update NodeName=node[1-2] State=POWER_UP",
        user=atf.properties["slurm-user"],
        fatal=True,
    )
    atf.repeat_until(
        lambda: _nodes(node_probe),
        lambda nodes: all(nodes[name]["powering_up"] for name in ("node1", "node2")),
        fatal=True,
    )
    for node, topology in (("node1", STALE), ("node2", KEEP)):
        atf.run_command(
            f"scontrol update NodeName={node} Topology={topology}",
            user=atf.properties["slurm-user"],
            fatal=True,
        )
        assert _nodes(node_probe)[node]["topology"] == topology

    if lifecycle == "restart":
        assert atf.stop_slurmctld() is None
    _write_topology(stale_block=False)
    if lifecycle == "restart":
        atf.start_slurmctld(clean=False)
    else:
        atf.run_command(
            "scontrol reconfigure", user=atf.properties["slurm-user"], fatal=True
        )
    # A successful RPC or ping alone can precede reconfigure's execve.
    atf.repeat_until(_topoconf, _block_removed, fatal=True)

    expected = KEEP if fallback == "valid" else None
    nodes = _nodes(node_probe)
    assert nodes["node1"]["topology"] == expected
    assert nodes["node2"]["topology"] == KEEP
    config = _topoconf()
    _assert_membership(
        config,
        "node1",
        {"sw_keep"} if expected else set(),
        {"b_keep"} if expected else set(),
    )
    _assert_membership(config, "node2", {"sw_keep"}, {"b_keep"})

    # Once the saved string is NULL, a later start can use the YAML baseline.
    assert atf.stop_slurmctld() is None
    atf.start_slurmctld(clean=False)
    assert _nodes(node_probe)["node1"]["topology"] == expected
    config = _topoconf()
    if fallback == "absent":
        _assert_membership(config, "node1", {"sw_unknown"}, {"unknown"})
    else:
        _assert_membership(
            config,
            "node1",
            {"sw_keep"} if expected else set(),
            {"b_keep"} if expected else set(),
        )
    _assert_membership(config, "node2", {"sw_keep"}, {"b_keep"})

    result = atf.run_command(
        "scontrol update NodeName=node2 Topology=block_topo:b_stale",
        user=atf.properties["slurm-user"],
        xfail=True,
    )
    assert result["exit_code"] != 0
    assert _nodes(node_probe)["node2"]["topology"] == KEEP
    _assert_membership(_topoconf(), "node2", {"sw_keep"}, {"b_keep"})


def test_invalid_static_node_topology_is_cleared(node_probe):
    """The permissive policy also applies to static nodes on a clean start."""
    _configure_nodes(STALE, state="DOWN")
    _write_topology(stale_block=False)
    atf.start_slurmctld(clean=True)
    assert _nodes(node_probe)["node1"]["topology"] is None
    _assert_membership(_topoconf(), "node1", set(), set())
