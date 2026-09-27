import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import yaml

from garmin_fit import cli
from garmin_fit.build_from_plan import build_workout_steps
from garmin_fit.marked_plan import (
    compile_marked_text,
    is_marked_plan,
    parse_marked_plan,
    plan_to_yaml_data,
    render_marked_plan,
)
from garmin_fit.plan_domain import plan_from_data
from garmin_fit.plan_service import build_plan_draft

THRESHOLD = """\
==== ТРЕНИРОВКА ==== 25.09.2026 (пятница) — Пороговая тренировка
Общая дистанция: 9 км
Цель тренировки: порог

**** ШАГ ****
Тип: разминка
Дистанция: 2 км

**** ПОВТОР: 4 РАЗ ****
**** ШАГ ****
Тип: работа
Дистанция: 1.5 км
Пульс: 170–174 уд/мин

**** ШАГ ****
Тип: восстановление
Длительность: 2 мин
**** КОНЕЦ ПОВТОРА ****

**** ШАГ ****
Тип: заминка
Дистанция: 1 км
"""


def _workout(body: str, header: str = "==== ТРЕНИРОВКА ==== без даты — Тест") -> str:
    return f"{header}\n{body}"


class DetectionTests(unittest.TestCase):
    def test_step_marker_makes_text_marked(self):
        self.assertTrue(is_marked_plan(THRESHOLD))

    def test_free_text_and_header_only_text_are_not_marked(self):
        self.assertFalse(is_marked_plan("Пн: 10 км легко"))
        self.assertFalse(is_marked_plan("==== ТРЕНИРОВКА ==== 01.10 — Лёгкий\n10 км легко"))


