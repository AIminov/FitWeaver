import unittest

from garmin_fit.plan_processing import normalize_source_text, repair_plan_data
from garmin_fit.plan_service import count_workouts, has_default_sbu_block


class PlanProcessingTests(unittest.TestCase):
    def test_normalize_source_text_standardizes_input_and_flags_ambiguity(self):
        analysis = normalize_source_text(
            "\u0420\u0430\u0437\u043c. 10 \u043c\u0438\u043d\n8 \u00D7 800\n\u043f\u0440\u0438\u043c\u0435\u0440\u043d\u043e 4.20"
        )

        self.assertIn("\u0440\u0430\u0437\u043c\u0438\u043d\u043a\u0430", analysis.text.lower())
        self.assertIn("8x800", analysis.text)
        self.assertTrue(any("normalized interval notation" in note for note in analysis.changes))
        self.assertIn("source text contains approximate values", analysis.ambiguities)

    def test_normalize_source_text_detects_non_rest_workout_headers(self):
        analysis = normalize_source_text(
            "2.03 (пн)\nВыходной\n\n"
            "3.03 (вт)\nКросс спокойно\n8 км\n\n"
            "4.03 (ср)\nИнтервалы\n"
        )

        self.assertEqual(analysis.expected_workouts, 2)
        self.assertEqual(analysis.workout_headers, ["3.03 (вт)", "4.03 (ср)"])

    def test_normalize_source_text_keeps_interval_blocks_with_rest_word(self):
        analysis = normalize_source_text(
            "10.03 (Tue)\nEasy run\n6 km\n\n"
            "12.03 (Thu)\nIntervals\n4x800 m, rest 400 m jog\n\n"
            "13.03 (Fri)\nRest day\n"
        )

        self.assertEqual(analysis.expected_workouts, 2)
        self.assertEqual(analysis.workout_headers, ["10.03 (Tue)", "12.03 (Thu)"])

    def test_repair_plan_data_aligns_names_and_defaults(self):
        data = {
            "workouts": [
                {
                    "filename": " W01 Easy/Run ",
                    "steps": [
                        {
                            "type": "distance_pace",
                            "km": "5",
                            "pace_fast": "5.0",
                            "pace_slow": "6 00",
                        },
                        {
                            "type": "sbu_block",
                            "drills": [{"name": " Bounds ", "seconds": "30"}],
                        },
                    ],
                }
            ]
        }

        repaired, notes = repair_plan_data(data)
        workout = repaired["workouts"][0]
        main_step = workout["steps"][0]
        sbu_step = workout["steps"][1]
        drill = sbu_step["drills"][0]

        self.assertEqual(workout["filename"], "W01_Easy_Run")
        self.assertEqual(workout["name"], "W01_Easy_Run")
        self.assertEqual(main_step["type"], "dist_pace")
        self.assertEqual(main_step["km"], 5.0)
        self.assertEqual(main_step["pace_fast"], "5:00")
        self.assertEqual(main_step["pace_slow"], "6:00")
        self.assertEqual(drill["seconds"], 30)
        self.assertEqual(drill["reps"], 2)
        self.assertEqual(drill["name"], "Bounds")
        self.assertTrue(any("aligned filename/name" in note for note in notes))

    def test_repair_plan_data_recomputes_calendar_week_from_date(self):
        data = {
            "workouts": [
                {
                    "filename": "W01_03-08_Sat_Long_20km",
                    "steps": [{"type": "dist_open", "km": 20}],
                }
            ]
        }

        repaired, _notes = repair_plan_data(data)
        workout = repaired["workouts"][0]

        self.assertEqual(workout["filename"], "W10_03-08_Sat_Long_20km")
        self.assertEqual(workout["name"], "W10_03-08_Sat_Long_20km")

    def test_repair_plan_data_parses_russian_date_and_weekday(self):
        data = {
            "workouts": [
                {
                    "filename": "8.03 (вс) easy run",
                    "steps": [{"type": "dist_open", "km": 8}],
                }
            ]
        }

        repaired, _notes = repair_plan_data(data)
        workout = repaired["workouts"][0]

        self.assertEqual(workout["filename"], "W10_03-08_Sun_easy_run")
        self.assertEqual(workout["name"], "W10_03-08_Sun_easy_run")

    def test_repair_plan_data_uses_sequence_fallback_when_no_date(self):
        data = {
            "workouts": [
                {
                    "filename": "понедельник easy 6km",
                    "steps": [{"type": "dist_open", "km": 6}],
                },
                {
                    "filename": "2 threshold",
                    "steps": [{"type": "dist_open", "km": 5}],
                },
            ]
        }

        repaired, _notes = repair_plan_data(data)

        self.assertEqual(repaired["workouts"][0]["filename"], "N01_Mon_easy_6km")
        self.assertEqual(repaired["workouts"][1]["filename"], "N02_threshold")

    def test_repair_plan_data_converts_cooldown_single_hr_cap_to_hr_range(self):
        data = {
            "workouts": [
                {
                    "filename": "W10_03-10_Tue_Easy_6km",
                    "name": "W10_03-10_Tue_Easy_6km",
                    "steps": [
                        {"type": "dist_hr", "km": 4, "hr_low": 130, "hr_high": 145},
                        {"type": "dist_hr", "km": 2, "hr_low": None, "hr_high": 130, "intensity": "cooldown"},
                    ],
                }
            ]
        }

        repaired, notes = repair_plan_data(data)
        cooldown = repaired["workouts"][0]["steps"][1]

        self.assertEqual(cooldown["type"], "dist_hr")
        self.assertEqual(cooldown["km"], 2)
        self.assertEqual(cooldown["intensity"], "cooldown")
        self.assertEqual(cooldown["hr_low"], 80)
        self.assertEqual(cooldown["hr_high"], 130)
        self.assertTrue(any("repaired cooldown upper-only HR cap" in note for note in notes))

    def test_repair_plan_data_converts_equal_cooldown_hr_range_to_80_based_range(self):
        data = {
            "workouts": [
                {
                    "filename": "W10_03-10_Tue_Easy_6km",
                    "name": "W10_03-10_Tue_Easy_6km",
                    "steps": [
                        {"type": "time_hr", "seconds": 600, "hr_low": 130, "hr_high": 130, "intensity": "cooldown"},
                    ],
                }
            ]
        }

        repaired, _notes = repair_plan_data(data)
        cooldown = repaired["workouts"][0]["steps"][0]

        self.assertEqual(cooldown["type"], "time_hr")
        self.assertEqual(cooldown["seconds"], 600)
        self.assertEqual(cooldown["hr_low"], 80)
        self.assertEqual(cooldown["hr_high"], 130)

    def test_repair_plan_data_normalizes_single_step_warmup_to_active(self):
        data = {
            "workouts": [
                {
                    "filename": "W18_05-01_Fri_Easy_10km",
                    "name": "W18_05-01_Fri_Easy_10km",
                    "steps": [
                        {
                            "type": "dist_hr",
                            "km": 10,
                            "hr_low": 120,
                            "hr_high": 140,
                            "intensity": "warmup",
                        },
                    ],
                }
            ]
        }

        repaired, notes = repair_plan_data(data)
        step = repaired["workouts"][0]["steps"][0]

        self.assertEqual(step["intensity"], "active")
        self.assertTrue(any("normalized single-step intensity" in note for note in notes))

    def test_service_helpers_count_workouts_and_sbu_defaults(self):
        data = {
            "workouts": [
                {
                    "filename": "W01_TEST",
                    "name": "W01_TEST",
                    "steps": [{"type": "sbu_block"}],
                }
            ]
        }

        self.assertEqual(count_workouts(data), 1)
        self.assertTrue(has_default_sbu_block(data))


if __name__ == "__main__":
    unittest.main()

