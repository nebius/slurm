#!/usr/bin/env python3

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from select_patch_tests import select
from validate_patch_tests import validate


def make_tree(root: Path) -> None:
    for directory in (
        root / "testsuite/python/expect",
        root / "testsuite/python/tests",
        root / "testsuite/expect",
    ):
        directory.mkdir(parents=True)
    (root / "testsuite/python/run-tests-python").write_text("runner\n")
    (root / "testsuite/python/expect/test_1_1.py").write_text(
        "def test_1_1(): pass\n"
    )
    (root / "testsuite/python/tests/test_100_1.py").write_text(
        "def test_100_1(): pass\n"
    )
    (root / "testsuite/expect/test1.1").write_text("expect script\n")


def write_junit(path: Path, cases: list[tuple[str, str]]) -> None:
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", {"name": "pytest"})
    for file_name, status in cases:
        case = ET.SubElement(
            suite,
            "testcase",
            {"file": file_name, "classname": file_name, "name": "test_case"},
        )
        if status == "failed":
            ET.SubElement(case, "failure")
        elif status == "skipped":
            ET.SubElement(case, "skipped", {"type": "pytest.skip"})
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class PatchTests(unittest.TestCase):
    def test_selects_added_and_modified_runnable_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            baseline = root_path / "baseline"
            candidate = root_path / "candidate"
            make_tree(baseline)
            make_tree(candidate)
            (candidate / "testsuite/python/tests/test_100_1.py").write_text(
                "def test_100_1(): assert True\n"
            )
            (candidate / "testsuite/python/expect/test_2_3.py").write_text(
                "def test_2_3(): pass\n"
            )
            result = select(candidate, baseline)
            selected = {
                item["path"]: item["change"] for item in result["selected_files"]
            }
            self.assertEqual(selected["tests/test_100_1.py"], "modified")
            self.assertEqual(selected["expect/test_2_3.py"], "added")

    def test_changed_raw_expect_selects_its_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            baseline = root_path / "baseline"
            candidate = root_path / "candidate"
            make_tree(baseline)
            make_tree(candidate)
            (candidate / "testsuite/expect/test1.1").write_text("changed\n")
            result = select(candidate, baseline)
            selected = result["selected_files"]
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["path"], "expect/test_1_1.py")
            self.assertEqual(selected[0]["change"], "raw-expect-modified")

    def test_rejects_removed_baseline_test(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            baseline = root_path / "baseline"
            candidate = root_path / "candidate"
            make_tree(baseline)
            make_tree(candidate)
            (candidate / "testsuite/python/tests/test_100_1.py").unlink()
            with self.assertRaisesRegex(ValueError, "may not remove"):
                select(candidate, baseline)

    def test_rejects_removed_baseline_support_file(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            baseline = root_path / "baseline"
            candidate = root_path / "candidate"
            make_tree(baseline)
            make_tree(candidate)
            (candidate / "testsuite/python/run-tests-python").unlink()
            with self.assertRaisesRegex(ValueError, "may not remove"):
                select(candidate, baseline)

    def test_validation_requires_every_testcase_to_pass(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            selection = root_path / "selection.json"
            selection.write_text(
                '{"schema":1,"selected_files":[{"path":"tests/test_new.py"}]}'
            )
            passing = root_path / "passing.xml"
            skipped = root_path / "skipped.xml"
            write_junit(passing, [("tests/test_new.py", "passed")])
            write_junit(skipped, [("tests/test_new.py", "skipped")])
            self.assertTrue(validate(selection, passing)["ok"])
            result = validate(selection, skipped)
            self.assertFalse(result["ok"])
            self.assertEqual(result["counts"], {"skipped": 1})

    def test_empty_selection_needs_no_vm_result(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            selection = Path(root) / "selection.json"
            selection.write_text('{"schema":1,"selected_files":[]}')
            self.assertTrue(validate(selection, None)["ok"])


if __name__ == "__main__":
    unittest.main()
