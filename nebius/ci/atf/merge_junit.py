#!/usr/bin/env python3
"""Merge the Expect-wrapper and Python pytest JUnit reports deterministically."""

from __future__ import annotations

import argparse
import copy
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


_OUTCOME_PRIORITY = {"skipped": 1, "failure": 2, "error": 3}


def _testcase_identity(case: ET.Element) -> tuple[str, str, str]:
    return (
        case.get("file", ""),
        case.get("classname", ""),
        case.get("name", ""),
    )


def _suites(path: Path) -> list[ET.Element]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"cannot read JUnit report {path}: {exc}") from exc

    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
    else:
        raise ValueError(f"unsupported JUnit root in {path}: {root.tag}")
    if not suites or not any(suite.findall(".//testcase") for suite in suites):
        raise ValueError(f"JUnit report contains no testcases: {path}")
    return suites


def _merge_duplicate_case(target: ET.Element, duplicate: ET.Element) -> None:
    """Collapse pytest call/teardown records into one comparable testcase."""
    target_time = float(target.get("time", "0"))
    duplicate_time = float(duplicate.get("time", "0"))
    target.set("time", f"{target_time + duplicate_time:.6f}")

    outcomes = [
        child
        for case in (target, duplicate)
        for child in case
        if child.tag in _OUTCOME_PRIORITY
    ]
    if outcomes:
        winning_outcome = max(
            outcomes, key=lambda child: _OUTCOME_PRIORITY[child.tag]
        )
        for child in list(target):
            if child.tag in _OUTCOME_PRIORITY:
                target.remove(child)
        target.append(copy.deepcopy(winning_outcome))

    # The raw phase reports remain in the artifact. Preserve additional output
    # in the aggregate report while avoiding duplicate pytest properties.
    for child in duplicate:
        if child.tag not in _OUTCOME_PRIORITY and child.tag != "properties":
            target.append(copy.deepcopy(child))


def _coalesce_cases(
    suite: ET.Element,
    seen: dict[tuple[str, str, str], ET.Element],
) -> None:
    for parent in suite.iter():
        for case in list(parent):
            if case.tag != "testcase":
                continue
            identity = _testcase_identity(case)
            previous = seen.get(identity)
            if previous is None:
                seen[identity] = case
                continue
            _merge_duplicate_case(previous, case)
            parent.remove(case)


def _suite_totals(suite: ET.Element) -> dict[str, float | int]:
    cases = suite.findall(".//testcase")
    return {
        "tests": len(cases),
        "failures": sum(case.find("failure") is not None for case in cases),
        "errors": sum(case.find("error") is not None for case in cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
        "time": sum(float(case.get("time", "0")) for case in cases),
    }


def merge(expect_path: Path, python_path: Path, output_path: Path) -> None:
    output = ET.Element("testsuites", {"name": "slurm-atf"})
    seen: set[tuple[str, str, str]] = set()
    totals: dict[str, float | int] = {
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "time": 0.0,
    }

    for phase, path in (("expect", expect_path), ("python", python_path)):
        phase_suites: list[ET.Element] = []
        phase_seen: dict[tuple[str, str, str], ET.Element] = {}
        for source_suite in _suites(path):
            suite = copy.deepcopy(source_suite)
            original_name = suite.get("name", "pytest")
            suite.set("name", f"{phase}/{original_name}")
            _coalesce_cases(suite, phase_seen)
            phase_suites.append(suite)

        overlap = seen.intersection(phase_seen)
        if overlap:
            identity = min(overlap)
            rendered = "::".join(part for part in identity if part)
            raise ValueError(f"duplicate testcase across phases: {rendered}")
        seen.update(phase_seen)

        for suite in phase_suites:
            suite_totals = _suite_totals(suite)
            for key in ("tests", "failures", "errors", "skipped"):
                suite.set(key, str(suite_totals[key]))
                totals[key] += int(suite_totals[key])
            suite.set("time", f"{float(suite_totals['time']):.6f}")
            totals["time"] += float(suite_totals["time"])
            output.append(suite)

    for key in ("tests", "failures", "errors", "skipped"):
        output.set(key, str(totals[key]))
    if not math.isfinite(float(totals["time"])):
        raise ValueError("non-finite testcase duration in JUnit input")
    output.set("time", f"{float(totals['time']):.6f}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp"
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        ET.ElementTree(output).write(
            temporary_path, encoding="utf-8", xml_declaration=True
        )
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("expect", type=Path)
    parser.add_argument("python", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        merge(args.expect, args.python, args.output)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
