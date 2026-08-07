import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from aggregate_shards import EXPECTED_SHARDS, aggregate


def write_junit(path: Path, file_name: str) -> None:
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", {"name": "pytest"})
    ET.SubElement(
        suite,
        "testcase",
        {"file": file_name, "classname": file_name, "name": "test_ok", "time": "1"},
    )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def make_evidence(root: Path) -> None:
    ids = list(EXPECTED_SHARDS)
    for shard_id, (index, profile) in EXPECTED_SHARDS.items():
        directory = root / f"artifact-{shard_id}"
        directory.mkdir(parents=True)
        metadata = {
            "schema": 1,
            "kind": "baseline",
            "release_line": "26.05",
            "source": {"ref": "refs/heads/test", "commit": "a" * 40},
            "tests": {"commit": "b" * 40},
            "infrastructure": {"repository": "nebius/infra", "commit": "c" * 40},
            "vm": {
                "image_id": "gpu-image" if profile == "h200" else "cpu-image",
                "shape": "gpu-shape" if profile == "h200" else "cpu-shape",
                "atf_profile": profile,
            },
            "shard": {"id": shard_id, "index": index, "total": 5},
        }
        (directory / "run-metadata.json").write_text(json.dumps(metadata))
        (directory / "run-manifest.json").write_text(
            json.dumps({"release": {"line": "26.05", "commit": "a" * 40}})
        )
        (directory / "image-metadata.json").write_text(
            json.dumps({"schema": 1, "profile": profile})
        )
        for phase, prefix in (("expect", "expect"), ("python", "tests")):
            assignments = {
                f"{prefix}/test_{owner}.py": owner for owner in range(5)
            }
            selected = [path for path, owner in assignments.items() if owner == index]
            selection = {
                "schema": 1,
                "algorithm": "sha256-path-v1",
                "phase": phase,
                "all_files_sha256": f"{phase}-inventory",
                "assignments": assignments,
                "selected_files": selected,
                "shard": {
                    "id": shard_id,
                    "index": index,
                    "total": 5,
                    "vm_profile": profile,
                },
            }
            (directory / f"{phase}-selection.json").write_text(
                json.dumps(selection)
            )
            write_junit(directory / f"{phase}-junit.xml", selected[0])
        write_junit(directory / "junit.xml", f"combined/test_{index}.py")
        for name in ("expect-exit-status", "python-exit-status", "pytest-exit-status"):
            (directory / name).write_text("0\n")
        (directory / "pytest.out").write_text(f"{shard_id} output\n")


class AggregateShardsTest(unittest.TestCase):
    def test_aggregate_fixed_topology(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            output = Path(root) / "output"
            make_evidence(source)
            aggregate(
                source,
                output,
                "baseline",
                "26.05",
                "123",
                "1",
                "https://example.test/run/123",
            )
            metadata = json.loads(
                (output / "run-metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["vm"]["topology"], "4cpu+1gpu")
            self.assertEqual(metadata["vm"]["cpu"]["count"], 4)
            self.assertEqual(metadata["vm"]["gpu"]["count"], 1)
            self.assertEqual(metadata["result"]["pytest_exit_status"], 0)
            cases = list(
                ET.parse(output / "junit.xml").getroot().iter("testcase")
            )
            self.assertEqual(len(cases), 5)

    def test_rejects_missing_shard_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            output = Path(root) / "output"
            make_evidence(source)
            (source / "artifact-gpu" / "run-metadata.json").unlink()
            with self.assertRaisesRegex(ValueError, "expected 5 shard artifacts"):
                aggregate(
                    source,
                    output,
                    "baseline",
                    "26.05",
                    "123",
                    "1",
                    "https://example.test/run/123",
                )


if __name__ == "__main__":
    unittest.main()
