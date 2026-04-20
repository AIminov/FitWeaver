import unittest

from garmin_fit.llm.prompt import SYSTEM_PROMPT, create_system_prompt, load_llm_contract


class TestLlmPrompt(unittest.TestCase):
    def test_load_llm_contract_contains_expected_constraints(self):
        contract = load_llm_contract()

        self.assertEqual(contract["output"]["root_key"], "workouts")
        self.assertIn("cooldown", contract["allowed_intensity"])
        self.assertIn("dist_hr", contract["step_types"])
        self.assertIn("repeat", contract["step_types"])

    def test_create_system_prompt_uses_strict_contract_language(self):
        prompt = create_system_prompt(
            include_text_variations=False,
            source_text="4.03 (ср)\nускорение в гору 40 м\nповторить 5 раз\nВсего: 2 серии",
        )

        self.assertIn("workout_keys=filename,name,desc,type_code,distance_km,estimated_duration_min,steps", prompt)
        self.assertIn("forbid_extra_workout_keys=plan,mapped_to,date,notes", prompt)
        self.assertIn("repeat: back_to_offset=0-based index of first repeating step", prompt)
        self.assertIn('single upper HR cap only (e.g. "до 130", "HR <= 130")->use hr_low=80 and hr_high=cap', prompt)
        self.assertIn("EXAMPLE hills_series", prompt)
        self.assertIn("W09_03-04_Wed_Intervals_Hills_2x5x40m", prompt)

    def test_system_prompt_is_contract_first(self):
        self.assertIn("STRICT YAML CONTRACT", SYSTEM_PROMPT)
        self.assertIn("STEP SCHEMA", SYSTEM_PROMPT)

    def test_targeted_prompt_is_more_compact_than_generic_prompt(self):
        generic_prompt = create_system_prompt(include_text_variations=False, source_text=None)
        targeted_prompt = create_system_prompt(
            include_text_variations=False,
            source_text="8.03 (вс)\nДлительный кросс\nПульс до 155\n16 км",
        )

        self.assertLess(len(targeted_prompt), len(generic_prompt))
        self.assertLess(len(targeted_prompt), 5600)
