import unittest

from Scripts.llm.benchmark import evaluate_case_expectations


class TestLlmBenchmark(unittest.TestCase):
    def test_evaluate_case_expectations_collects_warning_and_error_checks(self):
        data = {
            "workouts": [
                {
                    "filename": "W09_03-04_Wed_Intervals_Hills_2x5x40m",
                    "name": "W09_03-04_Wed_Intervals_Hills_2x5x40m",
                    "desc": "Intervals",
                    "type_code": "intervals",
                    "distance_km": 8.4,
                    "estimated_duration_min": 58,
                    "steps": [
                        {"type": "dist_hr", "km": 2.0},
                        {"type": "dist_open", "km": 0.04, "intensity": "active"},
                        {"type": "dist_open", "km": 0.4, "intensity": "recovery"},
                        {"type": "repeat", "back_to_offset": 1, "count": 5},
                    ],
                }
            ]
        }
        case = {
            "expected_workout_count": 1,
            "expected_filenames": ["W09_03-04_Wed_Intervals_Hills_2x5x40m"],
            "checks": [
                {
                    "kind": "step_field",
                    "workout": "W09_03-04_Wed_Intervals_Hills_2x5x40m",
                    "step_index": 0,
                    "field": "intensity",
                    "equals": "warmup",
                    "severity": "warning",
                },
                {
                    "kind": "step_field",
                    "workout": "W09_03-04_Wed_Intervals_Hills_2x5x40m",
                    "step_index": 3,
                    "field": "count",
                    "equals": 5,
                },
            ],
        }

        results = evaluate_case_expectations(
            data,
            case,
            source_text="4.03 (ср)\nИнтервалы\n2x40 м\nПульс до 155\n",
        )

        self.assertGreaterEqual(len(results), 5)
        self.assertTrue(any(item.severity == "warning" and not item.passed for item in results))
        self.assertTrue(any(item.severity == "error" and item.passed for item in results))
        self.assertTrue(any("source facts" in item.message.lower() for item in results))
