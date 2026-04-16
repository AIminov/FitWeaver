"""
Tests for garmin_step_mapper.py

Covers:
- All 9 step types: dist_hr, time_hr, dist_pace, time_pace, dist_open,
  time_step, open_step, sbu_block, repeat
- map_steps() repeat-body consumption
- map_workout() full payload shape
- extract_date_from_filename() with and without year override
- _pace_to_mps() helper
"""

import datetime
import unittest
from unittest.mock import patch

from garmin_fit.garmin_step_mapper import (
    END_COND_DISTANCE,
    END_COND_ITERATIONS,
    END_COND_LAP_BUTTON,
    END_COND_TIME,
    SPORT_TYPE_RUNNING,
    TARGET_HR,
    TARGET_NO,
    TARGET_SPD,
    _pace_to_mps,
    extract_date_from_filename,
    map_steps,
    map_workout,
)
from garmin_fit.plan_domain import Drill, Workout, WorkoutStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step(**kwargs) -> WorkoutStep:
    """Create a WorkoutStep with only the supplied fields set."""
    defaults = dict(
        step_type=None, intensity=None, km=None, seconds=None,
        pace_fast=None, pace_slow=None, hr_low=None, hr_high=None,
        back_to_offset=None, count=None, drills=None, extra={},
    )
    defaults.update(kwargs)
    return WorkoutStep(**defaults)


def _workout(steps: list[WorkoutStep], **kwargs) -> Workout:
    return Workout(
        filename=kwargs.get("filename", "W01_01-01_Test"),
        name=kwargs.get("name", "Test Workout"),
        desc=kwargs.get("desc", ""),
        estimated_duration_min=kwargs.get("estimated_duration_min", 60),
        steps=steps,
    )


# ---------------------------------------------------------------------------
# _pace_to_mps
# ---------------------------------------------------------------------------

class TestEndConditionIds(unittest.TestCase):
    """Guard against swapped conditionTypeId values (real-world regression)."""

    def test_distance_is_3(self):
        self.assertEqual(END_COND_DISTANCE["conditionTypeId"], 3)

    def test_time_is_2(self):
        self.assertEqual(END_COND_TIME["conditionTypeId"], 2)

    def test_iterations_is_7(self):
        self.assertEqual(END_COND_ITERATIONS["conditionTypeId"], 7)

    def test_lap_button_is_1(self):
        self.assertEqual(END_COND_LAP_BUTTON["conditionTypeId"], 1)

    def test_distance_key(self):
        self.assertEqual(END_COND_DISTANCE["conditionTypeKey"], "distance")

    def test_distance_is_not_lap_button(self):
        self.assertNotEqual(END_COND_DISTANCE["conditionTypeId"],
                            END_COND_LAP_BUTTON["conditionTypeId"])


class TestPaceToMps(unittest.TestCase):

    def test_5_00_per_km(self):
        # 5:00 = 300 s → 1000/300 ≈ 3.3333 m/s
        result = _pace_to_mps("5:00")
        self.assertAlmostEqual(result, round(1000 / 300, 4), places=4)

    def test_4_30_per_km(self):
        result = _pace_to_mps("4:30")
        self.assertAlmostEqual(result, round(1000 / 270, 4), places=4)

    def test_6_00_per_km(self):
        result = _pace_to_mps("6:00")
        self.assertAlmostEqual(result, round(1000 / 360, 4), places=4)

    def test_returns_float(self):
        self.assertIsInstance(_pace_to_mps("5:30"), float)


# ---------------------------------------------------------------------------
# extract_date_from_filename
# ---------------------------------------------------------------------------

class TestExtractDateFromFilename(unittest.TestCase):

    def test_basic_pattern(self):
        result = extract_date_from_filename("W11_03-14_Sat_Long_14km", year=2026)
        self.assertEqual(result, "2026-03-14")

    def test_explicit_year(self):
        result = extract_date_from_filename("W01_01-07_Mon_Easy", year=2025)
        self.assertEqual(result, "2025-01-07")

    def test_no_match_returns_none(self):
        result = extract_date_from_filename("some_random_filename")
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        result = extract_date_from_filename("")
        self.assertIsNone(result)

    def test_auto_year_future_date(self):
        """A date that hasn't passed yet → current year."""
        today = datetime.date.today()
        # Build a date 30 days in the future
        future = today + datetime.timedelta(days=30)
        filename = f"W01_{future.month:02d}-{future.day:02d}_Mon_Easy"
        result = extract_date_from_filename(filename)
        expected = datetime.date(today.year, future.month, future.day).isoformat()
        self.assertEqual(result, expected)

    def test_auto_year_past_date_bumps_to_next_year(self):
        """A date that has already passed → next year."""
        today = datetime.date.today()
        # Build a date 30 days in the past
        past = today - datetime.timedelta(days=30)
        filename = f"W01_{past.month:02d}-{past.day:02d}_Mon_Easy"
        result = extract_date_from_filename(filename)
        expected = datetime.date(today.year + 1, past.month, past.day).isoformat()
        self.assertEqual(result, expected)


