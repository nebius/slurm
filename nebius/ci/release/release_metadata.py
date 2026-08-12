#!/usr/bin/env python3
"""Validate Nebius release metadata and derive immutable artifact names."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FIELD_RE = re.compile(r"^\s*([A-Za-z_]+):\s*(\S+)\s*$")
RELEASE_BRANCH_RE = re.compile(r"^nebius/(\d+\.\d+)$")
DOWNSTREAM_RELEASE_RE = re.compile(
    r"^nebius-(?P<revision>[1-9]\d*)(?:-rc(?P<release_candidate>\d+))?$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def read_meta(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = FIELD_RE.match(line)
        if match:
            fields[match.group(1).lower()] = match.group(2)
    return fields


def release_metadata(meta_path: Path, ref_name: str, source_commit: str) -> dict:
    branch_match = RELEASE_BRANCH_RE.fullmatch(ref_name)
    if not branch_match:
        raise ValueError("release ref must match nebius/<major>.<minor>")
    if not COMMIT_RE.fullmatch(source_commit):
        raise ValueError("source commit must be a full lowercase 40-character SHA")

    fields = read_meta(meta_path)
    required = ("name", "major", "minor", "micro", "version", "release", "api_current")
    missing = [field for field in required if field not in fields]
    if missing:
        raise ValueError(f"META is missing required fields: {', '.join(missing)}")
    if fields["name"] != "slurm":
        raise ValueError("META Name must be slurm")

    numeric_fields = ("major", "minor", "micro", "api_current")
    for field in numeric_fields:
        if not fields[field].isdigit():
            raise ValueError(f"META {field} must be numeric")

    release_line = f"{fields['major']}.{fields['minor']}"
    version = f"{release_line}.{fields['micro']}"
    if fields["version"] != version:
        raise ValueError(f"META Version must be {version}")
    if branch_match.group(1) != release_line:
        raise ValueError(
            f"release branch {ref_name} does not match META release line {release_line}"
        )
    release_match = DOWNSTREAM_RELEASE_RE.fullmatch(fields["release"])
    if not release_match:
        raise ValueError(
            "META Release must match nebius-<positive revision>[-rc<number>]"
        )
    prerelease = release_match.group("release_candidate") is not None

    api_current = int(fields["api_current"])
    if api_current < 2:
        raise ValueError("META API_CURRENT must allow current and previous parsers")
    parser_versions = [f"v0.0.{api_current - 1}", f"v0.0.{api_current}"]
    tag = "-".join(
        (
            "slurm",
            fields["major"],
            fields["minor"],
            fields["micro"],
            fields["release"],
        )
    )
    asset_prefix = f"slurm-{version}-{fields['release']}"

    return {
        "schema": 1,
        "project": "slurm",
        "source_commit": source_commit,
        "release_branch": ref_name,
        "release_line": release_line,
        "version": version,
        "downstream_release": fields["release"],
        "prerelease": prerelease,
        "version_string": f"{version}-{fields['release']}",
        "tag": tag,
        "asset_prefix": asset_prefix,
        "api": {
            "current": api_current,
            "parsers": parser_versions,
        },
    }


def write_github_output(path: Path, metadata: dict) -> None:
    values = {
        "tag": metadata["tag"],
        "asset_prefix": metadata["asset_prefix"],
        "release_line": metadata["release_line"],
        "version": metadata["version"],
        "downstream_release": metadata["downstream_release"],
        "prerelease": str(metadata["prerelease"]).lower(),
        "version_string": metadata["version_string"],
        "api_current": metadata["api"]["current"],
        "api_previous": metadata["api"]["current"] - 1,
    }
    with path.open("a", encoding="utf-8") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta", type=Path, required=True)
    parser.add_argument("--ref-name", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    metadata = release_metadata(args.meta, args.ref_name, args.source_commit)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.github_output:
        write_github_output(args.github_output, metadata)


if __name__ == "__main__":
    main()
