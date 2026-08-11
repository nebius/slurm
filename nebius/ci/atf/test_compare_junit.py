#!/usr/bin/env python3

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import compare_junit


class CompareJunitTest(unittest.TestCase):
    def report(self, root: Path, name: str, cases: list[tuple[str, str]]) -> Path:
        suites = ET.Element("testsuites")
        suite = ET.SubElement(suites, "testsuite")
        for nodeid, status in cases:
            file_name, test_name = nodeid.split("::", 1)
            case = ET.SubElement(
                suite,
                "testcase",
                {
                    "file": file_name,
                    "classname": file_name.removesuffix(".py").replace("/", "."),
                    "name": test_name,
                },
            )
            if status == "failed":
                ET.SubElement(case, "failure")
            elif status == "error":
                ET.SubElement(case, "error")
            elif status == "skipped":
                ET.SubElement(case, "skipped", {"type": "pytest.skip"})
            elif status == "xfailed":
                ET.SubElement(case, "skipped", {"type": "pytest.xfail"})
        path = root / name
        ET.ElementTree(suites).write(path, encoding="utf-8", xml_declaration=True)
        return path

    def selection(
        self, root: Path, path: str, change: str = "modified"
    ) -> Path:
        selection = root / "selection.json"
        selection.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "policy": "changed-files-on-h200-v1",
                    "selected_files": [{"path": path, "change": change}],
                }
            ),
            encoding="utf-8",
        )
        return selection

    def test_identical_known_failure_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self.report(root, "base.xml", [("tests/a.py::test_a", "failed")])
            candidate = self.report(root, "candidate.xml", [("tests/a.py::test_a", "failed")])
            self.assertTrue(
                compare_junit.compare(
                    compare_junit.load(baseline), compare_junit.load(candidate)
                )["ok"]
            )

    def test_regression_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self.report(root, "base.xml", [("tests/a.py::test_a", "passed")])
            candidate = self.report(root, "candidate.xml", [("tests/a.py::test_a", "failed")])
            result = compare_junit.compare(
                compare_junit.load(baseline), compare_junit.load(candidate)
            )
            self.assertFalse(result["ok"])
            self.assertEqual(len(result["changed"]), 1)

    def test_passing_modified_patch_test_supersedes_frozen_regression(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self.report(
                root, "base.xml", [("tests/test_a.py::test_a", "passed")]
            )
            candidate = self.report(
                root, "candidate.xml", [("tests/test_a.py::test_a", "failed")]
            )
            patch = self.report(
                root, "patch.xml", [("tests/test_a.py::test_a", "passed")]
            )
            patch_files, patch_results = compare_junit.load_patch_context(
                self.selection(root, "tests/test_a.py"), patch
            )
            result = compare_junit.compare(
                compare_junit.load(baseline),
                compare_junit.load(candidate),
                patch_files,
                patch_results,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["regressions"], [])
            self.assertEqual(len(result["superseded_regressions"]), 1)

    def test_modified_patch_file_does_not_hide_unreplaced_regression(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self.report(
                root, "base.xml", [("tests/test_a.py::test_a", "passed")]
            )
            candidate = self.report(
                root, "candidate.xml", [("tests/test_a.py::test_a", "failed")]
            )
            patch = self.report(
                root, "patch.xml", [("tests/test_a.py::test_other", "passed")]
            )
            patch_files, patch_results = compare_junit.load_patch_context(
                self.selection(root, "tests/test_a.py"), patch
            )
            result = compare_junit.compare(
                compare_junit.load(baseline),
                compare_junit.load(candidate),
                patch_files,
                patch_results,
            )
            self.assertFalse(result["ok"])
            self.assertEqual(len(result["regressions"]), 1)
            self.assertEqual(result["superseded_regressions"], [])

    def test_added_patch_file_does_not_supersede_frozen_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self.report(
                root, "base.xml", [("tests/test_a.py::test_a", "passed")]
            )
            candidate = self.report(
                root, "candidate.xml", [("tests/test_a.py::test_a", "failed")]
            )
            patch = self.report(
                root, "patch.xml", [("tests/test_a.py::test_a", "passed")]
            )
            patch_files, patch_results = compare_junit.load_patch_context(
                self.selection(root, "tests/test_a.py", "added"), patch
            )
            result = compare_junit.compare(
                compare_junit.load(baseline),
                compare_junit.load(candidate),
                patch_files,
                patch_results,
            )
            self.assertFalse(result["ok"])
            self.assertEqual(patch_files, set())

    def test_modified_patch_test_requires_junit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "require a patch JUnit"):
                compare_junit.load_patch_context(
                    self.selection(root, "tests/test_a.py"), None
                )

    def test_changed_known_failure_to_passed_is_an_improvement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self.report(
                root, "base.xml", [("tests/a.py::test_a", "failed")]
            )
            candidate = self.report(
                root, "candidate.xml", [("tests/a.py::test_a", "passed")]
            )
            result = compare_junit.compare(
                compare_junit.load(baseline), compare_junit.load(candidate)
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["improvements"][0]["baseline"], "failed")
            self.assertEqual(result["improvements"][0]["candidate"], "passed")

    def test_changed_known_failure_to_skip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self.report(
                root, "base.xml", [("tests/a.py::test_a", "failed")]
            )
            candidate = self.report(
                root, "candidate.xml", [("tests/a.py::test_a", "skipped")]
            )
            result = compare_junit.compare(
                compare_junit.load(baseline), compare_junit.load(candidate)
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["regressions"][0]["candidate"], "skipped")

    def test_missing_test_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self.report(
                root, "base.xml", [("tests/a.py::test_a", "passed")]
            )
            candidate = self.report(
                root, "candidate.xml", [("tests/b.py::test_b", "passed")]
            )
            self.assertFalse(
                compare_junit.compare(
                    compare_junit.load(baseline), compare_junit.load(candidate)
                )["ok"]
            )

    def test_new_test_must_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self.report(
                root, "base.xml", [("tests/a.py::test_a", "passed")]
            )
            passing = self.report(
                root,
                "passing.xml",
                [
                    ("tests/a.py::test_a", "passed"),
                    ("tests/b.py::test_b", "passed"),
                ],
            )
            failing = self.report(
                root,
                "failing.xml",
                [
                    ("tests/a.py::test_a", "passed"),
                    ("tests/b.py::test_b", "skipped"),
                ],
            )
            base = compare_junit.load(baseline)
            self.assertTrue(
                compare_junit.compare(base, compare_junit.load(passing))["ok"]
            )
            self.assertFalse(
                compare_junit.compare(base, compare_junit.load(failing))["ok"]
            )

    def test_duplicate_testcase_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            duplicate = self.report(
                root,
                "duplicate.xml",
                [
                    ("tests/a.py::test_a", "passed"),
                    ("tests/a.py::test_a", "failed"),
                ],
            )
            with self.assertRaisesRegex(ValueError, "duplicate testcase identity"):
                compare_junit.load(duplicate)

    def test_empty_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty = self.report(root, "empty.xml", [])
            with self.assertRaisesRegex(ValueError, "contains no testcases"):
                compare_junit.load(empty)


if __name__ == "__main__":
    unittest.main()