# ---------------------------------------------------------------------------
# Individual step-type mappers (via map_steps)
# ---------------------------------------------------------------------------

class TestDistHr(unittest.TestCase):

    def setUp(self):
        self.step = _step(step_type="dist_hr", km=5, hr_low=130, hr_high=145,
                          intensity="active")
        self.result = map_steps([self.step])[0]

    def test_type(self):
        self.assertEqual(self.result["type"], "ExecutableStepDTO")

    def test_end_condition_distance(self):
        self.assertEqual(self.result["endCondition"], END_COND_DISTANCE)

    def test_end_condition_value_in_metres(self):
        self.assertAlmostEqual(self.result["endConditionValue"], 5000.0)

    def test_target_hr(self):
        self.assertEqual(self.result["targetType"], TARGET_HR)

    def test_hr_values(self):
        self.assertEqual(self.result["targetValueLow"], 130)
        self.assertEqual(self.result["targetValueHigh"], 145)

    def test_step_order(self):
        self.assertEqual(self.result["stepOrder"], 1)


class TestTimeHr(unittest.TestCase):

    def setUp(self):
        self.step = _step(step_type="time_hr", seconds=600, hr_low=120, hr_high=140,
                          intensity="warmup")
        self.result = map_steps([self.step])[0]

    def test_end_condition_time(self):
        self.assertEqual(self.result["endCondition"], END_COND_TIME)

    def test_end_condition_value(self):
        self.assertAlmostEqual(self.result["endConditionValue"], 600.0)

    def test_target_hr(self):
        self.assertEqual(self.result["targetType"], TARGET_HR)

    def test_step_type_key_warmup(self):
        self.assertEqual(self.result["stepType"]["stepTypeKey"], "warmup")


class TestDistPace(unittest.TestCase):

    def setUp(self):
        self.step = _step(step_type="dist_pace", km=1, pace_fast="4:30",
                          pace_slow="5:00", intensity="active")
        self.result = map_steps([self.step])[0]

    def test_end_condition_distance(self):
        self.assertEqual(self.result["endCondition"], END_COND_DISTANCE)

    def test_target_speed(self):
        self.assertEqual(self.result["targetType"], TARGET_SPD)

    def test_pace_fast_is_high(self):
        # pace_fast (faster = higher speed) → targetValueHigh
        expected_high = _pace_to_mps("4:30")
        self.assertAlmostEqual(self.result["targetValueHigh"], expected_high, places=4)

    def test_pace_slow_is_low(self):
        expected_low = _pace_to_mps("5:00")
        self.assertAlmostEqual(self.result["targetValueLow"], expected_low, places=4)


class TestTimePace(unittest.TestCase):

    def setUp(self):
        self.step = _step(step_type="time_pace", seconds=300, pace_fast="5:00",
                          pace_slow="5:30", intensity="active")
        self.result = map_steps([self.step])[0]

    def test_end_condition_time(self):
        self.assertEqual(self.result["endCondition"], END_COND_TIME)

    def test_target_speed(self):
        self.assertEqual(self.result["targetType"], TARGET_SPD)

    def test_end_condition_value(self):
        self.assertAlmostEqual(self.result["endConditionValue"], 300.0)


class TestDistOpen(unittest.TestCase):

    def setUp(self):
        self.step = _step(step_type="dist_open", km=2, intensity="warmup")
        self.result = map_steps([self.step])[0]

    def test_end_condition_distance(self):
        self.assertEqual(self.result["endCondition"], END_COND_DISTANCE)

    def test_no_target(self):
        self.assertEqual(self.result["targetType"], TARGET_NO)

    def test_no_target_value_fields(self):
        self.assertNotIn("targetValueLow", self.result)
        self.assertNotIn("targetValueHigh", self.result)


class TestTimeStep(unittest.TestCase):

    def setUp(self):
        self.step = _step(step_type="time_step", seconds=90)
        self.result = map_steps([self.step])[0]

    def test_end_condition_time(self):
        self.assertEqual(self.result["endCondition"], END_COND_TIME)

    def test_step_type_key_recovery(self):
        self.assertEqual(self.result["stepType"]["stepTypeKey"], "recovery")

    def test_no_target(self):
        self.assertEqual(self.result["targetType"], TARGET_NO)


