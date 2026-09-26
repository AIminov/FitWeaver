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



class NestedRepeatBuildTests(unittest.TestCase):
    """Sets-of-intervals ("3 sets of 4x400m") build into nested FIT repeats.

    The Garmin Calendar mapper has its own nesting tests; these cover the FIT
    path, where a repeat is a step whose duration_value is the FIT index to jump
    back to. The sbu_block case matters most: sbu_block is the one step type that
    expands into several FIT steps, so every back_to_offset after it has to be
    translated through build_yaml_to_fit_index -- and both the inner and the
    outer repeat of a nested pair need that same translation.
    """

    @staticmethod
    def _steps(yaml_text):
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "plan.yaml"
            yaml_path.write_text(yaml_text, encoding="utf-8")
            # load_plan_build_input raises if the plan does not validate,
            # so reaching build_workout_steps already proves the validator
            # accepts these nested repeats.
            result = load_plan_build_input(yaml_path)
        return build_workout_steps(result.plan.workouts[0])

    def test_nested_repeat_without_expansion_keeps_yaml_indices(self):
        # 0 warmup, 1 fast, 2 rest, 3 repeat(x4), 4 set rest, 5 repeat(x3)
        steps = self._steps("""
workouts:
- filename: W01_SETS
  name: W01_SETS
  steps:
  - type: dist_open
    km: 2
    intensity: warmup
  - type: dist_pace
    km: 0.4
    pace_fast: "3:40"
    pace_slow: "3:50"
  - type: time_step
    seconds: 60
  - type: repeat
    back_to_offset: 1
    count: 4
  - type: time_step
    seconds: 300
  - type: repeat
    back_to_offset: 1
    count: 3
""")
        self.assertEqual(len(steps), 6)
        inner, outer = steps[3], steps[5]
        # Both jump back to the same first step of the repeating group; the
        # outer one spans the inner, which is what makes it a set.
        self.assertEqual(inner.duration_value, 1)
        self.assertEqual(inner.target_value, 4)
        self.assertEqual(outer.duration_value, 1)
        self.assertEqual(outer.target_value, 3)

    def test_nested_repeat_after_sbu_block_translates_both_anchors(self):
        # YAML 0 warmup -> FIT 0
        # YAML 1 sbu_block (2 drills x 2 reps) -> FIT 1..8
        # YAML 2 fast -> FIT 9, YAML 3 rest -> FIT 10
        # YAML 4 inner repeat -> FIT 11, YAML 5 set rest -> FIT 12
        # YAML 6 outer repeat -> FIT 13
        steps = self._steps("""
workouts:
- filename: W01_SBU_SETS
  name: W01_SBU_SETS
  steps:
  - type: dist_open
    km: 2
    intensity: warmup
  - type: sbu_block
    drills:
    - name: Захлёст
      seconds: 30
      reps: 2
    - name: Колени
      seconds: 30
      reps: 2
  - type: dist_pace
    km: 0.4
    pace_fast: "3:40"
    pace_slow: "3:50"
  - type: time_step
    seconds: 60
  - type: repeat
    back_to_offset: 2
    count: 4
  - type: time_step
    seconds: 300
  - type: repeat
    back_to_offset: 2
    count: 3
""")
        self.assertEqual([s.message_index for s in steps], list(range(14)))

        inner, outer = steps[11], steps[13]
        # YAML index 2 sits at FIT index 9 once the sbu_block has expanded.
        # An untranslated anchor would leave 2 here and restart the workout
        # inside the drill block instead of at the 400m rep.
        self.assertEqual(inner.duration_value, 9)
        self.assertEqual(inner.target_value, 4)
        self.assertEqual(outer.duration_value, 9)
        self.assertEqual(outer.target_value, 3)
