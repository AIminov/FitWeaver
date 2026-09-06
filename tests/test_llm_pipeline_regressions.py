from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from garmin_fit.llm.client import GeneratedYamlResult, SourceWorkoutFact, UnifiedLLMClient
from garmin_fit.plan_processing import normalize_source_text, repair_plan_data
from garmin_fit.plan_validator import validate_plan_data_detailed


def workout(day=6, km=6):
    name = f"W36_09-{day:02d}_Sun_Easy_6km"
    return {"filename": name, "name": name, "desc": "Easy run", "type_code": "easy",
            "distance_km": km, "estimated_duration_min": 40,
            "steps": [{"type": "dist_open", "km": km, "intensity": "active"}]}


def client():
    return UnifiedLLMClient(model="test", base_url="http://localhost:1234", api_type="openai")


def test_default_retry_corrects_invalid_schema_and_receives_previous_output():
    c = client()
    wrong_workout = workout()
    wrong_workout.pop("steps")
    wrong = yaml.safe_dump({"workouts": [wrong_workout]})
    correct = yaml.safe_dump({"workouts": [workout()]})
    with patch.object(c, "_call_llm", side_effect=[wrong, correct]) as call:
        result = c.generate_yaml_draft("06.09.2026 — Easy run 6 km")
    assert not result.validation_errors
    assert result.attempts == 2
    assert "Previous output to correct:" in call.call_args.args[1]
    assert wrong.strip() in call.call_args.args[1]
    assert result.data["workouts"][0]["distance_km"] == 6


def test_invalid_repeat_anchor_is_not_guessed_by_repair():
    w = workout()
    w["steps"] += [{"type": "dist_open", "km": 0.4},
                   {"type": "repeat", "count": 6, "back_to_offset": 9}]
    repaired, notes = repair_plan_data({"workouts": [w]})
    assert repaired["workouts"][0]["steps"][-1]["back_to_offset"] == 9
    errors, _ = validate_plan_data_detailed(repaired)
    assert any(e.category == "repeat_semantics_error" for e in errors)
    assert not any("repaired back_to_offset" in n for n in notes)


@pytest.mark.parametrize("start", [0, 1, 2])
def test_repeat_must_include_active_step_and_exclude_cooldown(start):
    w = {"type_code": "intervals", "steps": [
        {"type": "dist_open", "km": 0.8, "intensity": "active"},
        {"type": "dist_open", "km": 0.4, "intensity": "recovery"},
        {"type": "dist_open", "km": 2, "intensity": "cooldown"},
        {"type": "repeat", "count": 6, "back_to_offset": start},
    ]}
    fact = SourceWorkoutFact(interval_count=6, interval_rep_km=0.8)
    before = deepcopy(w)
    assert UnifiedLLMClient._detect_suspicious_workout_against_fact(w, fact)
    assert w == before


def test_valid_interval_group_is_accepted():
    w = {"type_code": "intervals", "steps": [
        {"type": "dist_open", "km": 2, "intensity": "warmup"},
        {"type": "dist_open", "km": 0.8, "intensity": "active"},
        {"type": "dist_open", "km": 0.4, "intensity": "recovery"},
        {"type": "repeat", "count": 6, "back_to_offset": 1},
        {"type": "dist_open", "km": 2, "intensity": "cooldown"},
    ]}
    assert not UnifiedLLMClient._detect_suspicious_workout_against_fact(
        w, SourceWorkoutFact(interval_count=6, interval_rep_km=0.8))


def test_large_plan_and_shared_references_reach_model_together():
    c = client()
    source = "All runs: HR <= 140\n" + "\n".join(
        f"{d:02d}.09.2026 - repeat the first workout" for d in range(1, 12))
    output = yaml.safe_dump({"workouts": [workout(day=d) for d in range(1, 12)]})
    with patch.object(c, "_call_llm", return_value=output) as call:
        result = c.generate_yaml_draft(source)
    assert not result.validation_errors
    assert call.call_count == 1
    assert source in call.call_args.args[1]


def test_partial_header_detection_does_not_impose_workout_count():
    source = "06.09.2026 - Easy 6 km\nThen another run on Tuesday, same distance."
    c = client()
    with patch.object(c, "_call_llm", return_value=yaml.safe_dump({"workouts": [workout(6), workout(8)]})):
        result = c.generate_yaml_draft(source)
    assert not result.validation_errors
    assert len(result.data["workouts"]) == 2


def test_rest_in_header_is_not_a_workout_but_running_body_is():
    a = normalize_source_text("06.09.2026 — Отдых\n07.09.2026 — Easy 6 km")
    assert a.expected_workouts == 1
    assert a.workout_headers == ["07.09.2026 — Easy 6 km"]
    assert normalize_source_text("06.09.2026 — Отдых\nБег 6 км").expected_workouts == 1


def test_header_facts_and_missing_hr_are_checked():
    fact = UnifiedLLMClient._extract_single_workout_fact("06.09.2026 — 6x800 m, HR <= 140")
    assert fact.interval_count == 6 and fact.interval_rep_km == 0.8
    assert "missing hr cap 140" in UnifiedLLMClient._detect_suspicious_workout_against_fact(workout(), fact)