class TestOpenStep(unittest.TestCase):
    """open_step → 60 s recovery fallback."""

    def setUp(self):
        self.step = _step(step_type="open_step")
        self.result = map_steps([self.step])[0]

    def test_fallback_to_60s(self):
        self.assertAlmostEqual(self.result["endConditionValue"], 60.0)

    def test_end_condition_time(self):
        self.assertEqual(self.result["endCondition"], END_COND_TIME)

    def test_step_type_key_recovery(self):
        self.assertEqual(self.result["stepType"]["stepTypeKey"], "recovery")


# ---------------------------------------------------------------------------
# sbu_block
# ---------------------------------------------------------------------------

class TestSbuBlock(unittest.TestCase):

    def test_default_drills_and_reps(self):
        """No drills list → 4 drills × 2 reps = 8 iterations."""
        step = _step(step_type="sbu_block", extra={"reps": 2})
        result = map_steps([step])[0]
        self.assertEqual(result["type"], "RepeatGroupDTO")
        self.assertEqual(result["numberOfIterations"], 8)
        self.assertAlmostEqual(result["endConditionValue"], 8.0)

    def test_custom_drill_count(self):
        drills = [Drill(name=f"Drill{i}", seconds=30, reps=2) for i in range(3)]
        step = _step(step_type="sbu_block", drills=drills, extra={"reps": 2})
        result = map_steps([step])[0]
        # 3 drills × 2 reps = 6
        self.assertEqual(result["numberOfIterations"], 6)

    def test_child_steps_structure(self):
        """Must have exactly 2 child steps: active (30 s) + recovery (90 s)."""
        step = _step(step_type="sbu_block")
        result = map_steps([step])[0]
        children = result["workoutSteps"]
        self.assertEqual(len(children), 2)
        self.assertAlmostEqual(children[0]["endConditionValue"], 30.0)
        self.assertAlmostEqual(children[1]["endConditionValue"], 90.0)

    def test_end_condition_iterations(self):
        step = _step(step_type="sbu_block")
        result = map_steps([step])[0]
        self.assertEqual(result["endCondition"], END_COND_ITERATIONS)

    def test_smart_repeat_false(self):
        step = _step(step_type="sbu_block")
        result = map_steps([step])[0]
        self.assertFalse(result["smartRepeat"])


# ---------------------------------------------------------------------------
# repeat
# ---------------------------------------------------------------------------

class TestRepeat(unittest.TestCase):

    def _make_interval_block(self, count: int, back_to: int) -> list[WorkoutStep]:
        """Returns [warmup, interval, recovery, repeat] steps."""
        steps = [
            _step(step_type="dist_hr",   km=2,    hr_low=130, hr_high=145, intensity="warmup"),
            _step(step_type="dist_pace", km=1,    pace_fast="4:00", pace_slow="4:30", intensity="active"),
            _step(step_type="time_step", seconds=120),
            _step(step_type="repeat",    back_to_offset=back_to, count=count),
        ]
        return steps

    def test_repeat_group_type(self):
        steps = self._make_interval_block(count=4, back_to=1)
        result = map_steps(steps)
        # warmup + repeat group (2 steps consumed)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["type"], "RepeatGroupDTO")

    def test_repeat_iterations(self):
        steps = self._make_interval_block(count=6, back_to=1)
        result = map_steps(steps)
        repeat_group = result[1]
        self.assertEqual(repeat_group["numberOfIterations"], 6)
        self.assertAlmostEqual(repeat_group["endConditionValue"], 6.0)

    def test_repeat_body_steps_consumed(self):
        """Steps inside back_to_offset..repeat must NOT appear as top-level steps."""
        steps = self._make_interval_block(count=4, back_to=1)
        result = map_steps(steps)
        types = [s.get("type") for s in result]
        # Only ExecutableStepDTO (warmup) and RepeatGroupDTO — no standalone interval/recovery
        self.assertNotIn(None, types)
        repeat_count = sum(1 for t in types if t == "RepeatGroupDTO")
        self.assertEqual(repeat_count, 1)

    def test_repeat_child_step_orders(self):
        """Child steps inside RepeatGroupDTO must have consecutive stepOrders starting at 1."""
        steps = self._make_interval_block(count=4, back_to=1)
        result = map_steps(steps)
        children = result[1]["workoutSteps"]
        orders = [c["stepOrder"] for c in children]
        self.assertEqual(orders, list(range(1, len(children) + 1)))

    def test_repeat_whole_workout_as_body(self):
        """back_to_offset=0 → entire preceding workout wrapped."""
        steps = [
            _step(step_type="dist_hr", km=1, hr_low=130, hr_high=140),
            _step(step_type="time_step", seconds=60),
            _step(step_type="repeat", back_to_offset=0, count=3),
        ]
        result = map_steps(steps)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "RepeatGroupDTO")
        self.assertEqual(result[0]["numberOfIterations"], 3)


