#!/usr/bin/env python3
"""Validate and aggregate the fixed 4 CPU + 1 H200 ATF topology."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from merge_junit import merge_labeled_reports


EXPECTED_SHARDS = {
    "cpu-0": (0, "generic"),
    "cpu-1": (1, "generic"),
    "cpu-2": (2, "generic"),
    "cpu-3": (3, "generic"),
    "gpu": (4, "h200"),
}


def read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def require_file(directory: Path, name: str) -> Path:
    path = directory / name
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing regular shard evidence file: {path}")
    return path


def nested(value: dict[str, object], *keys: str) -> object:
    current: object = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"missing metadata field: {'.'.join(keys)}")
        current = current[key]
    return current


def status(directory: Path, name: str) -> int:
    raw = require_file(directory, name).read_text(encoding="utf-8").strip()
    if raw not in {"0", "1"}:
        raise ValueError(f"invalid pytest status in {directory / name}: {raw!r}")
    return int(raw)


def junit_files(path: Path) -> set[str]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"cannot read JUnit report {path}: {exc}") from exc
    files = {case.get("file", "") for case in root.iter("testcase")}
    files.discard("")
    if not files:
        raise ValueError(f"JUnit report contains no testcase file paths: {path}")
    return files


def validate_selections(
    shards: dict[str, Path], phase: str
) -> dict[str, object]:
    manifests = {
        shard_id: read_json(require_file(directory, f"{phase}-selection.json"))
        for shard_id, directory in shards.items()
    }
    reference = manifests["cpu-0"]
    assignments = nested(reference, "assignments")
    inventory_hash = nested(reference, "all_files_sha256")
    algorithm = nested(reference, "algorithm")
    if not isinstance(assignments, dict) or algorithm != "sha256-path-v1":
        raise ValueError(f"invalid {phase} selection manifest")

    selected_union: set[str] = set()
    for shard_id, manifest in manifests.items():
        index, profile = EXPECTED_SHARDS[shard_id]
        if nested(manifest, "assignments") != assignments:
            raise ValueError(f"{phase} assignments differ on {shard_id}")
        if nested(manifest, "all_files_sha256") != inventory_hash:
            raise ValueError(f"{phase} inventory differs on {shard_id}")
        if nested(manifest, "shard", "index") != index:
            raise ValueError(f"wrong shard index for {shard_id}")
        if nested(manifest, "shard", "total") != len(EXPECTED_SHARDS):
            raise ValueError(f"wrong shard total for {shard_id}")
        if nested(manifest, "shard", "vm_profile") != profile:
            raise ValueError(f"wrong VM profile for {shard_id}")
        selected = nested(manifest, "selected_files")
        if not isinstance(selected, list) or not all(
            isinstance(path, str) for path in selected
        ):
            raise ValueError(f"invalid selected files for {shard_id}")
        expected = sorted(
            path for path, owner in assignments.items() if owner == index
        )
        if selected != expected:
            raise ValueError(f"selected {phase} files do not match assignments")
        overlap = selected_union.intersection(selected)
        if overlap:
            raise ValueError(f"duplicate {phase} file assignment: {min(overlap)}")
        selected_union.update(selected)

        report_files = junit_files(
            require_file(shards[shard_id], f"{phase}-junit.xml")
        )
        selected_set = set(selected)
        unexpected = report_files.difference(selected_set)
        missing = selected_set.difference(report_files)
        if unexpected:
            raise ValueError(
                f"{shard_id} ran unassigned {phase} file: {min(unexpected)}"
            )
        if missing:
            raise ValueError(
                f"{shard_id} produced no {phase} testcase for: {min(missing)}"
            )

    if selected_union != set(assignments):
        raise ValueError(f"incomplete {phase} file coverage")
    return {
        "algorithm": algorithm,
        "all_files_sha256": inventory_hash,
        "assignments": assignments,
    }


def unique(values: list[object], label: str) -> object:
    rendered = {json.dumps(value, sort_keys=True) for value in values}
    if len(rendered) != 1:
        raise ValueError(f"shards disagree about {label}")
    return values[0]


def aggregate(
    input_dir: Path,
    output_dir: Path,
    kind: str,
    release_line: str,
    run_id: str,
    run_attempt: str,
    run_url: str,
) -> None:
    metadata_paths = sorted(input_dir.rglob("run-metadata.json"))
    if len(metadata_paths) != len(EXPECTED_SHARDS):
        raise ValueError(
            f"expected {len(EXPECTED_SHARDS)} shard artifacts, found "
            f"{len(metadata_paths)}"
        )

    shards: dict[str, Path] = {}
    metadata: dict[str, dict[str, object]] = {}
    for path in metadata_paths:
        item = read_json(path)
        shard_id = nested(item, "shard", "id")
        if not isinstance(shard_id, str) or shard_id not in EXPECTED_SHARDS:
            raise ValueError(f"unexpected shard id in {path}: {shard_id!r}")
        if shard_id in shards:
            raise ValueError(f"duplicate shard evidence: {shard_id}")
        shards[shard_id] = path.parent
        metadata[shard_id] = item
    if set(shards) != set(EXPECTED_SHARDS):
        raise ValueError("the fixed shard topology is incomplete")

    for shard_id, item in metadata.items():
        index, profile = EXPECTED_SHARDS[shard_id]
        if nested(item, "kind") != kind:
            raise ValueError(f"wrong run kind on {shard_id}")
        if nested(item, "release_line") != release_line:
            raise ValueError(f"wrong release line on {shard_id}")
        if nested(item, "shard", "index") != index:
            raise ValueError(f"wrong metadata index on {shard_id}")
        if nested(item, "shard", "total") != len(EXPECTED_SHARDS):
            raise ValueError(f"wrong metadata total on {shard_id}")
        if nested(item, "vm", "atf_profile") != profile:
            raise ValueError(f"wrong metadata VM profile on {shard_id}")

    source = unique([nested(item, "source") for item in metadata.values()], "source")
    tests = unique([nested(item, "tests") for item in metadata.values()], "tests")
    infrastructure = unique(
        [nested(item, "infrastructure") for item in metadata.values()],
        "infrastructure",
    )

    selections = {
        phase: validate_selections(shards, phase) for phase in ("expect", "python")
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    copied_shards = output_dir / "shards"
    for shard_id, directory in shards.items():
        shutil.copytree(directory, copied_shards / shard_id)

    ordered_ids = list(EXPECTED_SHARDS)
    merge_labeled_reports(
        [(shard_id, shards[shard_id] / "junit.xml") for shard_id in ordered_ids],
        output_dir / "junit.xml",
    )
    merge_labeled_reports(
        [
            (shard_id, shards[shard_id] / "expect-junit.xml")
            for shard_id in ordered_ids
        ],
        output_dir / "expect-junit.xml",
    )
    merge_labeled_reports(
        [
            (shard_id, shards[shard_id] / "python-junit.xml")
            for shard_id in ordered_ids
        ],
        output_dir / "python-junit.xml",
    )

    expect_status = max(status(directory, "expect-exit-status") for directory in shards.values())
    python_status = max(status(directory, "python-exit-status") for directory in shards.values())
    pytest_status = max(expect_status, python_status)
    for name, value in (
        ("expect-exit-status", expect_status),
        ("python-exit-status", python_status),
        ("pytest-exit-status", pytest_status),
    ):
        (output_dir / name).write_text(f"{value}\n", encoding="utf-8")

    profiles: dict[str, dict[str, object]] = {}
    vm: dict[str, dict[str, object]] = {}
    for group, ids in (("cpu", ordered_ids[:4]), ("gpu", ["gpu"])):
        group_metadata = [metadata[shard_id] for shard_id in ids]
        image_id = unique(
            [nested(item, "vm", "image_id") for item in group_metadata],
            f"{group} image",
        )
        shape = unique(
            [nested(item, "vm", "shape") for item in group_metadata],
            f"{group} shape",
        )
        profile = unique(
            [nested(item, "vm", "atf_profile") for item in group_metadata],
            f"{group} profile",
        )
        image_documents = [
            read_json(require_file(shards[shard_id], "image-metadata.json"))
            for shard_id in ids
        ]
        profiles[group] = unique(image_documents, f"{group} image metadata")
        vm[group] = {
            "count": len(ids),
            "image_id": image_id,
            "shape": shape,
            "atf_profile": profile,
        }

    image_metadata = {
        "schema": 1,
        "topology": "4cpu+1gpu",
        "cpu": profiles["cpu"],
        "gpu": profiles["gpu"],
    }
    (output_dir / "image-metadata.json").write_text(
        json.dumps(image_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    shard_entries = [
        {
            "id": shard_id,
            "index": EXPECTED_SHARDS[shard_id][0],
            "vm_profile": EXPECTED_SHARDS[shard_id][1],
        }
        for shard_id in ordered_ids
    ]
    release = nested(read_json(require_file(shards["cpu-0"], "run-manifest.json")), "release")
    manifest = {
        "schema": 2,
        "release": release,
        "tests": {"master_commit": nested(tests, "commit")},
        "sharding": {
            "topology": "4cpu+1gpu",
            "algorithm": "sha256-path-v1",
            "shards": shard_entries,
            "inventories": {
                phase: selections[phase]["all_files_sha256"]
                for phase in selections
            },
        },
    }
    (output_dir / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    junit_sha256 = hashlib.sha256((output_dir / "junit.xml").read_bytes()).hexdigest()
    run_metadata = {
        "schema": 2,
        "kind": kind,
        "release_line": release_line,
        "source": source,
        "tests": tests,
        "infrastructure": infrastructure,
        "vm": {"topology": "4cpu+1gpu", **vm},
        "sharding": {
            "algorithm": "sha256-path-v1",
            "shards": shard_entries,
            "inventories": {
                phase: selections[phase]["all_files_sha256"]
                for phase in selections
            },
        },
        "result": {
            "junit_sha256": junit_sha256,
            "pytest_exit_status": pytest_status,
            "expect_exit_status": expect_status,
            "python_exit_status": python_status,
        },
        "workflow": {
            "run_id": run_id,
            "run_attempt": run_attempt,
            "run_url": run_url,
        },
    }
    (output_dir / "run-metadata.json").write_text(
        json.dumps(run_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "selection-inventory.json").write_text(
        json.dumps(selections, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with (output_dir / "pytest.out").open("w", encoding="utf-8") as combined:
        for shard_id in ordered_ids:
            combined.write(f"===== SHARD {shard_id} =====\n")
            combined.write(require_file(shards[shard_id], "pytest.out").read_text(encoding="utf-8"))
            combined.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--kind", required=True, choices=("baseline", "candidate"))
    parser.add_argument("--release-line", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args()
    try:
        aggregate(
            args.input_dir,
            args.output_dir,
            args.kind,
            args.release_line,
            args.run_id,
            args.run_attempt,
            args.run_url,
        )
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
