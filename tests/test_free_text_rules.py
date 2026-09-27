import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from garmin_fit.free_text_rules import free_text_to_marked, parse_workout_with_rules
from garmin_fit.llm.client import UnifiedLLMClient
from garmin_fit.llm.golden import compare_to_canonical

GOLDEN = Path(__file__).resolve().parents[1] / "docs" / "golden_dataset" / "golden_examples_v1.yaml"

# Variants where the reference itself deviates from the text; the rules keep the stated facts.
KNOWN_REFERENCE_DEVIATIONS = {
    "strides_after_easy_6x100_v1": "reference drops the stated 100 m stride distance (open step)",
}

INTERVALS = """14.04.2026 (вт)
Интервалы 6x800м
Разминка: 2 км (5:45-6:00)
6x800м по 4:20-4:30, восстановление 400 м трусцой (5:30-6:00)
Заминка: 1 км (5:45-6:00)
Итого: ~10.2 км, 55 мин
"""


class FreeTextRulesTests(unittest.TestCase):
    def test_formal_interval_workout(self):
        workout = parse_workout_with_rules(INTERVALS)

        self.assertTrue(workout["filename"].startswith("W16_04-14_Tue_"))
        self.assertEqual(workout["steps"], [
            {"type": "dist_pace", "km": 2.0, "pace_fast": "5:45", "pace_slow": "6:00", "intensity": "warmup"},
            {"type": "dist_pace", "km": 0.8, "pace_fast": "4:20", "pace_slow": "4:30", "intensity": "active"},
            {"type": "dist_pace", "km": 0.4, "pace_fast": "5:30", "pace_slow": "6:00", "intensity": "recovery"},
            {"type": "repeat", "back_to_offset": 1, "count": 6},
            {"type": "dist_pace", "km": 1.0, "pace_fast": "5:45", "pace_slow": "6:00", "intensity": "cooldown"},
        ])
        self.assertEqual(workout["estimated_duration_min"], 55.0)

    def test_cycles_role_lines_and_sbu(self):
        text = """16.04.2026 (чт)
Фартлек
Разминка
2 км спокойно (пульс 130-145)
СБУ: High Knees 30с x2, Skipping 30с x2
5 циклов: 2 мин быстро (4:30-4:50) + 3 мин легко (5:45-6:00)
"""
        steps = parse_workout_with_rules(text)["steps"]
        self.assertEqual(steps[0]["intensity"], "warmup")
        self.assertEqual(steps[1]["drills"], [
            {"name": "High Knees", "seconds": 30, "reps": 2},
            {"name": "Skipping", "seconds": 30, "reps": 2},
        ])
        self.assertEqual(steps[2]["seconds"], 120)
        self.assertEqual(steps[3]["intensity"], "recovery")
        self.assertEqual(steps[4], {"type": "repeat", "back_to_offset": 2, "count": 5})

    def test_coach_shorthand(self):
        steps = parse_workout_with_rules(
            "14.04 вт: р2(5.45-6.00) + 6х800 4.20-4.30 отд 400 трусцой(5.30-6.00) + з1(5.45-6.00)"
        )["steps"]
        self.assertEqual([s.get("km") for s in steps], [2.0, 0.8, 0.4, None, 1.0])
        self.assertEqual(steps[1]["pace_fast"], "4:20")
        self.assertEqual(steps[3], {"type": "repeat", "back_to_offset": 1, "count": 6})

    def test_ambiguous_shorthand_is_left_to_the_llm(self):
        # "10р" may mean 10 minutes or 10 km of warmup.
        self.assertIsNone(free_text_to_marked("10р + 5 км (4:50-5:00) + 10з"))

    def test_hr_cap_becomes_60_to_cap(self):
        workout = parse_workout_with_rules("Лёгкий бег 8 км, пульс до 140")
        self.assertEqual(workout["steps"], [{"type": "dist_hr", "km": 8.0, "hr_low": 60, "hr_high": 140}])

    def test_unexplained_number_falls_back_to_llm(self):
        self.assertIsNone(free_text_to_marked("Разминка 2 км, потом 3 ускорения"))

    def test_unsupported_structure_falls_back_to_llm(self):
        self.assertIsNone(free_text_to_marked("3 серии по 4x400м, между сериями 3 минуты"))
        self.assertIsNone(free_text_to_marked("5 км по самочувствию"))

    def test_golden_dataset_precision_and_coverage(self):
        """Parsed workouts agree with the reference on every fact they state.

        The only tolerated difference is a missing target where the reference
        adds one the text does not give (e.g. a warmup pace copied from another
        line, or an upper HR cap turned into hr_low 80): these rules never
        invent values. Unclear or unsupported cases are never parsed.
        """
        data = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
        parsed_valid = 0
        for group in data["groups"]:
            for variant in group.get("variants", []):
                workout = parse_workout_with_rules(variant["text"])
                if group["status"] != "VALID":
                    self.assertIsNone(workout, variant["id"])
                    continue
                if workout is None:
                    continue
                parsed_valid += 1
                if variant["id"] in KNOWN_REFERENCE_DEVIATIONS:
                    continue
                problems = compare_to_canonical(
                    workout["steps"], group["canonical"]["workouts"][0]["steps"]
                )
                self.assertEqual(problems, [], variant["id"])
        self.assertGreaterEqual(parsed_valid, 26)


class RulesInClientTests(unittest.TestCase):
    def test_rule_parsed_workouts_skip_the_llm(self):
        plan = INTERVALS + "\n15.04.2026 (ср)\nТемповый бег\nРазминка 2 км (5:45-6:00)\nТемп 5 км по 4:50-5:00\n"
        client = UnifiedLLMClient(model="m", base_url="http://localhost:11434", api_type="ollama")
        client.use_rules = True
        with patch.object(client, "_call_llm", side_effect=AssertionError("LLM called")):
            result = client.generate_yaml_draft(plan, max_retries=1)
        self.assertEqual(result.validation_errors, [])
        self.assertEqual(len(result.data["workouts"]), 2)
        self.assertTrue(any("deterministic rules" in r for r in result.repairs))

    def test_rules_are_off_by_default_for_llm_evaluation(self):
        client = UnifiedLLMClient(model="m", base_url="http://localhost:11434", api_type="ollama")
        with patch.object(client, "_call_llm", return_value=None) as call:
            client.generate_yaml_draft(INTERVALS, max_retries=1)
        self.assertTrue(call.called)


if __name__ == "__main__":
    unittest.main()
