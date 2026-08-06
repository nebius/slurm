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
        results[identity] = TestResult(identity, _status(case))

    if not results:
        raise ValueError(f"JUnit report contains no testcases: {path}")
    return results


def compare(
    baseline: dict[str, TestResult], candidate: dict[str, TestResult]
) -> dict[str, object]:
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
    regressions = [
        item for item in changed if item["candidate"] != "passed"
    ]
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
            lines.extend(
                f"- `{item['test']}`: {item.get('baseline', '')} -> "
                f"**{item.get('candidate', item.get('status', ''))}**"
                for item in items
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    try:
        result = compare(load(args.baseline), load(args.candidate))
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
