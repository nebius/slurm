#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from release_metadata import release_metadata


VALID_META = """\
  Name:         slurm
  Major:        26
  Minor:        05
  Micro:        3
  Version:      26.05.3
  Release:      nebius-1
  API_CURRENT:  45
"""


class ReleaseMetadataTest(unittest.TestCase):
    def metadata(self, text: str = VALID_META, ref: str = "nebius/26.05") -> dict:
        with tempfile.TemporaryDirectory() as directory:
            meta = Path(directory) / "META"
            meta.write_text(text, encoding="utf-8")
            return release_metadata(meta, ref, "a" * 40)

    def test_derives_downstream_tag_and_two_supported_parsers(self) -> None:
        metadata = self.metadata()
        self.assertEqual(metadata["tag"], "slurm-26-05-3-nebius-1")
        self.assertEqual(metadata["asset_prefix"], "slurm-26.05.3-nebius-1")
        self.assertEqual(metadata["version_string"], "26.05.3-nebius-1")
        self.assertEqual(metadata["api"]["parsers"], ["v0.0.44", "v0.0.45"])
        self.assertFalse(metadata["prerelease"])

    def test_derives_release_candidate_identity(self) -> None:
        metadata = self.metadata(VALID_META.replace("nebius-1", "nebius-1-rc0"))
        self.assertEqual(metadata["tag"], "slurm-26-05-3-nebius-1-rc0")
        self.assertEqual(
            metadata["asset_prefix"], "slurm-26.05.3-nebius-1-rc0"
        )
        self.assertEqual(metadata["version_string"], "26.05.3-nebius-1-rc0")
        self.assertTrue(metadata["prerelease"])

    def test_rejects_non_release_branch(self) -> None:
        with self.assertRaisesRegex(ValueError, "release ref"):
            self.metadata(ref="master")

    def test_rejects_branch_meta_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.metadata(ref="nebius/26.11")

    def test_rejects_upstream_release_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "META Release"):
            self.metadata(VALID_META.replace("nebius-1", "1"))

    def test_rejects_release_candidate_without_number(self) -> None:
        with self.assertRaisesRegex(ValueError, "META Release"):
            self.metadata(VALID_META.replace("nebius-1", "nebius-1-rc"))

    def test_rejects_inconsistent_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "META Version"):
            self.metadata(VALID_META.replace("26.05.3", "26.05.4"))


if __name__ == "__main__":
    unittest.main()
