import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from garmin_fit.build_from_plan import (
    build_all_fits_from_plan,
    build_workout_steps,
    load_plan_build_input,
)


class BuildFromPlanTests(unittest.TestCase):
    def test_load_plan_build_input_repairs_and_validates(self):
        yaml_text = """
workouts:
- filename: " W01 Easy/Run "
  steps:
  - type: distance_pace
    km: "5"
    pace_fast: "5.0"
    pace_slow: "6 00"
"""
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "plan.yaml"
            yaml_path.write_text(yaml_text, encoding="utf-8")

            result = load_plan_build_input(yaml_path)

        workout = result.plan.workouts[0]
        step = workout.steps[0]
        self.assertEqual(workout.filename, "W01_Easy_Run")
        self.assertEqual(workout.name, "W01_Easy_Run")
        self.assertEqual(step.step_type, "dist_pace")
        self.assertEqual(step.km, 5.0)
        self.assertEqual(step.pace_fast, "5:00")
        self.assertEqual(step.pace_slow, "6:00")
        self.assertTrue(any("aligned filename/name" in note for note in result.repairs))

    def test_build_workout_steps_expands_sbu_block(self):
        yaml_text = """
workouts:
- filename: W01_TEST
  name: W01_TEST
  steps:
  - type: dist_open
    km: 2
    intensity: warmup
  - type: sbu_block
"""
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "plan.yaml"
            yaml_path.write_text(yaml_text, encoding="utf-8")

            result = load_plan_build_input(yaml_path)

        steps = build_workout_steps(result.plan.workouts[0])
        self.assertEqual(len(steps), 25)
        self.assertEqual([step.message_index for step in steps], list(range(25)))

    @patch("garmin_fit.build_from_plan.save_workout")
    @patch("garmin_fit.build_from_plan.get_next_serial_timestamp", return_value=[(10, 20), (11, 21)])
    def test_build_all_fits_from_plan_saves_each_workout(self, _serials, save_workout_mock):
        yaml_text = """
workouts:
- filename: W01_A
  name: W01_A
  steps:
  - type: dist_open
    km: 3
- filename: W01_B
  name: W01_B
  steps:
  - type: time_step
    seconds: 300
"""
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "plan.yaml"
            yaml_path.write_text(yaml_text, encoding="utf-8")

            success, total = build_all_fits_from_plan(yaml_path)

        self.assertEqual((success, total), (2, 2))
        self.assertEqual(save_workout_mock.call_count, 2)

    # ── TODO #10: error paths ────────────────────────────────────────────────
    def test_load_plan_build_input_rejects_malformed_yaml_syntax(self):
        yaml_text = "workouts: [unclosed list\n  - filename: W01\n"
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "plan.yaml"
            yaml_path.write_text(yaml_text, encoding="utf-8")

            with self.assertRaises(yaml.YAMLError):
                load_plan_build_input(yaml_path)

    def test_load_plan_build_input_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "plan.yaml"
            yaml_path.write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "empty"):
                load_plan_build_input(yaml_path)

    def test_load_plan_build_input_rejects_no_workouts_key(self):
        # Caught by schema validation ("workouts: Field required") before the
        # domain-level "No workouts found" check is ever reached -- both are
        # ValueError, which is what callers actually need to handle.
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "plan.yaml"
            yaml_path.write_text("some_other_key: 1\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "workouts"):
                load_plan_build_input(yaml_path)

    def test_load_plan_build_input_rejects_empty_workouts_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "plan.yaml"
            yaml_path.write_text("workouts: []\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "workouts"):
                load_plan_build_input(yaml_path)

    def test_load_plan_build_input_rejects_validation_errors(self):
        yaml_text = """
workouts:
- filename: W01_TEST
  name: W01_TEST
  steps:
  - type: dist_hr
    km: 5
    hr_low: 180
    hr_high: 120
"""
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "plan.yaml"
            yaml_path.write_text(yaml_text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "validation failed"):
                load_plan_build_input(yaml_path)

    @patch("garmin_fit.build_from_plan.save_workout", side_effect=OSError("disk full"))
    @patch("garmin_fit.build_from_plan.get_next_serial_timestamp", return_value=[(10, 20), (11, 21)])
    def test_build_all_fits_from_plan_reports_file_write_failure_without_raising(
        self, _serials, _save_workout_mock
    ):
        yaml_text = """
workouts:
- filename: W01_A
  name: W01_A
  steps:
  - type: dist_open
    km: 3
- filename: W01_B
  name: W01_B
  steps:
  - type: time_step
    seconds: 300
"""
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "plan.yaml"
            yaml_path.write_text(yaml_text, encoding="utf-8")

            success, total = build_all_fits_from_plan(yaml_path)

        self.assertEqual((success, total), (0, 2))  # both fail, but no exception propagates


if __name__ == "__main__":
    unittest.main()

