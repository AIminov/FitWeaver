import unittest
from unittest.mock import patch

import yaml

from garmin_fit.llm.client import UnifiedLLMClient
from garmin_fit.llm.compact_plan import CompactFormatError, compact_to_yaml


class CompactPlanTests(unittest.TestCase):
    def test_compiles_nested_repeats_and_targets_without_model_offsets(self):
        response = """W|14.04.2026|Intervals
S|warmup|2km|hr:до 140
R|2
R|4
S|active|400m|pace:4:00-4:10
S|recovery|200m|-
E
S|recovery|3min|-
E
S|cooldown|1km|-
"""
        text, warnings = compact_to_yaml(response)
        steps = yaml.safe_load(text)["workouts"][0]["steps"]
        self.assertEqual(warnings, [])
        self.assertEqual((steps[0]["hr_low"], steps[0]["hr_high"]), (60, 140))
        self.assertEqual(steps[3], {"type": "repeat", "back_to_offset": 1, "count": 4})
        self.assertEqual(steps[5], {"type": "repeat", "back_to_offset": 1, "count": 2})

    def test_incomplete_or_unknown_lines_are_rejected(self):
        for response in (
            "W|-|Run\nR|4\nS|active|400m|-\n",
            "W|-|Run\nS|active|400m|hr:150\n",
            "W|-|Run\nS|active|400m|pace:5:99\n",
            "W|-|Run\nS|active|400m|-\nWHAT\n",
        ):
            with self.subTest(response=response), self.assertRaises(CompactFormatError):
                compact_to_yaml(response)

    def test_client_compiles_model_lines_to_yaml(self):
        client = UnifiedLLMClient(
            model="local", base_url="http://localhost:11434", output_format="compact",
        )
        with patch.object(client, "_call_llm", return_value="W|-|Easy\nS|active|5km|-\n"):
            result = client.generate_yaml_draft("Бег 5 км", max_retries=1)
        self.assertEqual(result.validation_errors, [])
        self.assertEqual(result.data["workouts"][0]["steps"][0]["km"], 5.0)


if __name__ == "__main__":
    unittest.main()
