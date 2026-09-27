"""docs/PLAN_WRITING_GUIDE.md promises its examples parse without an LLM: keep it true."""

import re
import unittest
from pathlib import Path

from garmin_fit.free_text_rules import parse_workout_with_rules
from garmin_fit.marked_plan import compile_marked_text, is_marked_plan
from garmin_fit.plan_processing import normalize_source_text

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "PLAN_WRITING_GUIDE.md"


class PlanWritingGuideTests(unittest.TestCase):
    def test_every_example_parses_without_llm(self):
        blocks = re.findall(r"```text\n(.*?)```", GUIDE.read_text(encoding="utf-8"), re.S)
        self.assertGreaterEqual(len(blocks), 10)
        for block in blocks:
            if is_marked_plan(block):
                compiled = compile_marked_text(block)
                self.assertIsNotNone(compiled.data, block)
                continue
            analysis = normalize_source_text(block)
            for workout_text in analysis.workout_blocks or [analysis.text]:
                with self.subTest(workout=workout_text.splitlines()[0]):
                    self.assertIsNotNone(parse_workout_with_rules(workout_text), workout_text)

    def test_forms_the_guide_sends_to_the_llm(self):
        for text in (
            "Лёгкий бег 10 км по самочувствию",
            "Лёгкий бег 40 минут в разговорном темпе",
            "Разминка 2 км, 3 серии по 4x400 м 4:00-4:10, заминка 2 км",
            "Разминка километр, потом 5 км 5:00-5:10",
            "Лёгкий бег 8 км, пульс Z2",
            "Лёгкий бег 8 км, пульс 150",
            "Лёгкий бег 8 км (не выше 140)",
            "5 км 4:50-5:00, разминка 2 км, заминка 1 км",
            "10р + 5 км 4:50-5:00 + 10з",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_workout_with_rules(text))


if __name__ == "__main__":
    unittest.main()
