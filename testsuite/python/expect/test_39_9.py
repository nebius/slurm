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
    atf.require_nodes(1, [("CPUs", 2), ("Gres", "gpu:1")])

    atf.require_config_file(
        "gres.conf",
        "NodeName=node0 AutoDetect=nvml",
    )
    atf.require_slurm_running()


@pytest.mark.skipif(
    os.environ.get("SLURM_ATF_VM_PROFILE") != "h200",
    reason="Requires the dedicated H200 ATF profile with NVML",
)
def test_expect():
    atf.run_expect_test()
