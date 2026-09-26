"""The FIT file (USB) and the Garmin Connect payload must describe the same workout.

Both are built from the same YAML. FIT stores repeats flat (a repeat step jumps
back to an earlier index), Garmin Connect stores a tree of RepeatGroupDTOs.
These tests execute both representations step by step and compare what the
runner would actually do.
"""

import datetime
import unittest
from unittest.mock import Mock

from garmin_fit.build_from_plan import build_workout_steps
from garmin_fit.garmin_calendar_export import GarminCalendarExporter
from garmin_fit.garmin_step_mapper import map_steps
from garmin_fit.plan_domain import plan_from_data
from garmin_fit.workout_utils import km_to_dist, sec_to_time

_REPEAT = 6  # WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT
_TIME = 0
_DISTANCE = 1


def _workout(steps):
    data = {"workouts": [{"filename": "W40_10-01_Thu_Test", "name": "W40_10-01_Thu_Test", "steps": steps}]}
    return plan_from_data(data).workouts[0]


def _execute_fit(fit_steps):
    """Run flat FIT steps the way the watch does; a finished repeat resets its counter."""
    executed, counters, i = [], {}, 0
    while i < len(fit_steps):
        step = fit_steps[i]
        if step.duration_type == _REPEAT:
            counters[i] = counters.get(i, 0) + 1
            if counters[i] < step.target_value:
                i = int(step.duration_value)
                continue
            counters[i] = 0
        elif step.duration_type == _TIME:
            executed.append(("time", step.duration_value))
        elif step.duration_type == _DISTANCE:
            executed.append(("distance", step.duration_value))
        else:
            executed.append(("open", None))
        i += 1
    return executed


def _execute_garmin(steps):
    executed = []
    for step in steps:
        if step["type"] == "RepeatGroupDTO":
            for _ in range(step["numberOfIterations"]):
                executed.extend(_execute_garmin(step["workoutSteps"]))
            continue
        key = step["endCondition"]["conditionTypeKey"]
        if key == "time":
            executed.append(("time", sec_to_time(step["endConditionValue"])))
        elif key == "distance":
            executed.append(("distance", km_to_dist(step["endConditionValue"] / 1000)))
        else:
            executed.append(("open", None))
    return executed


def _both(steps):
    workout = _workout(steps)
    return _execute_fit(build_workout_steps(workout)), _execute_garmin(map_steps(workout.steps))


class FitGarminEquivalenceTests(unittest.TestCase):
    def test_simple_intervals(self):
        fit, garmin = _both([
            {"type": "dist_open", "km": 2.0, "intensity": "warmup"},
            {"type": "dist_hr", "km": 1.0, "hr_low": 170, "hr_high": 175},
            {"type": "time_step", "seconds": 120},
            {"type": "repeat", "back_to_offset": 1, "count": 4},
            {"type": "dist_open", "km": 1.0, "intensity": "cooldown"},
        ])
        self.assertEqual(len(fit), 1 + 4 * 2 + 1)
        self.assertEqual(fit, garmin)

    def test_nested_sets(self):
        # 3 sets of (2 × (400 m + 60 s)) + 3 min between sets.
        fit, garmin = _both([
            {"type": "dist_open", "km": 2.0},
            {"type": "dist_open", "km": 0.4},
            {"type": "time_step", "seconds": 60},
            {"type": "repeat", "back_to_offset": 1, "count": 2},
            {"type": "time_step", "seconds": 180},
            {"type": "repeat", "back_to_offset": 1, "count": 3},
        ])
        self.assertEqual(len(fit), 1 + 3 * (2 * 2 + 1))
        self.assertEqual(fit, garmin)

    def test_repeat_after_sbu_block_counts_expanded_steps(self):
        workout = _workout([
            {"type": "sbu_block", "drills": [{"name": "A", "seconds": 20, "reps": 2}]},
            {"type": "time_step", "seconds": 30},
            {"type": "time_step", "seconds": 45},
            {"type": "repeat", "back_to_offset": 1, "count": 6},
        ])
        fit = _execute_fit(build_workout_steps(workout))
        garmin = _execute_garmin(map_steps(workout.steps))
        # SBU recovery is a lap-button step in FIT but a timed step in Garmin
        # Connect (the REST API has no lap-button recovery), so compare the
        # sequence length and the part after the drills exactly.
        self.assertEqual(len(fit), len(garmin))
        self.assertEqual(fit[4:], garmin[4:])
        self.assertEqual(len(fit[4:]), 6 * 2)


