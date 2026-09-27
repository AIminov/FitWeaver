import unittest

from garmin_fit.llm.marked_source_checks import (
    compile_marked_source_repeats,
    sanitize_marked_source_targets,
    validate_marked_source_model_steps,
    validate_marked_source_structure,
)


class TestMarkedSourceChecks(unittest.TestCase):
    def _workout(self, step):
        return {"workouts": [{"steps": [step]}]}

    def test_subjective_effort_does_not_become_numeric_pace(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Интервалы
**** ШАГ ****
Тип: работа
Дистанция: 400 м
Интенсивность: темп на 10 км, строго не быстрее
"""
        data = self._workout(
            {
                "type": "dist_pace",
                "km": 0.4,
                "pace_fast": "4:50",
                "pace_slow": "5:00",
                "intensity": "active",
            }
        )

        repairs, warnings = sanitize_marked_source_targets(source, data)

        self.assertEqual(data["workouts"][0]["steps"][0]["type"], "dist_open")
        self.assertNotIn("pace_fast", data["workouts"][0]["steps"][0])
        self.assertTrue(repairs)
        self.assertTrue(warnings)

    def test_one_sided_hr_cap_is_encoded_with_the_60_floor(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Лёгкий бег
**** ШАГ ****
Тип: работа
Дистанция: 6 км
Пульс: до 140 уд/мин
"""
        data = self._workout(
            {"type": "dist_hr", "km": 6, "hr_low": 80, "hr_high": 140}
        )

        repairs, warnings = sanitize_marked_source_targets(source, data)

        self.assertEqual(data["workouts"][0]["steps"][0], {
            "type": "dist_hr", "km": 6, "hr_low": 60, "hr_high": 140, "intensity": "active",
        })
        self.assertTrue(any("restored explicit hr target" in r for r in repairs))

    def test_effort_percentage_does_not_become_heart_rate(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Ускорения
**** ШАГ ****
Тип: работа
Длительность: 30 сек
Интенсивность: 80–85% усилия
"""
        data = self._workout(
            {"type": "time_hr", "seconds": 30, "hr_low": 80, "hr_high": 85}
        )

        sanitize_marked_source_targets(source, data)

        self.assertEqual(data["workouts"][0]["steps"][0], {
            "type": "time_step", "seconds": 30, "intensity": "active",
        })

    def test_explicit_step_range_is_kept_but_workout_metadata_does_not_apply_to_steps(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Темповый бег
Целевой средний темп: 4:30 мин/км
**** ШАГ ****
Тип: разминка
Дистанция: 2 км
**** ШАГ ****
Тип: работа
Дистанция: 5 км
Темп: 4:50–5:00 мин/км
"""
        data = {
            "workouts": [
                {
                    "steps": [
                        {
                            "type": "dist_pace",
                            "km": 2,
                            "pace_fast": "5:30",
                            "pace_slow": "5:50",
                        },
                        {
                            "type": "dist_pace",
                            "km": 5,
                            "pace_fast": "4:50",
                            "pace_slow": "5:00",
                        },
                    ]
                }
            ]
        }

        repairs, warnings = sanitize_marked_source_targets(source, data)

        steps = data["workouts"][0]["steps"]
        self.assertEqual(steps[0]["type"], "dist_open")
        self.assertEqual(steps[1]["type"], "dist_pace")
        self.assertEqual(steps[1]["pace_fast"], "4:50")
        self.assertGreaterEqual(len(repairs), 1)
        self.assertEqual(warnings and len(warnings), 1)

    def test_missing_measure_becomes_open_step(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Кросс
**** ШАГ ****
Тип: работа
Пульс: нет данных
"""
        data = self._workout(
            {"type": "dist_hr", "km": None, "hr_low": 125, "hr_high": 140}
        )

        sanitize_marked_source_targets(source, data)

        self.assertEqual(data["workouts"][0]["steps"][0], {
            "type": "open_step", "intensity": "active",
        })

    def test_unsupported_model_intensity_is_removed_instead_of_becoming_data(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Бег
**** ШАГ ****
Тип: аэробный бег
Дистанция: 4 км
Интенсивность: легко, разговорный темп
"""
        data = self._workout({
            "type": "dist_open",
            "km": 4,
            "intensity": "легко, разговорный темп",
        })

        repairs, warnings = sanitize_marked_source_targets(source, data)

        step = data["workouts"][0]["steps"][0]
        self.assertNotIn("intensity", step)
        self.assertTrue(any("removed intensity" in repair for repair in repairs))
        self.assertTrue(any("was not an explicit supported value" in warning for warning in warnings))

    def test_step_count_mismatch_skips_positional_target_sanitizing(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Интервалы
**** ШАГ ****
Тип: работа
Дистанция: 400 м
**** ШАГ ****
Тип: восстановление
Дистанция: 200 м
"""
        data = self._workout({"type": "dist_pace", "km": 0.4, "pace_fast": "4:50", "pace_slow": "5:00"})

        repairs, warnings = sanitize_marked_source_targets(source, data)

        self.assertFalse(repairs)
        self.assertTrue(any("step markers" in warning for warning in warnings))
        self.assertEqual(data["workouts"][0]["steps"][0]["type"], "dist_pace")

    def test_marked_structure_accepts_repeat_after_its_body(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Интервалы
**** ШАГ ****
Тип: разминка
Дистанция: 2 км
**** ПОВТОР: 4 РАЗ ****
**** ШАГ ****
Тип: работа
Дистанция: 800 м
**** ШАГ ****
Тип: восстановление
Длительность: 120 сек
**** КОНЕЦ ПОВТОРА ****
**** ШАГ ****
Тип: заминка
Дистанция: 1 км
"""
        data = {"workouts": [{"steps": [
            {"type": "dist_open", "km": 2},
            {"type": "dist_open", "km": 0.8},
            {"type": "time_step", "seconds": 120},
            {"type": "repeat", "back_to_offset": 1, "count": 4},
            {"type": "dist_open", "km": 1},
        ]}]}

        self.assertEqual(validate_marked_source_structure(source, data), [])

    def test_model_can_omit_repeat_and_application_compiles_exact_marker(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Интервалы
**** ШАГ ****
Тип: разминка
Дистанция: 2 км
**** ПОВТОР: 4 РАЗ ****
**** ШАГ ****
Тип: работа
Дистанция: 800 м
**** ШАГ ****
Тип: восстановление
Длительность: 120 сек
**** КОНЕЦ ПОВТОРА ****
**** ШАГ ****
Тип: заминка
Дистанция: 1 км
"""
        data = {"workouts": [{"steps": [
            {"type": "dist_open", "km": 2},
            {"type": "repeat", "back_to_offset": 0, "count": 99, "steps": [
                {"type": "dist_open", "km": 0.8},
                {"type": "time_step", "seconds": 120},
            ]},
            {"type": "dist_open", "km": 1},
        ]}]}

        self.assertEqual(validate_marked_source_model_steps(source, data), [])
        repairs, warnings = compile_marked_source_repeats(source, data)

        self.assertEqual(warnings, [])
        self.assertTrue(repairs)
        self.assertEqual(data["workouts"][0]["steps"][3], {
            "type": "repeat", "back_to_offset": 1, "count": 4,
        })
        self.assertEqual(validate_marked_source_structure(source, data), [])

    def test_repeat_compiler_does_not_guess_when_model_loses_a_step(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Интервалы
**** ПОВТОР: 6 РАЗ ****
**** ШАГ ****
Тип: работа
Дистанция: 400 м
**** ШАГ ****
Тип: восстановление
Дистанция: 200 м
**** КОНЕЦ ПОВТОРА ****
"""
        data = {"workouts": [{"steps": [{"type": "dist_open", "km": 0.4}]}]}

        repairs, warnings = compile_marked_source_repeats(source, data)

        self.assertEqual(repairs, [])
        self.assertTrue(any("source has 2 steps but YAML has 1" in warning for warning in warnings))
        self.assertEqual(len(data["workouts"][0]["steps"]), 1)

    def test_marked_structure_rejects_repeat_before_body_or_wrong_count(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Интервалы
**** ПОВТОР: 4 РАЗ ****
**** ШАГ ****
Тип: работа
Дистанция: 800 м
**** ШАГ ****
Тип: восстановление
Длительность: 120 сек
**** КОНЕЦ ПОВТОРА ****
"""
        data = {"workouts": [{"steps": [
            {"type": "repeat", "back_to_offset": 0, "count": 3},
            {"type": "dist_open", "km": 0.8},
            {"type": "time_step", "seconds": 120},
        ]}]}

        issues = validate_marked_source_structure(source, data)

        self.assertEqual(len(issues), 1)
        self.assertIn("preserve every step", issues[0])


if __name__ == "__main__":
    unittest.main()
