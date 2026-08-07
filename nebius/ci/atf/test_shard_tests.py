import tempfile
import unittest
from pathlib import Path

from shard_tests import GPU_REQUIRED, build_manifest


def make_tree(root: Path) -> Path:
    test_root = root / "testsuite" / "python"
    for phase in ("expect", "tests"):
        directory = test_root / phase
        directory.mkdir(parents=True)
        for index in range(24):
            (directory / f"test_{index}.py").write_text(
                "def test_ok(): pass\n", encoding="utf-8"
            )
    for path in GPU_REQUIRED:
        target = test_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_gpu(): pass\n", encoding="utf-8")
    return test_root


class ShardTests(unittest.TestCase):
    def test_partition_is_complete_and_disjoint(self) -> None:
        for phase in ("expect", "python"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as root:
                test_root = make_tree(Path(root))
                manifests = [
                    build_manifest(
                        test_root,
                        phase,
                        "gpu" if index == 4 else f"cpu-{index}",
                        index,
                        5,
                        "h200" if index == 4 else "generic",
                    )
                    for index in range(5)
                ]
                assignments = manifests[0]["assignments"]
                self.assertTrue(
                    all(
                        manifest["assignments"] == assignments
                        for manifest in manifests
                    )
                )
                selected = [
                    path
                    for manifest in manifests
                    for path in manifest["selected_files"]
                ]
                self.assertEqual(sorted(selected), sorted(assignments))
                self.assertEqual(len(selected), len(set(selected)))

    def test_gpu_integrations_are_forced_to_h200(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            test_root = make_tree(Path(root))
            gpu = build_manifest(test_root, "expect", "gpu", 4, 5, "h200")
            cpu = build_manifest(test_root, "expect", "cpu-0", 0, 5, "generic")
            self.assertLessEqual(GPU_REQUIRED, set(gpu["selected_files"]))
            self.assertTrue(GPU_REQUIRED.isdisjoint(cpu["selected_files"]))

    def test_rejects_non_h200_last_shard(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            test_root = make_tree(Path(root))
            with self.assertRaisesRegex(ValueError, "last shard"):
                build_manifest(test_root, "expect", "gpu", 4, 5, "generic")


if __name__ == "__main__":
    unittest.main()
