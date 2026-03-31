"""Tests for Pydantic plan schema models (src/garmin_fit/plan_schema.py)."""

import unittest

from pydantic import ValidationError

from garmin_fit.plan_schema import (
    DistHrStep,
    DistPaceStep,
    DrillSchema,
    RepeatStep,
    SbuBlockStep,
    TimeHrStep,
    TimePaceStep,
    WorkoutPlanSchema,
    WorkoutSchema,
    WorkoutStepUnion,
)


class TestDrillSchema(unittest.TestCase):
    def test_valid_drill(self):
        d = DrillSchema(name="High Knees", seconds=30, reps=2)
        self.assertEqual(d.name, "High Knees")
        self.assertEqual(d.seconds, 30)

    def test_empty_name_raises(self):
        with self.assertRaises(ValidationError):
            DrillSchema(name="  ", seconds=30, reps=2)

    def test_zero_seconds_raises(self):
        with self.assertRaises(ValidationError):
            DrillSchema(name="High Knees", seconds=0, reps=2)

    def test_zero_reps_raises(self):
        with self.assertRaises(ValidationError):
            DrillSchema(name="High Knees", seconds=30, reps=0)

    def test_extra_fields_preserved(self):
        d = DrillSchema(name="High Knees", seconds=30, reps=2, custom_field="x")
        self.assertEqual(d.model_extra["custom_field"], "x")


class TestDistHrStep(unittest.TestCase):
    def _valid(self):
        return {"type": "dist_hr", "km": 5.0, "hr_low": 140, "hr_high": 155}

    def test_valid_step(self):
        s = DistHrStep(**self._valid())
        self.assertEqual(s.km, 5.0)

    def test_hr_low_equals_hr_high_raises(self):
        data = {**self._valid(), "hr_low": 155, "hr_high": 155}
        with self.assertRaises(ValidationError):
            DistHrStep(**data)

    def test_hr_low_greater_than_hr_high_raises(self):
        data = {**self._valid(), "hr_low": 160, "hr_high": 155}
        with self.assertRaises(ValidationError):
            DistHrStep(**data)

    def test_zero_km_raises(self):
        data = {**self._valid(), "km": 0}
        with self.assertRaises(ValidationError):
            DistHrStep(**data)

    def test_negative_km_raises(self):
        data = {**self._valid(), "km": -1.0}
        with self.assertRaises(ValidationError):
            DistHrStep(**data)


class TestTimeHrStep(unittest.TestCase):
    def test_valid(self):
        s = TimeHrStep(type="time_hr", seconds=300, hr_low=160, hr_high=175)
        self.assertEqual(s.seconds, 300)

    def test_hr_ordering_raises(self):
        with self.assertRaises(ValidationError):
            TimeHrStep(type="time_hr", seconds=300, hr_low=175, hr_high=160)


class TestDistPaceStep(unittest.TestCase):
    def test_valid(self):
        s = DistPaceStep(
            type="dist_pace", km=1.0, pace_fast="4:20", pace_slow="4:30"
        )
        self.assertEqual(s.pace_fast, "4:20")

    def test_invalid_pace_format_raises(self):
        with self.assertRaises(ValidationError):
            DistPaceStep(type="dist_pace", km=1.0, pace_fast="430", pace_slow="4:30")

    def test_pace_ordering_raises(self):
        with self.assertRaises(ValidationError):
            DistPaceStep(
                type="dist_pace", km=1.0, pace_fast="4:30", pace_slow="4:20"
            )

    def test_equal_paces_raise(self):
        with self.assertRaises(ValidationError):
            DistPaceStep(
                type="dist_pace", km=1.0, pace_fast="4:30", pace_slow="4:30"
            )

    def test_pace_constant_skips_ordering_check(self):
        # Constants are not comparable by seconds — should not raise
        s = DistPaceStep(
            type="dist_pace", km=1.0, pace_fast="EASY_F", pace_slow="EASY_S"
        )
        self.assertEqual(s.pace_fast, "EASY_F")


class TestTimePaceStep(unittest.TestCase):
    def test_valid(self):
        s = TimePaceStep(
            type="time_pace", seconds=120, pace_fast="4:20", pace_slow="4:30"
        )
        self.assertEqual(s.seconds, 120)

    def test_zero_seconds_raises(self):
        with self.assertRaises(ValidationError):
            TimePaceStep(
                type="time_pace", seconds=0, pace_fast="4:20", pace_slow="4:30"
            )


class TestRepeatStep(unittest.TestCase):
    def test_valid(self):
        s = RepeatStep(type="repeat", back_to_offset=1, count=5)
        self.assertEqual(s.count, 5)

    def test_negative_offset_raises(self):
        with self.assertRaises(ValidationError):
            RepeatStep(type="repeat", back_to_offset=-1, count=5)

    def test_zero_count_raises(self):
        with self.assertRaises(ValidationError):
            RepeatStep(type="repeat", back_to_offset=0, count=0)


