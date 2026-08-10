#!/usr/bin/env python3
"""Require every patch-owned testcase to run and pass on the H200 VM."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def _read_selection(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read patch selection {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("invalid patch selection schema")
    selected = value.get("selected_files")
    if not isinstance(selected, list) or not all(
        isinstance(item, dict) and isinstance(item.get("path"), str)
        for item in selected
    ):
        raise ValueError("invalid selected_files in patch selection")
    return value


def _status(case: ET.Element) -> str:
    if case.find("error") is not None:
        return "error"
    if case.find("failure") is not None:
        return "failed"
    skipped = case.find("skipped")
    if skipped is not None:
        return "xfailed" if skipped.get("type") == "pytest.xfail" else "skipped"
    return "passed"


def validate(selection_path: Path, junit_path: Path | None) -> dict[str, object]:
    selection = _read_selection(selection_path)
    selected = {
        str(item["path"]) for item in selection["selected_files"]  # type: ignore[index]
    }
    if not selected:
        if junit_path is not None and junit_path.exists():
            raise ValueError("patch JUnit exists although no patch tests were selected")
        return {
            "ok": True,
            "selected_files": 0,
            "testcases": 0,
            "counts": {},
            "missing_files": [],
            "unexpected_files": [],
            "non_passing": [],
        }
    if junit_path is None:
        raise ValueError("patch tests were selected but no JUnit path was provided")
    try:
        root = ET.parse(junit_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"cannot read patch JUnit {junit_path}: {exc}") from exc

    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError("patch JUnit contains no testcases")
    files = {case.get("file", "") for case in cases}
    files.discard("")
    missing = sorted(selected - files)
    unexpected = sorted(files - selected)
    results = [
        {
            "test": "::".join(
                part
                for part in (
                    case.get("file", ""),
                    case.get("classname", ""),
                    case.get("name", ""),
                )
                if part
            ),
            "status": _status(case),
        }
        for case in cases
    ]
    non_passing = [item for item in results if item["status"] != "passed"]
    counts = dict(sorted(Counter(item["status"] for item in results).items()))
    return {
        "ok": not missing and not unexpected and not non_passing,
        "selected_files": len(selected),
        "testcases": len(cases),
        "counts": counts,
        "missing_files": missing,
        "unexpected_files": unexpected,
        "non_passing": non_passing,
    }


def markdown(result: dict[str, object]) -> str:
    verdict = "PASS" if result["ok"] else "FAIL"
    lines = [
        f"# Patch-specific H200 tests: {verdict}",
        "",
        f"- Selected files: `{result['selected_files']}`",
        f"- Collected testcases: `{result['testcases']}`",
        f"- Outcomes: `{json.dumps(result['counts'], sort_keys=True)}`",
    ]
    for title, key in (
        ("Missing selected files", "missing_files"),
        ("Unexpected files", "unexpected_files"),
        ("Non-passing testcases", "non_passing"),
    ):
        items = result[key]
        assert isinstance(items, list)
        lines.extend(["", f"## {title} ({len(items)})", ""])
        if not items:
            lines.append("None.")
        else:
            for item in items:
                if isinstance(item, str):
                    lines.append(f"- `{item}`")
                else:
                    lines.append(f"- `{item['test']}`: **{item['status']}**")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("selection", type=Path)
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    try:
        result = validate(args.selection, args.junit)
    except ValueError as exc:
        parser.error(str(exc))
    rendered = markdown(result)
    print(rendered, end="")
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if args.markdown:
        args.markdown.write_text(rendered)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
