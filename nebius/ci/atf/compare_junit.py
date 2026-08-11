#!/usr/bin/env python3
"""Compare two pytest JUnit reports without hiding known baseline failures."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TestResult:
    identity: str
    file_name: str
    status: str


def _status(case: ET.Element) -> str:
    if case.find("error") is not None:
        return "error"
    if case.find("failure") is not None:
        return "failed"
    skipped = case.find("skipped")
    if skipped is not None:
        return "xfailed" if skipped.get("type") == "pytest.xfail" else "skipped"
    return "passed"


def load(path: Path) -> dict[str, TestResult]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"cannot read JUnit report {path}: {exc}") from exc

    results: dict[str, TestResult] = {}
    for case in root.iter("testcase"):
        file_name = case.get("file")
        classname = case.get("classname", "unknown")
        if not file_name:
            file_name = classname.replace(".", "/") + ".py"
        name = case.get("name", "unnamed")
        module = file_name.removesuffix(".py").replace("/", ".")
        class_path = ""
        if classname.startswith(module + "."):
            class_path = classname[len(module) + 1 :].replace(".", "::")
        identity = "::".join(part for part in (file_name, class_path, name) if part)
        if identity in results:
            raise ValueError(f"duplicate testcase identity in {path}: {identity}")
        results[identity] = TestResult(identity, file_name, _status(case))

    if not results:
        raise ValueError(f"JUnit report contains no testcases: {path}")
    return results


def load_patch_context(
    selection_path: Path, junit_path: Path | None
) -> tuple[set[str], dict[str, TestResult]]:
    try:
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"cannot read patch selection {selection_path}: {exc}"
        ) from exc
    if (
        not isinstance(selection, dict)
        or selection.get("schema") != 1
        or selection.get("policy") != "changed-files-on-h200-v1"
    ):
        raise ValueError("invalid patch selection schema or policy")
    selected = selection.get("selected_files")
    if not isinstance(selected, list):
        raise ValueError("invalid selected_files in patch selection")

    modified_files: set[str] = set()
    seen_files: set[str] = set()
    for item in selected:
        if not isinstance(item, dict):
            raise ValueError("invalid selected file in patch selection")
        path = item.get("path")
        change = item.get("change")
        if (
            not isinstance(path, str)
            or not path.startswith(("expect/test_", "tests/test_"))
            or not path.endswith(".py")
            or Path(path).is_absolute()
            or ".." in Path(path).parts
        ):
            raise ValueError(f"invalid selected test path: {path!r}")
        if path in seen_files:
            raise ValueError(f"duplicate selected test path: {path}")
        seen_files.add(path)
        if change not in {"added", "modified", "raw-expect-modified"}:
            raise ValueError(f"invalid selected test change for {path}: {change!r}")
        if change in {"modified", "raw-expect-modified"}:
            modified_files.add(path)

    if not modified_files:
        return set(), {}
    if junit_path is None:
        raise ValueError("modified patch tests require a patch JUnit report")
    patch_results = load(junit_path)
    covered_files = {result.file_name for result in patch_results.values()}
    missing_files = sorted(modified_files - covered_files)
    if missing_files:
        raise ValueError(
            "modified patch tests are missing from patch JUnit: "
            + ", ".join(missing_files)
        )
    return modified_files, patch_results


def compare(
    baseline: dict[str, TestResult],
    candidate: dict[str, TestResult],
    patch_files: set[str] | None = None,
    patch_results: dict[str, TestResult] | None = None,
) -> dict[str, object]:
    patch_files = patch_files or set()
    patch_results = patch_results or {}
    baseline_ids = set(baseline)
    candidate_ids = set(candidate)
    common = baseline_ids & candidate_ids
    changed = [
        {
            "test": identity,
            "baseline": baseline[identity].status,
            "candidate": candidate[identity].status,
        }
        for identity in sorted(common)
        if baseline[identity].status != candidate[identity].status
    ]
    improvements = [
        item for item in changed if item["candidate"] == "passed"
    ]
    regressions = []
    superseded_regressions = []
    for item in changed:
        if item["candidate"] == "passed":
            continue
        identity = str(item["test"])
        replacement = patch_results.get(identity)
        if (
            candidate[identity].file_name in patch_files
            and replacement is not None
            and replacement.status == "passed"
        ):
            superseded_regressions.append(
                {**item, "patch_candidate": replacement.status}
            )
        else:
            regressions.append(item)
    missing = sorted(baseline_ids - candidate_ids)
    added = [
        {"test": identity, "status": candidate[identity].status}
        for identity in sorted(candidate_ids - baseline_ids)
    ]
    bad_added = [item for item in added if item["status"] != "passed"]
    return {
        "ok": not regressions and not missing and not bad_added,
        "baseline_total": len(baseline),
        "candidate_total": len(candidate),
        "common_total": len(common),
        "baseline_counts": dict(
            sorted(Counter(x.status for x in baseline.values()).items())
        ),
        "candidate_counts": dict(
            sorted(Counter(x.status for x in candidate.values()).items())
        ),
        "changed": changed,
        "improvements": improvements,
        "regressions": regressions,
        "superseded_regressions": superseded_regressions,
        "validated_patch_files": sorted(patch_files),
        "missing": missing,
        "added": added,
        "bad_added": bad_added,
    }


def markdown(result: dict[str, object]) -> str:
    verdict = "PASS" if result["ok"] else "FAIL"
    lines = [
        f"# Slurm ATF comparison: {verdict}",
        "",
        "| Variant | passed | skipped | xfailed | failed | error | total |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label in ("baseline", "candidate"):
        counts = result[f"{label}_counts"]
        assert isinstance(counts, dict)
        values = [
            str(counts.get(x, 0))
            for x in ("passed", "skipped", "xfailed", "failed", "error")
        ]
        lines.append(
            f"| {label} | " + " | ".join(values) + f" | {result[f'{label}_total']} |"
        )

    sections = (
        ("Regressions or masked outcomes", result["regressions"]),
        (
            "Frozen-test regressions superseded by passing patch tests",
            result["superseded_regressions"],
        ),
        ("Improvements to passed", result["improvements"]),
        ("Missing from candidate", result["missing"]),
        ("Candidate-only tests", result["added"]),
    )
    for title, items in sections:
        assert isinstance(items, list)
        lines.extend(["", f"## {title} ({len(items)})", ""])
        if not items:
            lines.append("None.")
        elif isinstance(items[0], str):
            lines.extend(f"- `{item}`" for item in items)
        else:
            for item in items:
                rendered = (
                    f"- `{item['test']}`: {item.get('baseline', '')} -> "
                    f"**{item.get('candidate', item.get('status', ''))}**"
                )
                if "patch_candidate" in item:
                    rendered += (
                        f"; candidate patch test -> **{item['patch_candidate']}**"
                    )
                lines.append(rendered)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--patch-selection", type=Path)
    parser.add_argument("--patch-junit", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    try:
        if args.patch_junit is not None and args.patch_selection is None:
            raise ValueError("--patch-junit requires --patch-selection")
        patch_files: set[str] = set()
        patch_results: dict[str, TestResult] = {}
        if args.patch_selection is not None:
            patch_files, patch_results = load_patch_context(
                args.patch_selection, args.patch_junit
            )
        result = compare(
            load(args.baseline),
            load(args.candidate),
            patch_files,
            patch_results,
        )
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    rendered = markdown(result)
    print(rendered, end="")
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if args.markdown:
        args.markdown.write_text(rendered)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
