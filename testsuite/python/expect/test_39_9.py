############################################################################
# Copyright (C) SchedMD LLC.
############################################################################
import os

import pytest

import atf


@pytest.fixture(scope="module", autouse=True)
def setup():
    atf.require_expect()

    atf.require_config_parameter_includes("GresTypes", "gpu")
    atf.require_config_file(
        "gres.conf",
        "NodeName=node0 AutoDetect=nvml",
    )

    # The GPU shard normally uses the generic ATF profile so synthetic GRES
    # tests remain isolated from the physical devices.  Advertise the GPUs on
    # the existing node0 only for this test.  Do this after writing gres.conf
    # so a running cluster is never restarted with a Gres definition that
    # AutoDetect cannot satisfy.
    gpu_inventory = atf.run_command_output(
        "nvidia-smi --query-gpu=index --format=csv,noheader,nounits",
        fatal=True,
    )
    gpu_count = len([line for line in gpu_inventory.splitlines() if line.strip()])
    if gpu_count == 0:
        pytest.fail("The H200 ATF profile has no visible GPUs")
    atf.set_node_parameter("node0", "Gres", f"gpu:{gpu_count}")

    atf.require_nodes(1, [("CPUs", 2), ("Gres", "gpu:1")])
    atf.require_slurm_running()


@pytest.mark.skipif(
    os.environ.get("SLURM_ATF_VM_PROFILE") != "h200",
    reason="Requires the dedicated H200 ATF profile with NVML",
)
def test_expect():
    atf.run_expect_test()