class GarminImportRoundTripTests(unittest.TestCase):
    def test_uploaded_nested_workout_imports_back_to_the_same_steps(self):
        from garmin_fit.garmin_step_mapper import map_workout
        from garmin_fit.garmin_workout_import import workout_from_garmin

        steps = [
            {"type": "dist_pace", "km": 2.0, "pace_fast": "5:45", "pace_slow": "6:00", "intensity": "warmup"},
            {"type": "dist_hr", "km": 0.4, "hr_low": 175, "hr_high": 182, "intensity": "active"},
            {"type": "time_step", "seconds": 90, "intensity": "recovery"},
            {"type": "repeat", "back_to_offset": 1, "count": 4},
            {"type": "time_step", "seconds": 180, "intensity": "recovery"},
            {"type": "repeat", "back_to_offset": 1, "count": 3},
            {"type": "time_cadence", "seconds": 300, "cad_low": 170, "cad_high": 180, "intensity": "cooldown"},
        ]
        workout = _workout(steps)
        imported = workout_from_garmin(map_workout(workout), date="2026-10-01")

        def shape(step):
            return (step.step_type, step.km, step.seconds, step.hr_low, step.hr_high,
                    step.pace_fast, step.pace_slow, step.cad_low, step.cad_high,
                    step.back_to_offset, step.count, step.intensity if step.step_type != "repeat" else None)

        self.assertEqual([shape(s) for s in imported.steps], [shape(s) for s in workout.steps])


class FitUnitConversionTests(unittest.TestCase):
    def test_distance_is_rounded_not_truncated(self):
        # 1.15 * 100 == 114.99999999999999 in floating point.
        self.assertEqual(km_to_dist(1.15), 115)
        self.assertEqual(km_to_dist(2.3), 230)
        for meters in range(10, 42200, 10):
            self.assertEqual(km_to_dist(meters / 1000), meters // 10, meters)


class CalendarUploadSafetyTests(unittest.TestCase):
    def _plan(self, filename, steps):
        return plan_from_data({"workouts": [{"filename": filename, "name": filename, "steps": steps}]})

    def test_skip_past_skips_yesterday_instead_of_moving_it_a_year_ahead(self):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        filename = f"W{yesterday.isocalendar()[1]:02d}_{yesterday:%m-%d}_{yesterday:%a}_Easy"
        plan = self._plan(filename, [{"type": "dist_open", "km": 5.0}])

        result = GarminCalendarExporter(Mock()).upload_plan(plan, dry_run=True, skip_past=True)

        self.assertEqual(result.total, 0)

    def test_dry_run_reports_unmappable_workout_instead_of_dropping_a_step(self):
        workout = _workout([{"type": "dist_open", "km": 5.0}])
        workout.steps[0].step_type = "unsupported_kind"

        result = GarminCalendarExporter(Mock()).upload_and_schedule(workout, dry_run=True)

        self.assertIn("unsupported_kind", result.error)


class YearInferenceTests(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 26)

    def test_infer_date_nearest_and_weekday(self):
        from garmin_fit.garmin_step_mapper import infer_date

        self.assertEqual(infer_date(9, 25, today=self.TODAY), datetime.date(2026, 9, 25))
        self.assertEqual(infer_date(1, 5, today=self.TODAY), datetime.date(2027, 1, 5))
        # 2027-01-05 is a Tuesday, 2026-01-05 a Monday.
        self.assertEqual(infer_date(1, 5, weekday=0, today=self.TODAY), datetime.date(2026, 1, 5))
        self.assertIsNone(infer_date(2, 30, today=self.TODAY))

    def test_llm_segment_header_without_year_is_not_pinned_to_2025(self):
        from garmin_fit.garmin_step_mapper import infer_date
        from garmin_fit.llm.client import UnifiedLLMClient

        info = UnifiedLLMClient._extract_segment_header_info("01.10 — Лёгкий бег 8 км")
        expected = infer_date(10, 1)
        self.assertEqual(info["weekday"], expected.strftime("%a"))
        self.assertEqual(info["week"], expected.isocalendar()[1])

    def test_header_weekday_round_trips_through_filename_date(self):
        """The weekday the LLM path writes must lead extract_date back to the same date."""
        from garmin_fit.garmin_step_mapper import extract_date_from_filename, infer_date
        from garmin_fit.llm.client import UnifiedLLMClient

        info = UnifiedLLMClient._extract_segment_header_info("01.10 — Лёгкий бег 8 км")
        name = f"W{info['week']:02d}_10-01_{info['weekday']}_Easy"
        self.assertEqual(extract_date_from_filename(name), infer_date(10, 1).isoformat())


if __name__ == "__main__":
    unittest.main()
