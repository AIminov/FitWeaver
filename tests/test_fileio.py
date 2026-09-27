import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from garmin_fit.fileio import atomic_write_text, prune_directory


class AtomicWriteTests(unittest.TestCase):
    def test_writes_and_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plan.yaml"
            atomic_write_text(target, "old: 1\n")
            atomic_write_text(target, "new: тренировка\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "new: тренировка\n")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["plan.yaml"])

    def test_failed_write_keeps_the_old_file_and_no_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plan.yaml"
            target.write_text("old: 1\n", encoding="utf-8")
            with patch("os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "new: 2\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "old: 1\n")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["plan.yaml"])


class PruneTests(unittest.TestCase):
    def test_keeps_newest_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(5):
                path = Path(tmp) / f"{index}.json"
                path.write_text("{}", encoding="utf-8")
                os.utime(path, (1000 + index, 1000 + index))
            (Path(tmp) / "keep.txt").write_text("x", encoding="utf-8")
            self.assertEqual(prune_directory(tmp, "*.json", keep=2), 3)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["3.json", "4.json", "keep.txt"])


if __name__ == "__main__":
    unittest.main()