class TestSbuBlockStep(unittest.TestCase):
    def test_valid_no_drills(self):
        s = SbuBlockStep(type="sbu_block")
        self.assertIsNone(s.drills)

    def test_valid_with_drills(self):
        s = SbuBlockStep(
            type="sbu_block",
            drills=[{"name": "High Knees", "seconds": 30, "reps": 2}],
        )
        self.assertEqual(len(s.drills), 1)

    def test_empty_drills_list_raises(self):
        with self.assertRaises(ValidationError):
            SbuBlockStep(type="sbu_block", drills=[])


class TestDiscriminatedUnion(unittest.TestCase):
    def test_correct_type_dispatches(self):
        from pydantic import TypeAdapter

        adapter = TypeAdapter(WorkoutStepUnion)
        step = adapter.validate_python(
            {"type": "dist_hr", "km": 5.0, "hr_low": 140, "hr_high": 155}
        )
        self.assertIsInstance(step, DistHrStep)

    def test_unknown_type_raises(self):
        from pydantic import TypeAdapter

        adapter = TypeAdapter(WorkoutStepUnion)
        with self.assertRaises(ValidationError):
            adapter.validate_python({"type": "bogus_type", "km": 5.0})


class TestWorkoutSchema(unittest.TestCase):
    def _valid_workout(self):
        return {
            "filename": "W01_Easy_5km",
            "name": "W01_Easy_5km",
            "steps": [
                {"type": "dist_hr", "km": 5.0, "hr_low": 130, "hr_high": 145}
            ],
        }

    def test_valid_workout(self):
        w = WorkoutSchema(**self._valid_workout())
        self.assertEqual(w.filename, "W01_Easy_5km")

    def test_empty_filename_raises(self):
        data = {**self._valid_workout(), "filename": "  "}
        with self.assertRaises(ValidationError):
            WorkoutSchema(**data)

    def test_empty_steps_raises(self):
        data = {**self._valid_workout(), "steps": []}
        with self.assertRaises(ValidationError):
            WorkoutSchema(**data)


class TestWorkoutPlanSchema(unittest.TestCase):
    def _valid_plan(self):
        return {
            "workouts": [
                {
                    "filename": "W01_Easy_5km",
                    "name": "W01_Easy_5km",
                    "steps": [
                        {"type": "dist_hr", "km": 5.0, "hr_low": 130, "hr_high": 145}
                    ],
                },
                {
                    "filename": "W01_Intervals",
                    "name": "W01_Intervals",
                    "steps": [
                        {"type": "time_hr", "seconds": 300, "hr_low": 160, "hr_high": 175}
                    ],
                },
            ]
        }

    def test_valid_plan(self):
        plan = WorkoutPlanSchema(**self._valid_plan())
        self.assertEqual(len(plan.workouts), 2)

    def test_empty_workouts_raises(self):
        with self.assertRaises(ValidationError):
            WorkoutPlanSchema(workouts=[])

    def test_duplicate_filenames_raise(self):
        data = self._valid_plan()
        data["workouts"][1]["filename"] = "W01_Easy_5km"
        data["workouts"][1]["name"] = "W01_Easy_5km"
        with self.assertRaises(ValidationError):
            WorkoutPlanSchema(**data)

    def test_json_schema_is_generated(self):
        schema = WorkoutPlanSchema.model_json_schema()
        self.assertIn("workouts", schema.get("properties", {}))

    def test_json_schema_contains_step_types(self):
        schema = WorkoutPlanSchema.model_json_schema()
        schema_str = str(schema)
        for step_type in ("dist_hr", "time_hr", "dist_pace", "repeat", "sbu_block"):
            self.assertIn(step_type, schema_str)


class TestPydanticIntegrationWithValidator(unittest.TestCase):
    """Verify Pydantic issues appear in validate_plan_data_detailed output."""

    def test_invalid_step_type_reported(self):
        from garmin_fit.plan_validator import validate_plan_data_detailed

        data = {
            "workouts": [
                {
                    "filename": "W01",
                    "name": "W01",
                    "steps": [{"type": "bogus_type", "km": 5.0}],
                }
            ]
        }
        errors, _ = validate_plan_data_detailed(data)
        self.assertTrue(len(errors) > 0)

    def test_missing_required_field_reported(self):
        from garmin_fit.plan_validator import validate_plan_data_detailed

        data = {
            "workouts": [
                {
                    "filename": "W01",
                    "name": "W01",
                    "steps": [{"type": "dist_hr", "km": 5.0}],  # missing hr_low, hr_high
                }
            ]
        }
        errors, _ = validate_plan_data_detailed(data)
        self.assertTrue(len(errors) > 0)

    def test_valid_plan_no_errors(self):
        from garmin_fit.plan_validator import validate_plan_data_detailed

        data = {
            "workouts": [
                {
                    "filename": "W01_Easy",
                    "name": "W01_Easy",
                    "steps": [
                        {"type": "dist_hr", "km": 5.0, "hr_low": 130, "hr_high": 145}
                    ],
                }
            ]
        }
        errors, warnings = validate_plan_data_detailed(data)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
