import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from garmin_fit.llm.client import GenerationCancelled, UnifiedLLMClient

PLAN = """Зоны: Z2 = 130-145

01.10 — Лёгкий бег 8 км
8 км в Z2

03.10 — Лёгкий бег 6 км
6 км в Z2
"""


def _workout_yaml(km: float) -> str:
    # Written the way models answer (indented sequence items).
    return "\n".join([
        "workouts:",
        "  - filename: Easy",
        "    name: Easy",
        "    desc: easy",
        "    steps:",
        "      - type: dist_hr",
        f"        km: {km}",
        "        hr_low: 130",
        "        hr_high: 145",
        "",
    ])


class _FakeStream:
    def __init__(self, chunks, on_iter=None):
        self.status_code = 200
        self._chunks = chunks
        self._on_iter = on_iter
        self.closed = False

    def iter_lines(self):
        for i, chunk in enumerate(self._chunks):
            if self._on_iter:
                self._on_iter(i)
            yield json.dumps(chunk).encode("utf-8")

    def close(self):
        self.closed = True


def _client(**kwargs):
    return UnifiedLLMClient(model="m", base_url="http://localhost:11434", api_type="ollama", **kwargs)


class OllamaStreamingTests(unittest.TestCase):
    def test_stream_is_assembled_with_metrics_and_keep_alive(self):
        chunks = [
            {"message": {"content": "work"}, "done": False},
            {"message": {"content": "outs: []"}, "done": False},
            {"message": {"content": ""}, "done": True, "eval_count": 2, "prompt_eval_count": 7},
        ]
        stream = _FakeStream(chunks)
        client = _client()
        with patch("requests.post", return_value=stream) as post:
            text = client._call_ollama([{"role": "user", "content": "x"}], timeout=5)

        self.assertEqual(text, "workouts: []")
        self.assertTrue(stream.closed)
        payload = post.call_args.kwargs["json"]
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["keep_alive"], "30m")
        self.assertEqual(client._last_call_metrics["eval_count"], 2)

    def test_cancel_during_stream_raises(self):
        client = _client()
        client.cancel_event = threading.Event()
        chunks = [{"message": {"content": "a"}, "done": False}] * 5

        def cancel_after_first(i):
            if i == 1:
                client.cancel_event.set()

        with patch("requests.post", return_value=_FakeStream(chunks, cancel_after_first)):
            with self.assertRaises(GenerationCancelled):
                client._call_ollama([{"role": "user", "content": "x"}], timeout=5)

    def test_warm_up_loads_model_with_keep_alive(self):
        class _Resp:
            status_code = 200

        with patch("requests.post", return_value=_Resp()) as post:
            self.assertTrue(_client().warm_up())
        self.assertTrue(post.call_args.args[0].endswith("/api/generate"))
        self.assertEqual(post.call_args.kwargs["json"], {"model": "m", "keep_alive": "30m"})

    def test_token_limit_rejects_even_parseable_partial_answer(self):
        chunks = [
            {"message": {"content": _workout_yaml(8.0)}, "done": False},
            {"message": {"content": ""}, "done": True, "done_reason": "length"},
        ]
        with patch("requests.post", return_value=_FakeStream(chunks)):
            result = _client().generate_yaml_draft("Лёгкий бег 8 км", max_retries=1)
        self.assertIsNone(result.yaml_text)
        self.assertIn("token limit", result.validation_errors[0])