def test_duration_and_pace_loss_are_rejected():
    fact = UnifiedLLMClient._extract_single_workout_fact(
        "06.09.2026 — Tempo\nWarmup 10 min\n5 km pace 4:30-4:45")
    errors = UnifiedLLMClient._detect_suspicious_workout_against_fact(workout(), fact)
    assert "missing source duration 600 seconds" in errors
    assert "missing source pace range 4:30-4:45" in errors


def test_complete_thinking_prefix_is_removed_and_incomplete_is_rejected():
    text = yaml.safe_dump({"workouts": [workout()]})
    prefixed = "<think>analysis mentions workouts:</think>\n" + text
    assert yaml.safe_load(UnifiedLLMClient._extract_yaml(prefixed)) == yaml.safe_load(text)
    assert not UnifiedLLMClient._openai_chat_response_needs_fallback(prefixed)
    assert UnifiedLLMClient._openai_chat_response_needs_fallback("<think>workouts: unfinished")
    assert UnifiedLLMClient._openai_chat_response_needs_fallback("workouts:\n- filename: only")
    assert UnifiedLLMClient._openai_chat_response_needs_fallback("Sorry, try again")


def test_year_without_explicit_value_uses_current_year():
    info = UnifiedLLMClient._extract_segment_header_info("06.09 — Easy run")
    expected = date(date.today().year, 9, 6)
    assert info["week"] == expected.isocalendar().week
    assert info["weekday"] == expected.strftime("%a")


def test_nonpositive_attempts_are_rejected():
    with pytest.raises(ValueError, match="max_retries"):
        client().generate_yaml_draft("Easy run", max_retries=0)


def test_all_prompt_examples_preserve_extracted_source_facts():
    from garmin_fit.llm.prompt import STRICT_EXAMPLES_FILE

    examples = yaml.safe_load(STRICT_EXAMPLES_FILE.read_text(encoding="utf-8"))["examples"]
    for example in examples:
        result = GeneratedYamlResult(data=yaml.safe_load(example["output"]))
        facts = UnifiedLLMClient._extract_workout_facts_from_source_text(example["input"])
        UnifiedLLMClient._apply_source_fact_consistency_checks(result, facts)
        assert not result.validation_errors, (example["id"], result.validation_errors)


def test_truncated_completion_is_rejected_even_if_yaml_is_parseable():
    import json

    body = json.dumps({"choices": [{"text": yaml.safe_dump({"workouts": [workout()]}),
                                    "finish_reason": "length"}]}).encode()
    with patch("urllib.request.urlopen") as urlopen:
        response = urlopen.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = body
        assert client()._call_openai_completion("prompt", 10) is None


def test_truncated_chat_is_rejected_and_sdk_retries_are_explicit():
    with patch("openai.OpenAI") as sdk:
        sdk.return_value.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content="workouts: []"), finish_reason="length")])
        assert client()._call_openai_chat([], 10) is None
        assert sdk.call_args.kwargs["max_retries"] == 0


def test_total_and_auxiliary_duration_are_not_running_steps():
    fact = UnifiedLLMClient._extract_single_workout_fact(
        "06.09.2026 — Easy\n6 km\nСиловые 20 минут\nИтого: 40 мин")
    assert fact.durations_sec == []


def test_missing_intensity_does_not_turn_interval_into_warmup():
    data = {"workouts": [{"steps": [
        {"type": "dist_hr", "km": 0.8, "hr_low": 160, "hr_high": 170},
        {"type": "time_hr", "seconds": 90, "hr_low": 100, "hr_high": 130},
        {"type": "repeat", "back_to_offset": 0, "count": 6},
    ]}]}
    repaired, _ = repair_plan_data(data)
    assert [s["intensity"] for s in repaired["workouts"][0]["steps"][:2]] == ["active", "active"]


@pytest.mark.parametrize("source", [
    "На этой неделе два выхода: завтра спокойно шесть километров, в субботу повтори это.",
    "Пн: 6 км легко; четверг — то же самое. Даты не нужны.",
    "| день | занятие |\n| пн | 6 км |\n| чт | как в пн |",
    "6 km easy tomorrow, and again on Sunday. Keep both relaxed.",
])
def test_free_form_inputs_are_forwarded_without_template_requirements(source):
    c = client()
    with patch.object(c, "_call_llm", return_value=yaml.safe_dump({"workouts": [workout(6), workout(8)]})) as call:
        result = c.generate_yaml_draft(source)
    assert not result.validation_errors
    assert source in call.call_args.args[1]
    assert len(result.data["workouts"]) == 2


def test_uncertain_source_comparison_warns_without_rewriting_valid_yaml():
    c = client()
    output = yaml.safe_dump({"workouts": [workout(km=9)]})
    with patch.object(c, "_call_llm", return_value=output) as call:
        result = c.generate_yaml_draft("06.09.2026 — Easy 6 km, or longer if feeling good")
    assert not result.validation_errors
    assert any("heuristic" in warning for warning in result.warnings)
    assert call.call_count == 1
    assert result.data["workouts"][0]["distance_km"] == 9


