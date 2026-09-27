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

    def test_missing_reference_only_target_is_tolerated(self):
        reference = [{"type": "dist_hr", "km": 2.0, "hr_low": 130, "hr_high": 145}]
        self.assertEqual(compare_to_canonical(
            [{"type": "dist_open", "km": 2.0}], reference,
            source_text="Разминка 2 км", allow_missing_targets=True,
        ), [])
        self.assertTrue(compare_to_canonical(
            [{"type": "dist_open", "km": 2.0}], reference,
            source_text="Разминка 2 км, пульс 130-145", allow_missing_targets=True,
        ))
        wrong = [{"type": "dist_hr", "km": 2.0, "hr_low": 120, "hr_high": 145}]
        self.assertTrue(compare_to_canonical(wrong, reference))

    def test_cap_floor_60_and_reference_80_are_the_same_cap(self):
        reference = [{"type": "dist_hr", "km": 8.0, "hr_low": 80, "hr_high": 140}]
        ours = [{"type": "dist_hr", "km": 8.0, "hr_low": 60, "hr_high": 140}]
        self.assertEqual(compare_to_canonical(ours, reference, source_text="пульс до 140"), [])
        self.assertTrue(compare_to_canonical(ours, reference, source_text="пульс 80-140"))
        other_cap = [{"type": "dist_hr", "km": 8.0, "hr_low": 60, "hr_high": 150}]
        self.assertTrue(compare_to_canonical(other_cap, reference))

    def test_wrong_intensity_and_omitted_explicit_target_fail(self):
        reference = [{"type": "dist_hr", "km": 8.0, "hr_low": 120, "hr_high": 140,
                      "intensity": "warmup"}]
        missing = [{"type": "dist_open", "km": 8.0, "intensity": "warmup"}]
        wrong_intensity = [{"type": "dist_hr", "km": 8.0, "hr_low": 120, "hr_high": 140,
                            "intensity": "cooldown"}]
        self.assertTrue(compare_to_canonical(
            missing, reference, source_text="Разминка 8 км, пульс 120-140",
            allow_missing_targets=True,
        ))
        self.assertTrue(compare_to_canonical(wrong_intensity, reference))

        case = {"expected_steps": reference}
        checks = evaluate_case_expectations(
            {"workouts": [{"steps": missing}]}, case,
            source_text="Разминка 8 км, пульс 120-140", check_source_facts=False,
        )
        self.assertFalse(all(check.passed for check in checks))

    def test_source_target_must_stay_on_its_step(self):
        source = "Разминка 2 км, потом работа 3 км пульс 140-150"
        reference = [
            {"type": "dist_hr", "km": 2.0, "hr_low": 140, "hr_high": 150,
             "intensity": "warmup"},
            {"type": "dist_hr", "km": 3.0, "hr_low": 140, "hr_high": 150,
             "intensity": "active"},
        ]
        generated = [
            dict(reference[0]),
            {"type": "dist_open", "km": 3.0, "intensity": "active"},
        ]
        self.assertTrue(compare_to_canonical(
            generated, reference, source_text=source, allow_missing_targets=True,
        ))


if __name__ == "__main__":
    unittest.main()