class SegmentedGenerationTests(unittest.TestCase):
    def test_explicit_previous_day_reference_copies_workout_without_model(self):
        plan = (
            "29.09.2026 (Вт) — Лёгкий бег\n8 км в Z2\n\n"
            "01.10.2026 (Чт) — Повтор\nПовторить вторник\n"
        )
        client = _client()
        with patch.object(client, "_call_llm", return_value=_workout_yaml(8.0)) as call:
            result = client.generate_yaml_draft(plan, max_retries=1)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result.validation_errors, [])
        self.assertEqual(result.failed_segments, [])
        self.assertEqual(result.data["workouts"][0]["steps"], result.data["workouts"][1]["steps"])
        self.assertIn("09-29_Tue", result.data["workouts"][0]["filename"])
        self.assertIn("10-01_Thu", result.data["workouts"][1]["filename"])

    def test_missing_previous_day_reference_is_reported_without_hallucination(self):
        plan = "01.10.2026 (Чт) — Повтор\nПовторить вторник\n"
        client = _client()
        with patch.object(client, "_call_llm", side_effect=AssertionError("model called")):
            result = client.generate_yaml_draft(plan, max_retries=1)
        self.assertIsNone(result.yaml_text)
        self.assertEqual(len(result.failed_segments), 1)
        self.assertIn("0 matching", result.failed_segments[0]["error"])

    def test_undated_standalone_reference_requires_source_steps(self):
        client = _client()
        with patch.object(client, "_call_llm", side_effect=AssertionError("model called")):
            result = client.generate_yaml_draft("Повтори тренировку с четверга.", max_retries=1)
        self.assertIsNone(result.yaml_text)
        self.assertIn("укажите её шаги", result.validation_errors[0])

    def test_failed_workout_keeps_the_successful_ones(self):
        client = _client()
        responses = {"01.10": _workout_yaml(8.0), "03.10": "not yaml: ["}

        def fake_call(system_prompt, user_message):
            return next(v for k, v in responses.items() if k in user_message)

        with patch.object(client, "_call_llm", side_effect=fake_call):
            result = client.generate_yaml_draft(PLAN, max_retries=1)

        self.assertEqual(result.validation_errors, [])
        self.assertEqual(len(result.data["workouts"]), 1)
        self.assertEqual([item["index"] for item in result.failed_segments], [2])
        self.assertTrue(any("Workout 2" in w for w in result.warnings))

    def test_all_failed_is_an_error(self):
        client = _client()
        with patch.object(client, "_call_llm", return_value="not yaml: ["):
            result = client.generate_yaml_draft(PLAN, max_retries=1)
        self.assertIsNone(result.yaml_text)
        self.assertEqual(len(result.failed_segments), 2)
        self.assertTrue(result.validation_errors)

    def test_shared_plan_notes_reach_every_segment(self):
        client = _client()
        seen: list[str] = []

        def fake_call(system_prompt, user_message):
            seen.append(user_message)
            return _workout_yaml(8.0 if "01.10" in user_message else 6.0)

        with patch.object(client, "_call_llm", side_effect=fake_call):
            client.generate_yaml_draft(PLAN, max_retries=1)
        self.assertEqual(len(seen), 2)
        self.assertTrue(all("Z2 = 130-145" in message for message in seen))

    def test_segment_cache_skips_the_model_on_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _client(segment_cache_dir=Path(tmp))

            def fake_call(system_prompt, user_message):
                return _workout_yaml(8.0 if "01.10" in user_message else 6.0)

            with patch.object(client, "_call_llm", side_effect=fake_call) as first:
                first_result = client.generate_yaml_draft(PLAN, max_retries=1)
            self.assertEqual(first.call_count, 2)

            with patch.object(client, "_call_llm", side_effect=AssertionError("model called")):
                second_result = client.generate_yaml_draft(PLAN, max_retries=1)
            self.assertEqual(second_result.data, first_result.data)

    def test_progress_and_cancel_between_segments(self):
        client = _client()
        client.cancel_event = threading.Event()
        events: list[dict] = []

        def progress(info):
            events.append(info)
            if info.get("segment") == 2:
                client.cancel_event.set()

        client.progress_callback = progress
        with patch.object(client, "_call_llm", return_value=_workout_yaml(8.0)):
            with self.assertRaises(GenerationCancelled):
                client.generate_yaml_draft(PLAN, max_retries=1)
        self.assertEqual(events[0], {"stage": "segment", "segment": 1, "total": 2})


if __name__ == "__main__":
    unittest.main()
