############################################################################
# Copyright (c) 2026 Nebius.
############################################################################
"""NB-0002: a redundant topology update must not disable block scheduling.

topology_p_add_rm_node() clears the node's bit in the aggregate
blocks_nodes_bitmap before re-adding it, but only restored the bit when the
block membership actually changed. Re-applying the topology a node already has
therefore dropped it from that bitmap while the per-block bitmaps stayed
intact, so scontrol kept reporting the correct topology while
topology_p_eval_nodes() silently stopped using the block algorithm for the
affected nodes.
"""

import pytest

import atf


BLOCKS = {"b1": "node[1-4]", "b2": "node[5-8]"}


@pytest.fixture(scope="module", autouse=True)
def setup():
    atf.require_auto_config("wants to create a custom topology.conf")
    atf.require_nodes(8)
    atf.require_config_parameter("SelectType", "select/cons_tres")
    atf.require_config_parameter("SelectTypeParameters", "CR_CPU")
    atf.require_config_parameter("TopologyPlugin", "topology/block")
    atf.require_config_file(
        "topology.conf",
        """
        BlockName=b1 Nodes=node[1-4]
        BlockName=b2 Nodes=node[5-8]
        BlockSizes=4,8
        """,
    )
    atf.require_slurm_running()


@pytest.fixture(autouse=True)
def cancel_jobs():
    yield
    atf.cancel_all_jobs(quiet=True)


def block_of(node_list_expression):
    """Returns the name of the block holding every node of the expression.

    Fails the test when the nodes span more than one block.
    """

    blocks = set()
    for node in atf.node_range_to_list(node_list_expression):
        for block, nodes in BLOCKS.items():
            if node in atf.node_range_to_list(nodes):
                blocks.add(block)
                break
        else:
            pytest.fail(f"Node {node} does not belong to any configured block")

    assert (
        len(blocks) == 1
    ), f"Allocation {node_list_expression} spans several blocks: {sorted(blocks)}"

    return blocks.pop()


def assert_node_topology(node, expected, timeout=10):
    """Wait until the controller reports the expected topology for a node."""

    matches = atf.repeat_until(
        lambda: atf.get_node_parameter(node, "topology"),
        lambda topology: topology == expected,
        timeout=timeout,
        fatal=False,
    )
    if not matches:
        pytest.fail(
            f"Node {node} should report Topology={expected}, got "
            f"{atf.get_node_parameter(node, 'topology')!r}"
        )


def test_redundant_topology_update_keeps_block_scheduling():
    """Verify block placement survives re-applying an unchanged topology."""

    # Assign every node to the block it already belongs to. This is the no-op
    # update that slurmctld itself performs on startup, on reconfigure, on
    # dynamic node re-registration, and on power save transitions.
    for block, nodes in BLOCKS.items():
        atf.run_command(
            f"scontrol update nodename={nodes} topology=default:{block}",
            user=atf.properties["slurm-user"],
            fatal=True,
        )

    for block, nodes in BLOCKS.items():
        for node in atf.node_range_to_list(nodes):
            assert_node_topology(node, f"default:{block}")

    # Two exclusive jobs that each fit in a block. With the aggregate bitmap
    # corrupted the generic node evaluation runs instead and lets an
    # allocation cross a block boundary.
    job_id_1 = atf.submit_job_sbatch(
        '-N2 --exclusive --mem=1 --wrap="sleep 60"', fatal=True
    )
    job_id_2 = atf.submit_job_sbatch(
        '-N3 --exclusive --mem=1 --wrap="sleep 60"', fatal=True
    )
    atf.wait_for_job_state(job_id_1, "RUNNING", fatal=True)
    atf.wait_for_job_state(job_id_2, "RUNNING", fatal=True)

    block_1 = block_of(atf.get_job_parameter(job_id_1, "NodeList"))
    block_2 = block_of(atf.get_job_parameter(job_id_2, "NodeList"))
    assert (
        block_1 != block_2
    ), f"Both jobs were packed into block {block_1} instead of separate blocks"

    # Five nodes are busy and the three idle ones are split across both
    # blocks, so no block of size 4 can hold another 3-node job.
    job_id_3 = atf.submit_job_sbatch(
        '-N3 --exclusive --mem=1 --wrap="sleep 60"', fatal=True
    )
    assert not atf.wait_for_job_state(
        job_id_3, "RUNNING", timeout=15, xfail=True
    ), "A 3-node job must not be placed across two blocks"
    assert atf.wait_for_job_state(
        job_id_3, "PENDING"
    ), "The rejected job should stay pending"
