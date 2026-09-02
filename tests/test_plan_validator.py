import unittest

from garmin_fit.plan_validator import parse_and_validate_yaml_text, validate_plan_data_detailed


class PlanValidatorTests(unittest.TestCase):
    def test_valid_minimal_plan(self):
        yaml_text = """
workouts:
- filename: W01_05-12_Mon_Easy_5km
  name: W01_05-12_Mon_Easy_5km
  steps:
  - type: dist_hr
    km: 5
    hr_low: 140
    hr_high: 150
"""
        _, errors, warnings = parse_and_validate_yaml_text(yaml_text)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_filename_name_mismatch(self):
        yaml_text = """
workouts:
- filename: W01_A
  name: W01_B
  steps:
  - type: dist_hr
    km: 5
    hr_low: 140
    hr_high: 150
"""
        _, errors, _ = parse_and_validate_yaml_text(yaml_text)
        self.assertTrue(any("filename and name must be identical" in e for e in errors))

    def test_repeat_must_reference_previous_step(self):
        yaml_text = """
workouts:
- filename: W01_REPEAT
  name: W01_REPEAT
  steps:
  - type: repeat
    back_to_offset: 0
    count: 3
"""
        _, errors, _ = parse_and_validate_yaml_text(yaml_text)
        self.assertTrue(any("back_to_offset must point to a previous step" in e for e in errors))

    def test_symbolic_pace_constants_are_valid_and_ordered(self):
        data = {
            "workouts": [{
                "filename": "W01_PACE",
                "name": "W01_PACE",
                "steps": [{
                    "type": "dist_pace", "km": 5,
                    "pace_fast": "EASY_F", "pace_slow": "EASY_S",
                }],
            }],
        }
        errors, _warnings = validate_plan_data_detailed(data)
        self.assertEqual(errors, [])

    def test_crossing_repeat_ranges_are_rejected(self):
        data = {
            "workouts": [{
                "filename": "W01_REPEAT",
                "name": "W01_REPEAT",
                "steps": [
                    {"type": "dist_open", "km": 1},
                    {"type": "dist_open", "km": 1},
                    {"type": "repeat", "back_to_offset": 0, "count": 2},
                    {"type": "dist_open", "km": 1},
                    {"type": "repeat", "back_to_offset": 1, "count": 2},
                ],
            }],
        }
        errors, _warnings = validate_plan_data_detailed(data)
        self.assertTrue(any("overlap without containment" in issue.message for issue in errors))

    def test_detailed_categories_are_exposed(self):
        data = {
            "workouts": [
                {
                    "filename": "W01_A",
                    "name": "W01_B",
                    "steps": [
                        {
                            "type": "dist_pace",
                            "km": 5,
                            "pace_fast": "5.00",
                            "pace_slow": "6:00",
                        }
                    ],
                }
            ]
        }

        errors, _warnings = validate_plan_data_detailed(data)
        categories = {issue.category for issue in errors}

        self.assertIn("naming_rule_violation", categories)
        self.assertIn("pace_format_issue", categories)


if __name__ == "__main__":
    unittest.main()

