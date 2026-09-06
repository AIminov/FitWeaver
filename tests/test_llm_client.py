import unittest

import yaml

from garmin_fit.llm.client import GeneratedYamlResult, SourceWorkoutFact, UnifiedLLMClient


class TestUnifiedLLMClient(unittest.TestCase):
    def test_rejects_non_positive_request_timeout(self):
        with self.assertRaises(ValueError):
            UnifiedLLMClient(
                model="dummy",
                base_url="http://localhost:1234/v1",
                api_type="openai",
                request_timeout_sec=0,
            )

    def test_messages_to_completion_prompt_keeps_roles_and_output_rule(self):
        prompt = UnifiedLLMClient._messages_to_completion_prompt(
            [
                {"role": "system", "content": "System instructions"},
                {"role": "user", "content": "Plan text"},
            ]
        )

        self.assertIn("SYSTEM:\nSystem instructions", prompt)
        self.assertIn("USER:\nPlan text", prompt)
        self.assertIn("Start exactly with workouts:", prompt)
        self.assertTrue(prompt.endswith("ASSISTANT:\nworkouts:\n"))

    def test_reasoning_only_chat_response_needs_fallback(self):
        self.assertTrue(
            UnifiedLLMClient._openai_chat_response_needs_fallback(
                "Thinking Process:\n\n1. Analyze the request"
            )
        )
        self.assertFalse(
            UnifiedLLMClient._openai_chat_response_needs_fallback(
                "workouts:\n  - filename: W10_03-03_Tue_Easy_8km\n    steps: [{type: dist_open, km: 8}]"
            )
        )
        self.assertFalse(
            UnifiedLLMClient._openai_chat_response_needs_fallback(
                "```yaml\nworkouts:\n  - filename: W10_03-03_Tue_Easy_8km\n    steps: [{type: dist_open, km: 8}]\n```"
            )
        )

    def test_sanitize_yaml_candidate_cuts_second_workouts_root(self):
        sanitized = UnifiedLLMClient._sanitize_yaml_candidate(
            "workouts:\n"
            "  - filename: W10_03-03_Tue_Easy_8km\n"
            "    name: W10_03-03_Tue_Easy_8km\n"
            "workouts:\n"
            "  - filename: W10_03-04_Wed_Easy_5km\n"
        )

        self.assertEqual(sanitized.count("workouts:"), 1)
        self.assertIn("W10_03-03_Tue_Easy_8km", sanitized)
        self.assertNotIn("W10_03-04_Wed_Easy_5km", sanitized)

    def test_sanitize_yaml_candidate_cuts_reasoning_suffix(self):
        sanitized = UnifiedLLMClient._sanitize_yaml_candidate(
            "workouts:\n"
            "  - filename: W10_03-03_Tue_Easy_8km\n"
            "    name: W10_03-03_Tue_Easy_8km\n"
            "    desc: \"Easy\"\n"
            "\n        1.  **Analyze the Request:**\n"
            "More reasoning"
        )

        self.assertIn("W10_03-03_Tue_Easy_8km", sanitized)
        self.assertNotIn("Analyze the Request", sanitized)

    def test_sanitize_yaml_candidate_cuts_qwen_reasoning_suffix(self):
        sanitized = UnifiedLLMClient._sanitize_yaml_candidate(
            "workouts:\n"
            "  - filename: W01_08-24_Mon_Easy_6_3km\n"
            "    name: Easy run\n"
            "    steps: []\n"
            "\nI need to parse the user's input ...\n"
            "The user input is:\n"
        )

        self.assertIn("W01_08-24_Mon_Easy_6_3km", sanitized)
        self.assertNotIn("I need to parse", sanitized)

    def test_sanitize_yaml_candidate_cuts_think_suffix(self):
        sanitized = UnifiedLLMClient._sanitize_yaml_candidate(
            "workouts:\n"
            "  - filename: W01_05-01_Fri_Long_20km\n"
            "    name: Long run\n"
            "    steps: []\n"
            "\n<think>\nThe model started reasoning after YAML."
        )

        self.assertIn("W01_05-01_Fri_Long_20km", sanitized)
        self.assertNotIn("<think>", sanitized)

    def test_segment_header_info_accepts_weekday_and_title(self):
        info = UnifiedLLMClient._extract_segment_header_info(
            "01.05.2026 (\u0427\u0442) \u2014 \u0414\u043b\u0438\u043d\u043d\u044b\u0439 \u0431\u0435\u0433\n20 \u043a\u043c"
        )
        self.assertEqual(info["weekday"], "Thu")
        self.assertEqual((info["day"], info["month"]), (1, 5))

        info = UnifiedLLMClient._extract_segment_header_info(
            "24.08.2026 \u041f\u043e\u043d\u0435\u0434\u0435\u043b\u044c\u043d\u0438\u043a\n6 \u043a\u043c"
        )
        self.assertEqual(info["weekday"], "Mon")

        info = UnifiedLLMClient._extract_segment_header_info(
            "  ### 01.09.2026, \u0432торник \u2014 \u043b\u0451\u0433\u043a\u0438\u0439 \u0431\u0435\u0433\n5 \u043a\u043c"
        )
        self.assertEqual(info["weekday"], "Tue")

    def test_sanitize_yaml_candidate_fixes_common_completions_artifacts(self):
        candidate = (
            "- filename: W01_03-04_Wed_Intervals_Hills\n"
            "  - desc: \"Hill sprints\"\n"
            "  steps:\n"
            "    - type: open_step\n"
            "You are an expert Russian-speaking running coach AI"
        )

        sanitized = UnifiedLLMClient._sanitize_yaml_candidate(candidate)

        self.assertTrue(sanitized.startswith("workouts:\n  - filename:"))
        self.assertIn('\n    desc: "Hill sprints"', sanitized)
        self.assertNotIn("You are an expert", sanitized)
        loaded = yaml.safe_load(sanitized)
        self.assertEqual(
            loaded["workouts"][0]["desc"],
            "Hill sprints",
        )

    def test_auto_mode_falls_back_to_completions(self):
        client = UnifiedLLMClient(
            model="dummy",
            base_url="http://localhost:1234/v1",
            api_type="openai",
            openai_mode="auto",
        )
        calls: list[str] = []

        def fake_chat(messages, timeout):
            calls.append("chat")
            return "Thinking Process:\n\n1. Analyze the request"

        def fake_completions(prompt, timeout):
            calls.append("completions")
            return "workouts:\n  - filename: W10_03-03_Tue_Easy_8km\n    steps: [{type: dist_open, km: 8}]"

        client._call_openai_chat = fake_chat
        client._call_openai_completion = fake_completions

        content = client._call_openai(
            [{"role": "user", "content": "Plan text"}],
            timeout=30,
        )

        self.assertEqual(calls, ["chat", "completions"])
        self.assertIn("workouts:", content)

    def test_chat_mode_does_not_fallback(self):
        client = UnifiedLLMClient(
            model="dummy",
            base_url="http://localhost:1234/v1",
            api_type="openai",
            openai_mode="chat",
        )
        calls: list[str] = []

        def fake_chat(messages, timeout):
            calls.append("chat")
            return "Thinking Process:\n\n1. Analyze the request"

        def fake_completions(prompt, timeout):
            calls.append("completions")
            return "workouts: []"

        client._call_openai_chat = fake_chat
        client._call_openai_completion = fake_completions

        content = client._call_openai(
            [{"role": "user", "content": "Plan text"}],
            timeout=30,
        )

        self.assertEqual(calls, ["chat"])
        self.assertTrue(content.startswith("Thinking Process:"))

    def test_apply_expected_workout_count_check_adds_error(self):
        result = UnifiedLLMClient._prepare_yaml_candidate(
            "workouts:\n"
            "  - filename: W10_03-03_Tue_Easy_8km\n"
            "    name: W10_03-03_Tue_Easy_8km\n"
            "    desc: \"Easy\"\n"
            "    type_code: easy\n"
            "    distance_km: 8.0\n"
            "    estimated_duration_min: 50\n"
            "    steps:\n"
            "      - type: dist_open\n"
            "        km: 8.0\n",
            analysis_repairs=[],
            analysis_ambiguities=[],
            expected_workout_count=2,
            repair_plan_data=lambda data: (data, []),
            validate_plan_data_detailed=lambda data, enforce_filename_name_match=True: ([], []),
            group_issues_by_category=lambda errors: {},
        )

        self.assertIn(
            "expected 2 workouts from source text, got 1",
            result.validation_errors,
        )

    def test_missing_repeat_is_rejected_without_modifying_steps(self):
        workout = {"steps": [
            {"type": "dist_open", "km": 0.8, "intensity": "active"},
            {"type": "dist_open", "km": 0.4, "intensity": "recovery"},
            {"type": "dist_open", "km": 2, "intensity": "cooldown"},
        ]}
        fact = SourceWorkoutFact(interval_count=6, interval_rep_km=0.8)
        issues = UnifiedLLMClient._detect_suspicious_workout_against_fact(workout, fact)
        self.assertIn("missing repeat count 6", issues)
        self.assertEqual(len(workout["steps"]), 3)

    def test_extract_segment_header_info_parses_date_and_weekday(self):
        info = UnifiedLLMClient._extract_segment_header_info("12.03 (Thu)\nIntervals\n")

        self.assertIsNotNone(info)
        self.assertEqual(info["month"], 3)
        self.assertEqual(info["day"], 12)
        self.assertEqual(info["week"], 11)
        self.assertEqual(info["weekday"], "Thu")

    def test_align_workout_identifier_with_source_header_rewrites_date_prefix(self):
        workout = {
            "filename": "W09_03-03_Tue_Easy_6km",
            "name": "W09_03-03_Tue_Easy_6km",
        }

        UnifiedLLMClient._align_workout_identifier_with_source_header(
            workout,
            month=3,
            day=10,
            week=11,
            weekday="Tue",
        )

        self.assertEqual(workout["filename"], "W11_03-10_Tue_Easy_6km")
        self.assertEqual(workout["name"], "W11_03-10_Tue_Easy_6km")

    def test_extract_single_workout_fact_parses_intervals_and_hr(self):
        fact = UnifiedLLMClient._extract_single_workout_fact(
            "12.03 (Thu)\nIntervals\n4x800 m, rest 400 m jog\nПульс до 150\n"
        )

        self.assertIsNotNone(fact)
        self.assertEqual(fact.interval_count, 4)
        self.assertAlmostEqual(fact.interval_rep_km, 0.8)
        self.assertEqual(fact.hr_cap, 150)

    def test_detect_suspicious_workout_against_fact_flags_distance_mismatch(self):
        fact = UnifiedLLMClient._extract_single_workout_fact(
            "10.03 (Tue)\nЛегкий кросс\n6 км\nПульс до 140\n"
        )
        workout = {
            "filename": "W10_03-10_Tue_Easy_9km",
            "name": "W10_03-10_Tue_Easy_9km",
            "type_code": "easy",
            "distance_km": 9.0,
            "steps": [{"type": "dist_hr", "km": 9.0, "hr_high": 140}],
        }

        issues = UnifiedLLMClient._detect_suspicious_workout_against_fact(workout, fact)
        self.assertTrue(any("distance mismatch" in item for item in issues))

    def test_apply_source_fact_consistency_checks_adds_error_on_mismatch(self):
        fact = UnifiedLLMClient._extract_single_workout_fact(
            "10.03 (Tue)\nЛегкий кросс\n6 км\n"
        )
        result = GeneratedYamlResult(
            data={
                "workouts": [
                    {
                        "filename": "W10_03-10_Tue_Easy_9km",
                        "name": "W10_03-10_Tue_Easy_9km",
                        "type_code": "easy",
                        "distance_km": 9.0,
                        "steps": [{"type": "dist_open", "km": 9.0}],
                    }
                ]
            }
        )

        UnifiedLLMClient._apply_source_fact_consistency_checks(result, [fact])
        self.assertTrue(any("source facts mismatch" in msg for msg in result.validation_errors))

    def test_source_fact_mismatch_remains_blocking_after_consistency_check(self):
        fact = UnifiedLLMClient._extract_single_workout_fact(
            "10.03 (Tue)\nЛегкий кросс\n6 км\n"
        )
        result = GeneratedYamlResult(
            data={
                "workouts": [
                    {
                        "filename": "W10_03-10_Tue_Easy_9km",
                        "name": "W10_03-10_Tue_Easy_9km",
                        "type_code": "easy",
                        "distance_km": 9.0,
                        "steps": [{"type": "dist_open", "km": 9.0}],
                    }
                ]
            }
        )

        UnifiedLLMClient._apply_source_fact_consistency_checks(result, [fact])

        self.assertTrue(result.validation_errors)
        self.assertIn("source_fact_mismatch", result.error_categories)

