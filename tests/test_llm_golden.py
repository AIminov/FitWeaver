import tempfile
import unittest
from pathlib import Path

import yaml

from garmin_fit.llm.benchmark import evaluate_case_expectations
from garmin_fit.llm.golden import DEFAULT_GOLDEN_PATH, build_suite_from_golden, compare_to_canonical


class GoldenSuiteTests(unittest.TestCase):
    def test_suite_has_one_case_per_valid_single_workout_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite_path = build_suite_from_golden(DEFAULT_GOLDEN_PATH, Path(tmp))
            suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
            first = suite["cases"][0]
            self.assertTrue((Path(tmp) / first["input_path"]).exists())
        self.assertGreaterEqual(len(suite["cases"]), 50)
        self.assertEqual(first["expected_workout_count"], 1)
        self.assertTrue(first["expected_steps"])

    def test_expected_steps_check_passes_on_reference_and_fails_on_changed_distance(self):
        steps = [
            {"type": "dist_pace", "km": 2.0, "pace_fast": "5:45", "pace_slow": "6:00"},
            {"type": "dist_open", "km": 0.4},
            {"type": "repeat", "back_to_offset": 1, "count": 6},
        ]
        case = {"expected_steps": steps}
        ok = evaluate_case_expectations({"workouts": [{"steps": steps}]}, case)
        self.assertTrue(all(result.passed for result in ok))

        changed = [dict(steps[0]), {"type": "dist_open", "km": 0.5}, dict(steps[2])]
        bad = evaluate_case_expectations({"workouts": [{"steps": changed}]}, case)
        self.assertFalse(all(result.passed for result in bad))

    def test_missing_target_is_tolerated_but_a_wrong_one_is_not(self):
        reference = [{"type": "dist_hr", "km": 2.0, "hr_low": 130, "hr_high": 145}]
        self.assertEqual(compare_to_canonical([{"type": "dist_open", "km": 2.0}], reference), [])
        wrong = [{"type": "dist_hr", "km": 2.0, "hr_low": 120, "hr_high": 145}]
        self.assertTrue(compare_to_canonical(wrong, reference))

    def test_cap_floor_60_and_reference_80_are_the_same_cap(self):
        reference = [{"type": "dist_hr", "km": 8.0, "hr_low": 80, "hr_high": 140}]
        ours = [{"type": "dist_hr", "km": 8.0, "hr_low": 60, "hr_high": 140}]
        self.assertEqual(compare_to_canonical(ours, reference, allow_missing_targets=False), [])
        other_cap = [{"type": "dist_hr", "km": 8.0, "hr_low": 60, "hr_high": 150}]
        self.assertTrue(compare_to_canonical(other_cap, reference))


if __name__ == "__main__":
    unittest.main()
