#!/usr/bin/env python3
"""Select tests owned by a patch without changing the frozen baseline suite."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


RUNNABLE_DIRECTORIES = {
    "expect": Path("testsuite/python/expect"),
    "python": Path("testsuite/python/tests"),
}
RAW_EXPECT_DIRECTORY = Path("testsuite/expect")
RAW_EXPECT_PATTERN = re.compile(r"^test([0-9]+)\.([0-9]+)(?:\.|$)")


def _files(root: Path, directory: Path, pattern: str = "*") -> dict[str, Path]:
    base = root / directory
    if not base.is_dir():
        raise ValueError(f"missing test directory: {base}")
    result: dict[str, Path] = {}
    for path in sorted(base.rglob(pattern)):
        if path.is_symlink():
            raise ValueError(f"test tree contains a symlink: {path}")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            result[relative] = path
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _changed(candidate: Path, baseline: Path | None) -> bool:
    return baseline is None or candidate.read_bytes() != baseline.read_bytes()


def select(candidate_root: Path, baseline_root: Path) -> dict[str, object]:
    candidate_root = candidate_root.resolve()
    baseline_root = baseline_root.resolve()
    selected: dict[str, dict[str, str]] = {}
    removed: list[str] = []

    for phase, directory in RUNNABLE_DIRECTORIES.items():
        candidate = {
            relative: path
            for relative, path in _files(
                candidate_root, directory, "test_*.py"
            ).items()
            if path.parent == candidate_root / directory
        }
        baseline = {
            relative: path
            for relative, path in _files(
                baseline_root, directory, "test_*.py"
            ).items()
            if path.parent == baseline_root / directory
        }
        for relative, path in candidate.items():
            old = baseline.get(relative)
            if _changed(path, old):
                selected[relative] = {
                    "path": relative.removeprefix("testsuite/python/"),
                    "repository_path": relative,
                    "phase": phase,
                    "change": "added" if old is None else "modified",
                    "sha256": _sha256(path),
                }
        removed.extend(sorted(set(baseline) - set(candidate)))

    candidate_raw = _files(candidate_root, RAW_EXPECT_DIRECTORY)
    baseline_raw = _files(baseline_root, RAW_EXPECT_DIRECTORY)
    changed_raw = [
        relative
        for relative, path in candidate_raw.items()
        if _changed(path, baseline_raw.get(relative))
    ]
    removed.extend(sorted(set(baseline_raw) - set(candidate_raw)))

    unmapped_raw: list[str] = []
    for relative in changed_raw:
        name = Path(relative).name
        match = RAW_EXPECT_PATTERN.match(name)
        if match is None:
            unmapped_raw.append(relative)
            continue
        wrapper = (
            Path("testsuite/python/expect")
            / f"test_{match.group(1)}_{match.group(2)}.py"
        ).as_posix()
        wrapper_path = candidate_root / wrapper
        if not wrapper_path.is_file() or wrapper_path.is_symlink():
            unmapped_raw.append(relative)
            continue
        entry = selected.setdefault(
            wrapper,
            {
                "path": wrapper.removeprefix("testsuite/python/"),
                "repository_path": wrapper,
                "phase": "expect",
                "change": "raw-expect-modified",
                "sha256": _sha256(wrapper_path),
            },
        )
        if entry["change"] != "added":
            entry["change"] = "raw-expect-modified"

    candidate_support = _files(candidate_root, Path("testsuite/python"))
    baseline_support = _files(baseline_root, Path("testsuite/python"))
    removed.extend(sorted(set(baseline_support) - set(candidate_support)))
    runnable_paths = {
        relative
        for directory in RUNNABLE_DIRECTORIES.values()
        for relative, path in _files(candidate_root, directory, "test_*.py").items()
        if path.parent == candidate_root / directory
    }
    support_files = sorted(
        relative
        for relative, path in candidate_support.items()
        if relative not in runnable_paths
        and _changed(path, baseline_support.get(relative))
    )

    if removed:
        rendered = ", ".join(sorted(set(removed))[:5])
        raise ValueError(
            "patches may not remove frozen baseline test files; removed: "
            f"{rendered}"
        )
    if unmapped_raw and not selected:
        rendered = ", ".join(unmapped_raw[:5])
        raise ValueError(
            "changed Expect support files have no runnable Python wrapper; "
            f"add or modify the corresponding test wrapper: {rendered}"
        )
    if support_files and not selected:
        rendered = ", ".join(support_files[:5])
        raise ValueError(
            "changed Python test support files have no patch-owned runnable test; "
            f"add or modify a test_*.py file: {rendered}"
        )

    ordered = [selected[path] for path in sorted(selected)]
    inventory = json.dumps(ordered, sort_keys=True, separators=(",", ":"))
    return {
        "schema": 1,
        "policy": "changed-files-on-h200-v1",
        "selected_files": ordered,
        "selected_files_sha256": hashlib.sha256(inventory.encode()).hexdigest(),
        "support_files": support_files,
        "unmapped_expect_support_files": sorted(unmapped_raw),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = select(args.candidate, args.baseline)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(len(result["selected_files"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
