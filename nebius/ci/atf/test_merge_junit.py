#!/usr/bin/env python3

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import compare_junit
import merge_junit


class MergeJunitTest(unittest.TestCase):
    def report(
        self, root: Path, name: str, cases: list[tuple[str, str, str]]
    ) -> Path:
        suites = ET.Element("testsuites")
        suite = ET.SubElement(suites, "testsuite", {"name": "pytest"})
        for nodeid, status, duration in cases:
            file_name, test_name = nodeid.split("::", 1)
            case = ET.SubElement(
                suite,
                "testcase",
                {
                    "file": file_name,
                    "classname": file_name.removesuffix(".py").replace("/", "."),
                    "name": test_name,
                    "time": duration,
                },
            )
            if status == "failed":
                ET.SubElement(case, "failure")
            elif status == "error":
                ET.SubElement(case, "error")
            elif status == "skipped":
                ET.SubElement(case, "skipped", {"type": "pytest.skip"})
        path = root / name
        ET.ElementTree(suites).write(path, encoding="utf-8", xml_declaration=True)
        return path

    def test_merges_reports_and_recomputes_totals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expect = self.report(
                root,
                "expect.xml",
                [("expect/test_1_1.py::test_1_1", "passed", "1.25")],
            )
            python = self.report(
                root,
                "python.xml",
                [
                    ("tests/test_1_1.py::test_one", "failed", "2.0"),
                    ("tests/test_1_2.py::test_two", "skipped", "0.25"),
                ],
            )
            output = root / "junit.xml"
            merge_junit.merge(expect, python, output)

            merged = ET.parse(output).getroot()
            self.assertEqual(merged.get("tests"), "3")
            self.assertEqual(merged.get("failures"), "1")
            self.assertEqual(merged.get("errors"), "0")
            self.assertEqual(merged.get("skipped"), "1")
            self.assertEqual(merged.get("time"), "3.500000")
            self.assertEqual(
                [suite.get("name") for suite in merged.findall("testsuite")],
                ["expect/pytest", "python/pytest"],
            )
            self.assertEqual(len(compare_junit.load(output)), 3)

    def test_rejects_duplicate_testcase_across_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = [("tests/test_a.py::test_a", "passed", "0")]
            expect = self.report(root, "expect.xml", case)
            python = self.report(root, "python.xml", case)
            with self.assertRaisesRegex(ValueError, "duplicate testcase"):
                merge_junit.merge(expect, python, root / "junit.xml")

    def test_rejects_empty_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty = self.report(root, "empty.xml", [])
            valid = self.report(
                root,
                "valid.xml",
                [("tests/test_a.py::test_a", "passed", "0")],
            )
            with self.assertRaisesRegex(ValueError, "contains no testcases"):
                merge_junit.merge(empty, valid, root / "junit.xml")


if __name__ == "__main__":
    unittest.main()
