import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import garmin_fit.orchestrator as orch
import garmin_fit.plan_artifacts as plan_artifacts


class OrchestratorTests(unittest.TestCase):
    def test_select_active_yaml_uses_latest_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            older = plan_dir / "a.yaml"
            newer = plan_dir / "b.yaml"
            older.write_text("workouts: []", encoding="utf-8")
            newer.write_text("workouts: []", encoding="utf-8")
            base = time.time()
            os.utime(older, (base - 10, base - 10))
            os.utime(newer, (base, base))

            with patch.object(orch, "PLAN_DIR", plan_dir):
                selected = orch.select_active_yaml(prefer_latest=True)
                self.assertEqual(selected.name, "b.yaml")

    @patch("garmin_fit.orchestrator.archive_current_plan")
    @patch("garmin_fit.orchestrator.validate_directory", return_value=(2, 2))
    @patch("garmin_fit.orchestrator.build_all_fits_from_plan", return_value=(2, 2))
    def test_run_generation_pipeline_success_archives(
        self, _build, _validate, archive_mock
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            yaml_path = root / "plan.yaml"
            out_dir = root / "out"
            artifacts_dir = root / "artifacts"
            out_dir.mkdir()
            artifacts_dir.mkdir()
            (out_dir / "w1.fit").write_bytes(b"fit")
            (out_dir / "w2.fit").write_bytes(b"fit")
            yaml_path.write_text("workouts: []", encoding="utf-8")
            archive_mock.return_value = root / "archive_ok"

            with patch.object(orch, "OUTPUT_DIR", out_dir), patch.object(
                plan_artifacts, "ARTIFACTS_DIR", artifacts_dir
            ):
                result = orch.run_generation_pipeline(
                    yaml_path,
                    cleanup_first=False,
                    auto_archive=True,
                )

            self.assertTrue(result["success"])
            self.assertEqual(result["build_mode"], "direct")
            self.assertEqual(result["template_export_count"], 0)
            self.assertEqual(result["template_export_total_count"], 0)
            self.assertNotIn("templates_count", result)
            self.assertNotIn("templates_total_count", result)
            self.assertEqual(len(result["fit_files"]), 2)
            self.assertTrue(result["build_report_path"].exists())
            self.assertTrue(result["repaired_yaml_path"].exists())
            archive_mock.assert_called_once()

    @patch("garmin_fit.orchestrator.archive_current_plan")
    @patch("garmin_fit.orchestrator.validate_directory", return_value=(1, 2))
    @patch("garmin_fit.orchestrator.build_all_fits_from_plan", return_value=(2, 2))
    def test_run_generation_pipeline_failure_skips_archive(
        self, _build, _validate, archive_mock
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            yaml_path = root / "plan.yaml"
            out_dir = root / "out"
            artifacts_dir = root / "artifacts"
            out_dir.mkdir()
            artifacts_dir.mkdir()
            (out_dir / "w1.fit").write_bytes(b"fit")
            yaml_path.write_text("workouts: []", encoding="utf-8")

            with patch.object(orch, "OUTPUT_DIR", out_dir), patch.object(
                plan_artifacts, "ARTIFACTS_DIR", artifacts_dir
            ):
                result = orch.run_generation_pipeline(
                    yaml_path,
                    cleanup_first=False,
                    auto_archive=True,
                )

            self.assertFalse(result["success"])
            archive_mock.assert_not_called()
            self.assertTrue(any("Validation failed" in e for e in result["errors"]))

    @patch("garmin_fit.orchestrator.archive_current_plan")
    @patch("garmin_fit.orchestrator.validate_directory", return_value=(1, 1))
    @patch("garmin_fit.orchestrator.build_all_fits_from_plan", return_value=(1, 2))
    def test_run_generation_pipeline_fails_on_partial_direct_build(
        self, _build, _validate, archive_mock
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            yaml_path = root / "plan.yaml"
            out_dir = root / "out"
            artifacts_dir = root / "artifacts"
            out_dir.mkdir()
            artifacts_dir.mkdir()
            (out_dir / "w1.fit").write_bytes(b"fit")
            yaml_path.write_text("workouts: []", encoding="utf-8")

            with patch.object(orch, "OUTPUT_DIR", out_dir), patch.object(
                plan_artifacts, "ARTIFACTS_DIR", artifacts_dir
            ):
                result = orch.run_generation_pipeline(
                    yaml_path,
                    cleanup_first=False,
                    auto_archive=True,
                )

            self.assertFalse(result["success"])
            archive_mock.assert_not_called()
            self.assertTrue(any("Direct build incomplete" in e for e in result["errors"]))

    @patch("garmin_fit.orchestrator.archive_current_plan")
    @patch("garmin_fit.orchestrator.validate_directory", return_value=(1, 1))
    @patch("garmin_fit.orchestrator.build_all_fits", return_value=(1, 1))
    @patch("garmin_fit.orchestrator.generate_all_templates", return_value=(1, 2))
    def test_run_generation_pipeline_fails_on_partial_template_generation(
        self, _gen, _build, _validate, archive_mock
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            yaml_path = root / "plan.yaml"
            out_dir = root / "out"
            artifacts_dir = root / "artifacts"
            out_dir.mkdir()
            artifacts_dir.mkdir()
            (out_dir / "w1.fit").write_bytes(b"fit")
            yaml_path.write_text("workouts: []", encoding="utf-8")

            with patch.object(orch, "OUTPUT_DIR", out_dir), patch.object(
                plan_artifacts, "ARTIFACTS_DIR", artifacts_dir
            ):
                result = orch.run_generation_pipeline(
                    yaml_path,
                    cleanup_first=False,
                    auto_archive=True,
                    build_mode="templates",
                )

            self.assertFalse(result["success"])
            archive_mock.assert_not_called()
            self.assertTrue(any("Debug template export incomplete" in e for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()

