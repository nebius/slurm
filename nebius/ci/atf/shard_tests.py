#!/usr/bin/env python3
"""Create a stable, auditable, file-count-balanced ATF selection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


GPU_REQUIRED = {
    "expect/test_39_9.py",
    "expect/test_40_8.py",
}

GPU_INCOMPATIBLE = {
    # The legacy helper stores affinity masks in uint64_t and skips hosts with
    # more than 64 hardware threads. The H200 shape exposes 128 threads.
    "expect/test_1_91.py",
}

ALGORITHM = "balanced-hash-v1"


def discover(test_root: Path, phase: str) -> list[str]:
    directory = test_root / ("expect" if phase == "expect" else "tests")
    return sorted(
        path.relative_to(test_root).as_posix()
        for path in directory.glob("test_*.py")
        if path.is_file()
    )


def build_assignments(
    files: list[str], shard_total: int, gpu_index: int
) -> dict[str, int]:
    """Spread files evenly while keeping hardware GPU tests on H200.

    Hashing the paths first prevents related, similarly named tests from being
    clustered together. Greedily assigning that stable order to the currently
    smallest shard guarantees that file counts differ by at most one unless a
    capability-pinned set is itself too large to balance.
    """

    assignments: dict[str, int] = {}
    counts = [0] * shard_total

    for path in sorted(GPU_REQUIRED.intersection(files)):
        assignments[path] = gpu_index
        counts[gpu_index] += 1

    generic_files = sorted(
        (path for path in files if path not in assignments),
        key=lambda path: (hashlib.sha256(path.encode()).digest(), path),
    )
    for path in generic_files:
        eligible = (
            range(gpu_index)
            if path in GPU_INCOMPATIBLE
            else range(shard_total)
        )
        owner = min(eligible, key=lambda index: (counts[index], index))
        assignments[path] = owner
        counts[owner] += 1

    return assignments


def build_manifest(
    test_root: Path,
    phase: str,
    shard_id: str,
    shard_index: int,
    shard_total: int,
    vm_profile: str,
) -> dict[str, object]:
    if shard_total < 2:
        raise ValueError("shard_total must be at least 2")
    if not 0 <= shard_index < shard_total:
        raise ValueError("shard_index must be within the shard range")
    if vm_profile not in {"generic", "h200"}:
        raise ValueError("vm_profile must be generic or h200")

    gpu_index = shard_total - 1
    if (shard_index == gpu_index) != (vm_profile == "h200"):
        raise ValueError("the last shard must be the only h200 shard")

    files = discover(test_root, phase)
    if not files:
        raise ValueError(f"no {phase} tests found below {test_root}")
    assignments = build_assignments(files, shard_total, gpu_index)
    selected = [path for path in files if assignments[path] == shard_index]
    if not selected:
        raise ValueError(f"shard {shard_id} selected no {phase} tests")

    inventory = json.dumps(files, separators=(",", ":"), ensure_ascii=True)
    return {
        "schema": 1,
        "algorithm": ALGORITHM,
        "phase": phase,
        "shard": {
            "id": shard_id,
            "index": shard_index,
            "total": shard_total,
            "vm_profile": vm_profile,
        },
        "all_files_sha256": hashlib.sha256(inventory.encode()).hexdigest(),
        "assignments": assignments,
        "selected_files": selected,
        "gpu_required_files": sorted(GPU_REQUIRED.intersection(files)),
        "gpu_incompatible_files": sorted(GPU_INCOMPATIBLE.intersection(files)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-root", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=("expect", "python"))
    parser.add_argument("--shard-id", required=True)
    parser.add_argument("--shard-index", required=True, type=int)
    parser.add_argument("--shard-total", required=True, type=int)
    parser.add_argument("--vm-profile", required=True, choices=("generic", "h200"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        manifest = build_manifest(
            args.test_root,
            args.phase,
            args.shard_id,
            args.shard_index,
            args.shard_total,
            args.vm_profile,
        )
    except ValueError as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
