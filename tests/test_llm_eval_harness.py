import json
import tempfile
import unittest
from pathlib import Path

from garmin_fit.llm.eval_harness import (
    _specified_distance_km,
    check_raw_candidate,
    compare_reports,
    extract_raw_response,
    run_suite,
    validate_source_markers,
)

VALID_SOURCE = """==== ТРЕНИРОВКА ==== без даты — Easy run
**** ШАГ ****
Тип: лёгкий бег
Дистанция: 1 км
"""

VALID_RESPONSE = """workouts:
  - filename: N01_Easy_run
    name: N01_Easy_run
    desc: Easy run
    type_code: easy
    distance_km: null
    estimated_duration_min: null
    steps:
      - type: dist_open
        km: 1
"""


class TestLlmEvalHarness(unittest.TestCase):
    def test_distance_diagnostic_expands_nested_repeats_without_guessing_time_distance(self):
        steps = [
            {"type": "dist_open", "km": 2.0},
            {"type": "dist_open", "km": 0.4},
            {"type": "dist_open", "km": 0.2},
            {"type": "repeat", "back_to_offset": 1, "count": 4},
            {"type": "time_step", "seconds": 180},
            {"type": "repeat", "back_to_offset": 1, "count": 3},
            {"type": "dist_open", "km": 1.0},
        ]
        self.assertEqual(_specified_distance_km(steps), 10.2)

    def test_source_preflight_reports_malformed_repeat_and_missing_measure(self):
        source = """==== ТРЕНИРОВКА ==== без даты — Intervals
**** ПОВТОР: 4 РАЗ ****
**** ШАГ ****
Тип: работа
**** ШАГ ****
Тип: восстановление
**** КОНЕЦ ПОВТОРА ****
**** КОНЕЦ ПОВТОРА ****
"""

        result = validate_source_markers(source)

        self.assertTrue(any("distance or duration" in issue for issue in result["needs_user_input"]))
        self.assertTrue(any("без открытого повтора" in issue for issue in result["errors"]))

    def test_raw_candidate_checks_schema_and_marked_structure(self):
        result = check_raw_candidate(VALID_RESPONSE, VALID_SOURCE)

        self.assertTrue(result["strict_raw_pass"])
        self.assertTrue(result["schema_valid"])
        self.assertTrue(result["structure_valid"])

    def test_extract_raw_response_supports_ollama_and_openai_shapes(self):
        self.assertEqual(
            extract_raw_response({"message": {"content": "ollama"}}),
            "ollama",
        )
        self.assertEqual(
            extract_raw_response({"choices": [{"text": "completion"}]}),
            "completion",
        )

    def test_offline_suite_writes_reproducible_artifacts_and_passes_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "source.txt").write_text(VALID_SOURCE, encoding="utf-8")
            (root / "raw.yaml").write_text(VALID_RESPONSE, encoding="utf-8")
            suite_path = root / "suite.yaml"
            suite_path.write_text(
                "suite: smoke\ncases:\n"
                "  - id: easy\n"
                "    input_path: source.txt\n"
                "    raw_response_path: raw.yaml\n"
                "    tags: [easy, marked]\n",
                encoding="utf-8",
            )

            report, run_dir = run_suite(
                suite_path,
                mode="offline",
                api="ollama",
                url="http://localhost:11434",
                model="unused",
                openai_mode="auto",
                retries=1,
                timeout_sec=30,
                trials=1,
                output_root=root / "artifacts",
            )

            self.assertEqual(report["strict_pass_count"], 1)
            self.assertEqual(report["strict_fail_count"], 0)
            self.assertTrue((run_dir / "manifest.json").is_file())
            self.assertTrue((run_dir / "results.json").is_file())
            self.assertTrue((run_dir / "summary.md").is_file())
            trace_events = [
                json.loads(line)
                for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("offline_response_loaded", [event["event"] for event in trace_events])

    def test_compare_reports_pairs_only_identical_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            row = {
                "case_id": "easy",
                "trial": 1,
                "source_sha256": "same-source",
                "strict_pass": True,
                "runtime": {"latency_sec": 12.0},
            }
            for filename, model, passed in (("a.json", "model-a", True), ("b.json", "model-b", False)):
                payload = {
                    "run_id": filename,
                    "model": model,
                    "results": [{**row, "strict_pass": passed}],
                }
                (root / filename).write_text(json.dumps(payload), encoding="utf-8")

            comparison, artifact = compare_reports(root / "a.json", root / "b.json", root / "out")

            self.assertEqual(comparison["first_wins"], 1)
            self.assertEqual(comparison["second_pass_count"], 0)
            self.assertTrue(artifact.with_suffix(".md").is_file())

            second = json.loads((root / "b.json").read_text(encoding="utf-8"))
            second["results"][0]["source_sha256"] = "different-source"
            (root / "b.json").write_text(json.dumps(second), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Source text differs"):
                compare_reports(root / "a.json", root / "b.json", root / "out")


if __name__ == "__main__":
    unittest.main()
