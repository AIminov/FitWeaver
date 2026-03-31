import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import garmin_fit.archive_manager as archive_manager


class ArchiveManagerTests(unittest.TestCase):
    def test_archive_move_plan_handles_plan_done_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_dir = root / "Plan"
            plan_done_dir = plan_dir / "plan_done"
            templates_dir = root / "Workout_templates"
            output_dir = root / "Output_fit"
            archive_dir = root / "Archive"
            artifacts_dir = root / "Build_artifacts"

            plan_done_dir.mkdir(parents=True)
            templates_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            archive_dir.mkdir(parents=True)
            artifacts_dir.mkdir(parents=True)

            plan_file = plan_dir / "sample.yaml"
            plan_file.write_text("workouts: []", encoding="utf-8")

            # Existing file with same name at the plan_done root should not interfere
            # with the archive-specific subdirectory layout.
            (plan_done_dir / "sample.yaml").write_text("old", encoding="utf-8")

            with patch.object(archive_manager, "PLAN_DIR", plan_dir), patch.object(
                archive_manager, "PLAN_DONE_DIR", plan_done_dir
            ), patch.object(archive_manager, "TEMPLATES_DIR", templates_dir), patch.object(
                archive_manager, "OUTPUT_DIR", output_dir
            ), patch.object(
                archive_manager, "ARCHIVE_DIR", archive_dir
            ), patch.object(
                archive_manager, "ARTIFACTS_DIR", artifacts_dir
            ):
                archive_path = archive_manager.archive_current_plan(
                    archive_name="test_archive",
                    keep_plan=False,
                    plan_paths=[plan_file],
                )

            self.assertTrue((plan_done_dir / "sample.yaml").exists())
            self.assertTrue((plan_done_dir / "test_archive" / "sample.yaml").exists())
            self.assertFalse(plan_file.exists())
            self.assertTrue((archive_path / "sample.yaml").exists())

    def test_archive_exports_debug_templates_from_yaml_when_workspace_templates_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_dir = root / "Plan"
            plan_done_dir = plan_dir / "plan_done"
            templates_dir = root / "Workout_templates"
            output_dir = root / "Output_fit"
            archive_dir = root / "Archive"
            artifacts_dir = root / "Build_artifacts"

            plan_done_dir.mkdir(parents=True)
            templates_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            archive_dir.mkdir(parents=True)
            artifacts_dir.mkdir(parents=True)

            plan_file = plan_dir / "sample.yaml"
            plan_file.write_text(
                """
workouts:
- filename: W01_TEST
  name: W01_TEST
  steps:
  - type: dist_open
    km: 5
""".strip(),
                encoding="utf-8",
            )

            with patch.object(archive_manager, "PLAN_DIR", plan_dir), patch.object(
                archive_manager, "PLAN_DONE_DIR", plan_done_dir
            ), patch.object(archive_manager, "TEMPLATES_DIR", templates_dir), patch.object(
                archive_manager, "OUTPUT_DIR", output_dir
            ), patch.object(
                archive_manager, "ARCHIVE_DIR", archive_dir
            ), patch.object(
                archive_manager, "ARTIFACTS_DIR", artifacts_dir
            ):
                archive_path = archive_manager.archive_current_plan(
                    archive_name="test_export_archive",
                    keep_plan=False,
                    plan_paths=[plan_file],
                )

            exported_template = archive_path / "workout_templates" / "W01_TEST.py"
            info_text = (archive_path / "archive_info.txt").read_text(encoding="utf-8")

            self.assertTrue(exported_template.exists())
            self.assertIn("Templates archived: 1", info_text)
            self.assertIn("Templates source: exported_from_yaml", info_text)

    def test_archive_collects_related_build_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_dir = root / "Plan"
            plan_done_dir = plan_dir / "plan_done"
            templates_dir = root / "Workout_templates"
            output_dir = root / "Output_fit"
            archive_dir = root / "Archive"
            artifacts_dir = root / "Build_artifacts"

            plan_done_dir.mkdir(parents=True)
            templates_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            archive_dir.mkdir(parents=True)
            artifacts_dir.mkdir(parents=True)

            plan_file = plan_dir / "sample.yaml"
            plan_file.write_text("workouts: []", encoding="utf-8")
            (artifacts_dir / "sample.repaired.yaml").write_text("workouts: []\n", encoding="utf-8")
            (artifacts_dir / "sample.build_report.json").write_text("{}", encoding="utf-8")

            with patch.object(archive_manager, "PLAN_DIR", plan_dir), patch.object(
                archive_manager, "PLAN_DONE_DIR", plan_done_dir
            ), patch.object(archive_manager, "TEMPLATES_DIR", templates_dir), patch.object(
                archive_manager, "OUTPUT_DIR", output_dir
            ), patch.object(
                archive_manager, "ARCHIVE_DIR", archive_dir
            ), patch.object(
                archive_manager, "ARTIFACTS_DIR", artifacts_dir
            ):
                archive_path = archive_manager.archive_current_plan(
                    archive_name="test_artifacts_archive",
                    keep_plan=False,
                    plan_paths=[plan_file],
                )

            self.assertTrue((archive_path / "artifacts" / "sample.repaired.yaml").exists())
            self.assertTrue((archive_path / "artifacts" / "sample.build_report.json").exists())
            info_text = (archive_path / "archive_info.txt").read_text(encoding="utf-8")
            self.assertIn("Build artifacts archived: 2", info_text)


if __name__ == "__main__":
    unittest.main()