class CompileTests(unittest.TestCase):
    def test_threshold_workout_compiles_with_repeat_after_body(self):
        result = compile_marked_text(THRESHOLD)

        self.assertEqual(result.errors, [])
        workout = result.data["workouts"][0]
        self.assertEqual(workout["filename"], "W39_09-25_Fri_Porogovaya_Trenirovka")
        self.assertEqual(workout["name"], workout["filename"])
        self.assertEqual(workout["distance_km"], 9.0)
        self.assertIn("Цель тренировки: порог", workout["desc"])
        self.assertEqual(workout["steps"], [
            {"type": "dist_open", "km": 2.0, "intensity": "warmup"},
            {"type": "dist_hr", "km": 1.5, "hr_low": 170, "hr_high": 174, "intensity": "active"},
            {"type": "time_step", "seconds": 120, "intensity": "recovery"},
            {"type": "repeat", "back_to_offset": 1, "count": 4},
            {"type": "dist_open", "km": 1.0, "intensity": "cooldown"},
        ])

    def test_nested_repeats_use_yaml_index_of_first_body_step(self):
        text = _workout("""\
**** ПОВТОР: 3 РАЗ ****
**** ПОВТОР: 2 РАЗ ****
**** ШАГ ****
Длительность: 60 сек
**** ШАГ ****
Длительность: 30 сек
**** КОНЕЦ ПОВТОРА ****
**** ШАГ ****
Длительность: 2 мин
**** КОНЕЦ ПОВТОРА ****
""")
        steps = compile_marked_text(text).data["workouts"][0]["steps"]

        self.assertEqual(steps[2], {"type": "repeat", "back_to_offset": 0, "count": 2})
        self.assertEqual(steps[4], {"type": "repeat", "back_to_offset": 0, "count": 3})

    def test_repeat_of_one_emits_body_only(self):
        text = _workout("**** ПОВТОР: 1 РАЗ ****\n**** ШАГ ****\nДистанция: 1 км\n**** КОНЕЦ ПОВТОРА ****\n")
        steps = compile_marked_text(text).data["workouts"][0]["steps"]
        self.assertEqual(steps, [{"type": "dist_open", "km": 1.0}])

    def test_sbu_drills_are_parsed_and_fit_repeat_accounts_for_expansion(self):
        text = _workout("""\
**** ШАГ ****
Тип: разминка
Дистанция: 2 км
**** ШАГ ****
Тип: СБУ
Упражнения: высокое бедро — 2×20 сек; многоскоки — 2×20 сек
**** ПОВТОР: 6 РАЗ ****
**** ШАГ ****
Тип: ускорение
Длительность: 30 сек
**** ШАГ ****
Тип: восстановление
Длительность: 45 сек
**** КОНЕЦ ПОВТОРА ****
""")
        data = compile_marked_text(text).data
        steps = data["workouts"][0]["steps"]
        self.assertEqual(steps[1]["drills"], [
            {"name": "высокое бедро", "seconds": 20, "reps": 2},
            {"name": "многоскоки", "seconds": 20, "reps": 2},
        ])
        self.assertEqual(steps[4], {"type": "repeat", "back_to_offset": 2, "count": 6})

        fit_steps = build_workout_steps(plan_from_data(data).workouts[0])
        # warmup(1) + 2 drills × 2 reps × 2 FIT steps (8) + 2 body steps + repeat
        self.assertEqual(len(fit_steps), 12)
        self.assertEqual(fit_steps[-1].duration_value, 9)
        self.assertEqual(fit_steps[-1].target_value, 6)

    def test_sbu_without_exercises_uses_default_block_with_warning(self):
        result = compile_marked_text(_workout("**** ШАГ ****\nТип: СБУ\n"))
        self.assertEqual(result.data["workouts"][0]["steps"], [{"type": "sbu_block"}])
        self.assertTrue(any("стандартный набор" in w for w in result.warnings))

    def test_hr_zone_resolved_from_profile(self):
        text = _workout("**** ШАГ ****\nДистанция: 5 км\nПульс: Z2\n")
        result = compile_marked_text(text, hr_zones={"zone2": {"low": 120, "high": 140}})
        step = result.data["workouts"][0]["steps"][0]
        self.assertEqual((step["type"], step["hr_low"], step["hr_high"]), ("dist_hr", 120, 140))

    def test_unconfigured_zone_drops_target_with_warning(self):
        result = compile_marked_text(_workout("**** ШАГ ****\nДистанция: 5 км\nПульс: зона 2\n"))
        self.assertEqual(result.data["workouts"][0]["steps"][0], {"type": "dist_open", "km": 5.0})
        self.assertTrue(any("Z2" in w for w in result.warnings))

    def test_hr_cap_is_encoded_with_60_floor(self):
        for phrase in ("до 150 уд/мин", "не выше 150", "<= 150"):
            result = compile_marked_text(_workout(f"**** ШАГ ****\nДлительность: 30 мин\nПульс: {phrase}\n"))
            self.assertEqual(
                result.data["workouts"][0]["steps"][0],
                {"type": "time_hr", "seconds": 1800, "hr_low": 60, "hr_high": 150},
                phrase,
            )

    def test_lower_only_hr_bound_is_not_guessed(self):
        result = compile_marked_text(_workout("**** ШАГ ****\nДлительность: 30 мин\nПульс: от 130\n"))
        self.assertEqual(result.data["workouts"][0]["steps"][0], {"type": "time_step", "seconds": 1800})
        self.assertTrue(any("полный диапазон" in w for w in result.warnings))

    def test_single_pace_widened_and_range_ordered(self):
        text = _workout("""\
**** ШАГ ****
Дистанция: 1 км
Темп: 4:30 мин/км
**** ШАГ ****
Длительность: 1 ч 30 мин
Темп: 5:20–5:05 мин/км
""")
        steps = compile_marked_text(text).data["workouts"][0]["steps"]
        self.assertEqual((steps[0]["pace_fast"], steps[0]["pace_slow"]), ("4:20", "4:40"))
        self.assertEqual(steps[1]["type"], "time_pace")
        self.assertEqual(steps[1]["seconds"], 5400)
        self.assertEqual((steps[1]["pace_fast"], steps[1]["pace_slow"]), ("5:05", "5:20"))

    def test_cadence_target(self):
        steps = compile_marked_text(
            _workout("**** ШАГ ****\nДистанция: 400 метров\nЧастота шагов: 175-185\n")
        ).data["workouts"][0]["steps"]
        self.assertEqual(steps[0], {"type": "dist_cadence", "km": 0.4, "cad_low": 175, "cad_high": 185})

    def test_step_without_measure_becomes_open_step_and_drops_target(self):
        result = compile_marked_text(_workout("**** ШАГ ****\nТип: восстановление\nПульс: 120-130\n"))
        self.assertEqual(result.data["workouts"][0]["steps"], [{"type": "open_step", "intensity": "recovery"}])
        self.assertTrue(any("кнопкой круга" in w for w in result.warnings))

    def test_approximate_value_warns(self):
        result = compile_marked_text(_workout("**** ШАГ ****\nДистанция: около 200 м\n"))
        self.assertEqual(result.data["workouts"][0]["steps"], [{"type": "dist_open", "km": 0.2}])
        self.assertTrue(any("приблизительное" in w for w in result.warnings))

    def test_duplicate_titles_get_unique_identifiers(self):
        body = "**** ШАГ ****\nДистанция: 5 км\n"
        data = compile_marked_text(_workout(body) + "\n" + _workout(body)).data
        self.assertEqual([w["filename"] for w in data["workouts"]], ["Test", "Test_2"])


