import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import garmin_fit.runtime_layout as runtime_layout


class RuntimeLayoutTests(unittest.TestCase):
    def test_init_runtime_root_creates_mutable_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            created = runtime_layout.init_runtime_root(runtime_root)

            self.assertTrue(runtime_root.exists())
            self.assertEqual(len(created), len(runtime_layout.MUTABLE_DIRECTORIES))
            for name in runtime_layout.MUTABLE_DIRECTORIES:
                self.assertTrue((runtime_root / name).is_dir())

    def test_copy_runtime_data_copies_known_mutable_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            runtime_root = Path(tmp) / "runtime"
            (project_root / "Plan").mkdir(parents=True)
            (project_root / "Output_fit").mkdir(parents=True)
            (project_root / "Plan" / "plan.yaml").write_text("workouts: []", encoding="utf-8")
            (project_root / "Output_fit" / "a.fit").write_text("fit", encoding="utf-8")
            (project_root / "state.json").write_text("{}", encoding="utf-8")

            with patch.object(runtime_layout, "PROJECT_ROOT", project_root):
                summary = runtime_layout.copy_runtime_data(runtime_root)

            self.assertGreaterEqual(summary["copied"], 3)
            self.assertEqual(summary["skipped"], 0)
            self.assertTrue((runtime_root / "Plan" / "plan.yaml").exists())
            self.assertTrue((runtime_root / "Output_fit" / "a.fit").exists())
            self.assertTrue((runtime_root / "state.json").exists())