def test_explicit_user_count_still_blocks_incomplete_output():
    c = client()
    with patch.object(c, "_call_llm", return_value=yaml.safe_dump({"workouts": [workout()]})):
        result = c.generate_yaml_draft("Two easy runs this week", workouts_hint=2, max_retries=1)
    assert result.validation_errors
    assert "workout_count_mismatch" in result.error_categories


@pytest.mark.parametrize("url,trust_env", [
    ("http://127.0.0.1:1234", False),
    ("http://localhost:1234", False),
    ("http://[::1]:1234", False),
    ("https://llm.example.com/v1", True),
])
def test_chat_bypasses_proxy_only_for_loopback(url, trust_env):
    with patch("openai.DefaultHttpxClient") as http, patch("openai.OpenAI") as sdk:
        sdk.return_value.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content="workouts: []"), finish_reason="stop")])
        c = UnifiedLLMClient(model="test", base_url=url, api_type="openai")
        assert c._call_openai_chat([], 10) == "workouts: []"
    http.assert_called_once_with(trust_env=trust_env)


def test_cli_does_not_promote_detected_headers_to_explicit_count(tmp_path):
    from garmin_fit.llm import request_cli

    source = tmp_path / "plan.txt"
    source.write_text("06.09.2026 - Easy 6 km\nRepeat that on Tuesday", encoding="utf-8")
    output = tmp_path / "plan.yaml"
    with patch("sys.argv", ["llm", "--plan", str(source), "--output", str(output)]), \
         patch.object(request_cli, "UnifiedLLMClient") as factory, \
         patch("builtins.input", side_effect=AssertionError("Must not require an input template")):
        factory.return_value.generate_yaml_from_plan.return_value = "workouts: []"
        assert request_cli.main()
        assert factory.return_value.generate_yaml_from_plan.call_args.kwargs["workouts_hint"] == 0


def test_lmstudio_auto_uses_native_reasoning_control_and_context_budget():
    c = client()
    info = {"id": "test", "compatibility_type": "gguf", "state": "loaded", "loaded_context_length": 8192}
    body = {"output": [{"type": "message", "content": "workouts: []"}],
            "stats": {"input_tokens": 20, "total_output_tokens": 5, "reasoning_output_tokens": 0}}
    with patch("requests.get", return_value=SimpleNamespace(status_code=200, json=lambda: {"data": [info]})) as probe, \
         patch("requests.post", return_value=SimpleNamespace(status_code=200, json=lambda: body)) as post, \
         patch.object(c, "_call_openai_chat") as compatibility:
        for _ in range(2):
            assert c._call_openai([{"role": "system", "content": "schema"}, {"role": "user", "content": "whole plan"}], 10) == "workouts: []"
    assert probe.call_count == 1
    compatibility.assert_not_called()
    payload = post.call_args.kwargs["json"]
    assert payload["input"] == "whole plan"
    assert payload["system_prompt"] == "schema"
    assert payload["reasoning"] == "off" and payload["store"] is False
    assert payload["max_output_tokens"] == 4096


def test_lmstudio_rejects_output_at_token_limit():
    c = client()
    c._lmstudio_info = {"loaded_context_length": 8192}
    body = {"output": [{"type": "message", "content": "workouts: []"}],
            "stats": {"total_output_tokens": 4096}}
    with patch("requests.post", return_value=SimpleNamespace(status_code=200, json=lambda: body)):
        assert c._call_lmstudio([], 10) is None


def test_distance_summary_is_computed_from_repeat_steps():
    w = workout()
    w["steps"] = [
        {"type": "dist_open", "km": 2},
        {"type": "dist_open", "km": 0.8},
        {"type": "dist_open", "km": 0.4},
        {"type": "repeat", "back_to_offset": 1, "count": 6},
        {"type": "dist_open", "km": 1},
    ]
    c = client()
    with patch.object(c, "_call_llm", return_value=yaml.safe_dump({"workouts": [w]})):
        result = c.generate_yaml_draft("Intervals as described", max_retries=1)
    assert not result.validation_errors
    assert result.data["workouts"][0]["distance_km"] == 10.2
    assert any("recalculated distance_km" in note for note in result.repairs)


def test_old_lmstudio_without_native_endpoint_uses_chat_compatibility():
    c = client()
    c._lmstudio_probe_done = True
    c._lmstudio_info = {"loaded_context_length": 8192}
    answer = yaml.safe_dump({"workouts": [workout()]})
    with patch("requests.post", return_value=SimpleNamespace(status_code=404)), \
         patch.object(c, "_call_openai_chat", return_value=answer) as chat:
        assert c._call_openai([], 10) == answer
    chat.assert_called_once()


def test_native_context_error_reaches_generation_result():
    c = client()
    c._lmstudio_probe_done = True
    c._lmstudio_info = {"loaded_context_length": 8192}
    with patch("requests.post", return_value=SimpleNamespace(status_code=400, text="Context size has been exceeded")):
        result = c.generate_yaml_draft("A long plan", max_retries=1)
    assert "Context size has been exceeded" in result.validation_errors[0]