class HeaderTests(unittest.TestCase):
    def test_missing_year_uses_default_with_warning(self):
        plan = parse_marked_plan(
            _workout("**** ШАГ ****\nДистанция: 5 км\n", "==== ТРЕНИРОВКА ==== 03.10 — Лёгкий"),
            default_year=2026,
        )
        self.assertEqual(plan.workouts[0].date, date(2026, 10, 3))
        self.assertTrue(any("год" in str(w) for w in plan.warnings))

    def test_weekday_mismatch_warns(self):
        plan = parse_marked_plan(
            _workout("**** ШАГ ****\nДистанция: 5 км\n", "==== ТРЕНИРОВКА ==== 25.09.2026 (понедельник) — Бег")
        )
        self.assertTrue(any("пятница" in str(w) for w in plan.warnings))

    def test_weekday_after_comma_is_accepted(self):
        plan = parse_marked_plan(
            _workout("**** ШАГ ****\nДистанция: 5 км\n", "==== ТРЕНИРОВКА ==== 25.09.2026, пятница — Бег")
        )
        self.assertEqual(plan.workouts[0].date, date(2026, 9, 25))
        self.assertEqual(plan.workouts[0].title, "Бег")

    def test_invalid_date_is_an_error(self):
        plan = parse_marked_plan(
            _workout("**** ШАГ ****\nДистанция: 5 км\n", "==== ТРЕНИРОВКА ==== 30.02.2026 — Бег")
        )
        self.assertTrue(any("некорректная дата" in str(e) for e in plan.errors))


class StructureErrorTests(unittest.TestCase):
    def _errors(self, text: str) -> list[str]:
        return compile_marked_text(text).errors

    def test_unclosed_repeat(self):
        errors = self._errors(_workout("**** ПОВТОР: 3 РАЗ ****\n**** ШАГ ****\nДистанция: 1 км\n"))
        self.assertTrue(any("не закрыт" in e for e in errors))

    def test_end_without_repeat(self):
        errors = self._errors(_workout("**** ШАГ ****\nДистанция: 1 км\n**** КОНЕЦ ПОВТОРА ****\n"))
        self.assertTrue(any("без открытого" in e for e in errors))

    def test_repeat_without_count(self):
        errors = self._errors(_workout("**** ПОВТОР ****\n**** ШАГ ****\nДистанция: 1 км\n**** КОНЕЦ ПОВТОРА ****\n"))
        self.assertTrue(any("число повторов" in e for e in errors))

    def test_unreadable_distance_reports_line(self):
        errors = self._errors(_workout("**** ШАГ ****\nДистанция: много\n"))
        self.assertEqual(errors, ["строка 3: не удалось прочитать дистанцию «много» (нужно число и м/км)"])

    def test_workout_without_steps(self):
        errors = self._errors("==== ТРЕНИРОВКА ==== без даты — A\n10 км легко\n"
                              "==== ТРЕНИРОВКА ==== без даты — B\n**** ШАГ ****\nДистанция: 1 км\n")
        self.assertTrue(any("нет ни одного шага" in e for e in errors))

    def test_step_before_header(self):
        errors = self._errors("**** ШАГ ****\nДистанция: 1 км\n")
        self.assertTrue(any("до первого заголовка" in e for e in errors))


class RenderTests(unittest.TestCase):
    def test_render_round_trip_preserves_compiled_plan(self):
        plan = parse_marked_plan(THRESHOLD)
        rendered = render_marked_plan(plan)
        self.assertIn("==== ТРЕНИРОВКА ==== 25.09.2026 (пятница) — Пороговая тренировка", rendered)
        self.assertEqual(plan_to_yaml_data(parse_marked_plan(rendered)), plan_to_yaml_data(plan))


