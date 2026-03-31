import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import Scripts.build_from_plan as build_from_plan
import Scripts.check_fit as check_fit
import Scripts.orchestrator as orch
import Scripts.plan_artifacts as plan_artifacts
import Scripts.state_manager as state_manager


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class DirectPipelineE2ETests(unittest.TestCase):
    def _run_fixture_pipeline(self, fixture_name):
        fixture_path = FIXTURES_DIR / fixture_name

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "Output_fit"
            templates_dir = root / "Workout_templates"
            artifacts_dir = root / "Build_artifacts"
            state_file = root / "state.json"
            lock_file = root / "state.lock"
            output_dir.mkdir()
            templates_dir.mkdir()
            artifacts_dir.mkdir()

            original_build_fit = build_from_plan.build_fit_from_workout

            def _build_fit_to_temp(workout, serial_number, timestamp):
                return original_build_fit(
                    workout,
                    serial_number,
                    timestamp,
                    output_dir=output_dir,
                )

            with patch.object(orch, "OUTPUT_DIR", output_dir), patch.object(
                orch, "TEMPLATES_DIR", templates_dir
            ), patch.object(
                build_from_plan,
                "OUTPUT_DIR",
                output_dir,
            ), patch.object(
                plan_artifacts,
                "ARTIFACTS_DIR",
                artifacts_dir,
            ), patch.object(
                build_from_plan,
                "build_fit_from_workout",
                new=_build_fit_to_temp,
            ), patch.object(
                state_manager, "STATE_FILE", state_file
            ), patch.object(
                state_manager, "LOCK_FILE", lock_file
            ):
                result = orch.run_generation_pipeline(
                    fixture_path,
                    cleanup_first=True,
                    auto_archive=False,
                )

            fit_results = {
                fit_path.name: check_fit.validate_fit_file(fit_path, strict=False)
                for fit_path in sorted(output_dir.glob("*.fit"))
            }
            state_data = json.loads(state_file.read_text(encoding="utf-8"))
            report_data = json.loads(result["build_report_path"].read_text(encoding="utf-8"))
            repaired_yaml_text = result["repaired_yaml_path"].read_text(encoding="utf-8")

        return fixture_path, result, fit_results, state_data, report_data, repaired_yaml_text

    def test_run_generation_pipeline_builds_and_validates_fixture_plan(self):
        _fixture_path, result, fit_results, state_data, report_data, repaired_yaml_text = self._run_fixture_pipeline(
            "direct_pipeline_basic.yaml"
        )

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(result["build_mode"], "direct")
        self.assertEqual(result["template_export_count"], 0)
        self.assertEqual(result["built_count"], 2)
        self.assertEqual(result["build_total_count"], 2)
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(
            [path.name for path in result["fit_files"]],
            ["W01_EASY_BASE.fit", "W01_INTERVAL_BLOCK.fit"],
        )

        interval_results = fit_results["W01_INTERVAL_BLOCK.fit"]
        self.assertTrue(interval_results["valid"], interval_results["errors"])
        workout_name = (
            interval_results["workout"].get("wkt_name")
            or interval_results["workout"].get("workout_name")
        )
        self.assertEqual(workout_name, "W01_INTERVAL_BLOCK")
        self.assertEqual(interval_results["workout"].get("num_valid_steps"), 5)
        self.assertEqual(len(interval_results["steps"]), 5)
        self.assertEqual(state_data["generated_count"], 2)
        self.assertEqual(report_data["build"]["built_count"], 2)
        self.assertEqual(report_data["validation"]["valid_count"], 2)
        self.assertEqual(report_data["archive_path"], None)
        self.assertIn("W01_EASY_BASE", repaired_yaml_text)

    def test_run_generation_pipeline_expands_custom_sbu_fixture(self):
        fixture_path, result, fit_results, state_data, report_data, repaired_yaml_text = self._run_fixture_pipeline(
            "direct_pipeline_sbu_custom.yaml"
        )

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(result["built_count"], 1)
        self.assertEqual(result["valid_count"], 1)
        self.assertEqual([path.name for path in result["fit_files"]], ["W02_SBU_CUSTOM.fit"])

        sbu_results = fit_results["W02_SBU_CUSTOM.fit"]
        self.assertTrue(sbu_results["valid"], sbu_results["errors"])
        self.assertEqual(sbu_results["workout"].get("num_valid_steps"), 8)
        self.assertEqual(len(sbu_results["steps"]), 8)

        plan_input = build_from_plan.load_plan_build_input(fixture_path)
        expanded_steps = build_from_plan.build_workout_steps(plan_input.plan.workouts[0])
        self.assertEqual(len(expanded_steps), 8)
        step_names = [getattr(step, "wkt_step_name", None) for step in expanded_steps]
        self.assertIn("Bounds 1/2", step_names)
        self.assertIn("Ankling 1/1", step_names)
        self.assertEqual(state_data["generated_count"], 1)
        self.assertEqual(report_data["planned_workouts"], 1)
        self.assertIn("Ankling", repaired_yaml_text)

    def test_run_generation_pipeline_builds_hr_fixture_with_expected_targets(self):
        _fixture_path, result, fit_results, state_data, report_data, repaired_yaml_text = self._run_fixture_pipeline(
            "direct_pipeline_hr_blocks.yaml"
        )

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(result["built_count"], 1)
        self.assertEqual(result["valid_count"], 1)
        self.assertEqual([path.name for path in result["fit_files"]], ["W03_HR_BLOCK.fit"])

        hr_results = fit_results["W03_HR_BLOCK.fit"]
        self.assertTrue(hr_results["valid"], hr_results["errors"])
        self.assertEqual(hr_results["workout"].get("num_valid_steps"), 4)
        self.assertEqual(len(hr_results["steps"]), 4)
        self.assertEqual(hr_results["steps"][1].get("custom_target_value_low"), 240)
        self.assertEqual(hr_results["steps"][1].get("custom_target_value_high"), 252)
        self.assertEqual(hr_results["steps"][2].get("custom_target_value_low"), 255)
        self.assertEqual(hr_results["steps"][2].get("custom_target_value_high"), 268)
        self.assertEqual(state_data["generated_count"], 1)
        self.assertEqual(report_data["template_exports"]["generated_count"], 0)
        self.assertIn("hr_low: 155", repaired_yaml_text)


if __name__ == "__main__":
    unittest.main()