# ---------------------------------------------------------------------------
# Unknown step type
# ---------------------------------------------------------------------------

class TestUnknownStepType(unittest.TestCase):

    def test_unknown_type_skipped(self):
        steps = [
            _step(step_type="dist_hr", km=1, hr_low=130, hr_high=145),
            _step(step_type="totally_unknown"),
            _step(step_type="time_step", seconds=60),
        ]
        result = map_steps(steps)
        # Unknown step silently dropped
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# map_steps — step order is sequential
# ---------------------------------------------------------------------------

class TestMapStepsOrdering(unittest.TestCase):

    def test_step_order_sequential(self):
        steps = [
            _step(step_type="dist_open", km=2),
            _step(step_type="time_step", seconds=60),
            _step(step_type="dist_hr",   km=1, hr_low=120, hr_high=140),
        ]
        result = map_steps(steps)
        self.assertEqual([s["stepOrder"] for s in result], [1, 2, 3])


# ---------------------------------------------------------------------------
# map_workout
# ---------------------------------------------------------------------------

class TestMapWorkout(unittest.TestCase):

    def setUp(self):
        steps = [
            _step(step_type="dist_hr", km=2, hr_low=130, hr_high=145, intensity="warmup"),
            _step(step_type="time_step", seconds=60),
        ]
        self.workout = _workout(steps, filename="W05_02-01_Test", estimated_duration_min=45)
        self.payload = map_workout(self.workout)

    def test_top_level_keys(self):
        for key in ("workoutName", "estimatedDurationInSecs", "description",
                    "sportType", "author", "workoutSegments"):
            self.assertIn(key, self.payload)

    def test_workout_name(self):
        self.assertEqual(self.payload["workoutName"], "W05_02-01_Test")

    def test_estimated_duration(self):
        self.assertEqual(self.payload["estimatedDurationInSecs"], 45 * 60)

    def test_sport_type_running(self):
        self.assertEqual(self.payload["sportType"], SPORT_TYPE_RUNNING)

    def test_single_segment(self):
        self.assertEqual(len(self.payload["workoutSegments"]), 1)

    def test_segment_order(self):
        self.assertEqual(self.payload["workoutSegments"][0]["segmentOrder"], 1)

    def test_segment_contains_steps(self):
        segment_steps = self.payload["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(len(segment_steps), 2)

    def test_fallback_name_when_filename_none(self):
        workout = Workout(filename=None, name="My Run", steps=[])
        payload = map_workout(workout)
        self.assertEqual(payload["workoutName"], "My Run")

    def test_fallback_name_both_none(self):
        workout = Workout(filename=None, name=None, steps=[])
        payload = map_workout(workout)
        self.assertEqual(payload["workoutName"], "Workout")

    def test_estimated_duration_zero_when_none(self):
        workout = Workout(filename="test", estimated_duration_min=None, steps=[])
        payload = map_workout(workout)
        self.assertEqual(payload["estimatedDurationInSecs"], 0)

    def test_author_empty_dict(self):
        self.assertEqual(self.payload["author"], {})


# ---------------------------------------------------------------------------
# Intensity → stepTypeKey mapping
# ---------------------------------------------------------------------------

class TestIntensityMapping(unittest.TestCase):

    def _get_step_key(self, intensity: str, step_type="dist_hr") -> str:
        step = _step(step_type=step_type, km=1, hr_low=130, hr_high=140,
                     intensity=intensity)
        return map_steps([step])[0]["stepType"]["stepTypeKey"]

    def test_warmup_intensity(self):
        self.assertEqual(self._get_step_key("warmup"), "warmup")

    def test_cooldown_intensity(self):
        self.assertEqual(self._get_step_key("cooldown"), "cooldown")

    def test_active_intensity(self):
        self.assertEqual(self._get_step_key("active"), "interval")

    def test_recovery_intensity(self):
        self.assertEqual(self._get_step_key("recovery"), "recovery")

    def test_none_intensity_defaults_to_interval(self):
        self.assertEqual(self._get_step_key(None), "interval")


if __name__ == "__main__":
    unittest.main()