class YamlToMarkedTextTests(unittest.TestCase):
    def test_generated_yaml_renders_to_text_that_compiles_to_the_same_steps(self):
        from garmin_fit.marked_plan import plan_data_to_marked_text

        data = {"workouts": [{
            "filename": "W40_10-01_Thu_Sets", "name": "W40_10-01_Thu_Sets", "desc": "Sets. Hard",
            "distance_km": 10.0,
            "steps": [
                {"type": "dist_hr", "km": 2.0, "hr_low": 125, "hr_high": 140, "intensity": "warmup"},
                {"type": "sbu_block", "drills": [{"name": "A", "seconds": 20, "reps": 2}]},
                {"type": "dist_pace", "km": 0.4, "pace_fast": "3:50", "pace_slow": "4:00",
                 "intensity": "active"},
                {"type": "time_step", "seconds": 90, "intensity": "recovery"},
                {"type": "repeat", "back_to_offset": 2, "count": 4},
                {"type": "time_step", "seconds": 180, "intensity": "recovery"},
                {"type": "repeat", "back_to_offset": 2, "count": 3},
                {"type": "time_cadence", "seconds": 600, "cad_low": 170, "cad_high": 180,
                 "intensity": "cooldown"},
            ],
        }]}

        text = plan_data_to_marked_text(data)
        self.assertIn("**** ПОВТОР: 3 РАЗ ****", text)
        self.assertIn("Длительность: 1 мин 30 сек", text)
        self.assertIn("Дистанция: 400 м", text)

        recompiled = compile_marked_text(text)
        self.assertEqual(recompiled.errors, [])
        self.assertEqual(recompiled.data["workouts"][0]["steps"], data["workouts"][0]["steps"])
        self.assertEqual(recompiled.data["workouts"][0]["distance_km"], 10.0)


class IntegrationTests(unittest.TestCase):
    def test_plan_service_compiles_marked_text_without_calling_llm(self):
        llm = Mock()
        result = build_plan_draft(llm, THRESHOLD)

        llm.generate_yaml_draft.assert_not_called()
        self.assertEqual(result.validation_errors, [])
        self.assertEqual(yaml.safe_load(result.yaml_text), result.data)

    def test_plan_service_sends_free_text_to_llm(self):
        llm = Mock()
        build_plan_draft(llm, "Пн: 10 км легко", max_retries=2)
        llm.generate_yaml_draft.assert_called_once_with("Пн: 10 км легко", max_retries=2)

    def test_plan_service_reports_marked_errors(self):
        result = build_plan_draft(Mock(), _workout("**** ШАГ ****\nДистанция: много\n"))
        self.assertIsNone(result.yaml_text)
        self.assertTrue(result.validation_errors)

    def test_cli_parse_marked_writes_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "plan.txt"
            output = Path(tmp) / "out" / "plan.yaml"
            source.write_text(THRESHOLD, encoding="utf-8")

            self.assertEqual(cli.main(["parse-marked", str(source), "--output", str(output)]), 0)
            data = yaml.safe_load(output.read_text(encoding="utf-8"))
        self.assertEqual(data["workouts"][0]["filename"], "W39_09-25_Fri_Porogovaya_Trenirovka")

    def test_cli_to_marked_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "plan.txt"
            plan_yaml = Path(tmp) / "plan.yaml"
            text_out = Path(tmp) / "back.txt"
            source.write_text(THRESHOLD, encoding="utf-8")
            self.assertEqual(cli.main(["parse-marked", str(source), "--output", str(plan_yaml)]), 0)
            self.assertEqual(cli.main(["to-marked", str(plan_yaml), "--output", str(text_out)]), 0)
            original = yaml.safe_load(plan_yaml.read_text(encoding="utf-8"))["workouts"][0]["steps"]
            again = compile_marked_text(text_out.read_text(encoding="utf-8")).data["workouts"][0]["steps"]
        self.assertEqual(again, original)

    def test_cli_parse_marked_fails_on_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "plan.txt"
            source.write_text("**** ШАГ ****\n", encoding="utf-8")
            self.assertEqual(cli.main(["parse-marked", str(source)]), 1)

    def test_llm_request_cli_compiles_marked_text_without_a_model(self):
        from unittest.mock import patch

        from garmin_fit.llm import request_cli

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "plan.txt"
            output = Path(tmp) / "plan.yaml"
            source.write_text(THRESHOLD, encoding="utf-8")
            argv = ["request_cli", "--plan", str(source), "--output", str(output)]
            no_llm = patch.object(request_cli, "UnifiedLLMClient", side_effect=AssertionError("LLM used"))
            with patch("sys.argv", argv), no_llm:
                self.assertTrue(request_cli.main())
            data = yaml.safe_load(output.read_text(encoding="utf-8"))
        self.assertEqual(len(data["workouts"]), 1)


if __name__ == "__main__":
    unittest.main()
