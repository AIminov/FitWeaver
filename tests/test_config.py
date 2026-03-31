import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ConfigTests(unittest.TestCase):
    def test_runtime_root_defaults_to_project_root(self):
        import Scripts.config as config

        with patch.dict(os.environ, {}, clear=False):
            importlib.reload(config)
            self.assertEqual(config.RUNTIME_ROOT, config.PROJECT_ROOT)
            self.assertEqual(config.PLAN_DIR, config.PROJECT_ROOT / "Plan")

        importlib.reload(config)

    def test_runtime_root_can_be_overridden_via_env(self):
        import Scripts.config as config

        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "custom-runtime"

            with patch.dict(os.environ, {"GARMIN_FIT_RUNTIME_DIR": str(runtime_root)}, clear=False):
                importlib.reload(config)
                self.assertEqual(config.RUNTIME_ROOT, runtime_root.resolve())
                self.assertEqual(config.PLAN_DIR, runtime_root.resolve() / "Plan")
                self.assertEqual(config.OUTPUT_DIR, runtime_root.resolve() / "Output_fit")
                self.assertEqual(config.ARCHIVE_DIR, runtime_root.resolve() / "Archive")
                self.assertEqual(config.STATE_FILE, runtime_root.resolve() / "state.json")

        importlib.reload(config)
