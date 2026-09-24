"""End-to-end local evaluation harness for workout-plan LLM generation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import platform
import statistics
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..config import ARTIFACTS_DIR, PROJECT_ROOT
from ..plan_processing import repair_plan_data
from ..plan_validator import group_issues_by_category, validate_plan_data_detailed
from .benchmark import evaluate_case_expectations
from .client import UnifiedLLMClient
from .marked_source_checks import (
    STEP_MARKER,
    sanitize_marked_source_targets,
    validate_marked_source_structure,
)

logger = logging.getLogger(__name__)


class JsonlTraceWriter:
    """Append trace events immediately so interrupted runs remain inspectable."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.events: list[dict[str, Any]] = []

    def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            stream.flush()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_ollama_model_fingerprint(base_url: str, model: str) -> dict[str, Any] | None:
    """Best-effort capture of the Ollama model digest and byte size."""
    try:
        import requests

        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        response.raise_for_status()
        models = response.json().get("models", [])
        match = next(
            (item for item in models if item.get("name") == model or item.get("model") == model),
            None,
        )
        if not isinstance(match, dict):
            return None
        return {
            key: match.get(key)
            for key in ("name", "model", "digest", "size", "modified_at")
            if match.get(key) is not None
        }
    except Exception as exc:
        logger.info("Could not capture Ollama model fingerprint: %s", exc)
        return None


def resolve_case_path(raw_path: str, suite_path: Path) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    beside_suite = suite_path.parent / path
    if beside_suite.exists():
        return beside_suite
    return PROJECT_ROOT / path


def load_suite(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not isinstance(loaded.get("cases"), list):
        raise ValueError("Suite must be a mapping with a cases list")
    seen: set[str] = set()
    for index, case in enumerate(loaded["cases"]):
        if not isinstance(case, dict) or not case.get("id") or not case.get("input_path"):
            raise ValueError(f"Suite case {index + 1} needs id and input_path")
        case_id = str(case["id"])
        if case_id in seen:
            raise ValueError(f"Duplicate suite case id: {case_id}")
        seen.add(case_id)
    if not loaded["cases"]:
        raise ValueError("Suite contains no cases")
    return loaded


def validate_source_markers(source_text: str) -> dict[str, Any]:
    """Report malformed marked input before paying for an LLM request."""
    lines = [line.strip() for line in source_text.splitlines()]
    marked = STEP_MARKER in lines
    result: dict[str, Any] = {
        "marked_format": marked,
        "workout_markers": sum(line.startswith("==== ТРЕНИРОВКА") for line in lines),
        "step_markers": sum(line == STEP_MARKER for line in lines),
        "errors": [],
        "warnings": [],
        "needs_user_input": [],
    }
    if not source_text.strip():
        result["errors"].append("source text is empty")
        return result
    if not marked:
        result["warnings"].append("source is unmarked; source-level structural checks are limited")
        return result

    in_workout = False
    in_step = False
    in_repeat = False
    step_has_measure = False

    def close_step(line_number: int | None = None) -> None:
        nonlocal in_step, step_has_measure
        if in_step and not step_has_measure:
            prefix = f"line {line_number}: " if line_number else ""
            result["needs_user_input"].append(
                prefix + "step has no distance or duration; user input is required"
            )
        in_step = False
        step_has_measure = False

    for line_number, line in enumerate(lines, 1):
        if line.startswith("==== ТРЕНИРОВКА"):
            if in_repeat:
                result["errors"].append(f"line {line_number}: workout starts before repeat is closed")
            close_step(line_number)
            in_workout = True
            continue
        if line == STEP_MARKER:
            if not in_workout:
                result["errors"].append(f"line {line_number}: step is outside a workout")
            close_step(line_number)
            in_step = True
            step_has_measure = False
            continue
        if line.startswith("**** ПОВТОР:"):
            if not in_workout:
                result["errors"].append(f"line {line_number}: repeat is outside a workout")
            if in_repeat:
                result["errors"].append(f"line {line_number}: nested repeats are unsupported")
            close_step(line_number)
            in_repeat = True
            continue
        if line.startswith("**** КОНЕЦ ПОВТОРА"):
            if not in_repeat:
                result["errors"].append(f"line {line_number}: repeat end has no matching start")
            in_repeat = False
            close_step(line_number)
            continue
        if line.startswith("****"):
            result["errors"].append(f"line {line_number}: unknown marker {line!r}")
            continue
        if in_step and line:
            if line.lower().startswith(("дистанция:", "длительность:")):
                step_has_measure = True
            if line.lower().startswith("тип:") and "сбу" in line.lower():
                step_has_measure = True

    if result["workout_markers"] == 0:
        result["errors"].append("marked steps require at least one workout marker")
    if in_repeat:
        result["errors"].append("repeat has no closing marker")
    close_step()
    return result


def extract_raw_response(payload: Any) -> str:
    """Accept plain text, Ollama responses, and OpenAI-compatible response JSON."""
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("Raw response must be text or a response mapping")
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    response = payload.get("response")
    if isinstance(response, str):
        return response
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice = choices[0]
        choice_message = choice.get("message")
        if isinstance(choice_message, dict) and isinstance(choice_message.get("content"), str):
            return choice_message["content"]
        if isinstance(choice.get("text"), str):
            return choice["text"]
    raise ValueError("Could not find generated text in raw response JSON")


def check_raw_candidate(raw_response: str, source_text: str) -> dict[str, Any]:
    """Score the model's unmodified YAML before deterministic pipeline repairs."""
    yaml_text = UnifiedLLMClient._extract_yaml(raw_response)
    try:
        raw_data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return {
            "yaml_parse_valid": False,
            "schema_valid": False,
            "structure_valid": False,
            "parse_error": str(exc),
            "schema_errors": [],
            "structure_errors": [],
        }
    if not isinstance(raw_data, dict):
        return {
            "yaml_parse_valid": True,
            "schema_valid": False,
            "structure_valid": False,
            "parse_error": None,
            "schema_errors": ["YAML root must be a mapping"],
            "structure_errors": [],
        }
    errors, _warnings = validate_plan_data_detailed(
        raw_data,
        enforce_filename_name_match=True,
    )
    structure_errors = validate_marked_source_structure(source_text, raw_data)
    target_probe = copy.deepcopy(raw_data)
    target_repairs, target_warnings = sanitize_marked_source_targets(source_text, target_probe)
    return {
        "yaml_parse_valid": True,
        "schema_valid": not errors,
        "structure_valid": not structure_errors,
        "parse_error": None,
        "schema_errors": [issue.message for issue in errors],
        "structure_errors": structure_errors,
        "target_repairs_needed": target_repairs,
        "target_warnings": target_warnings,
        "strict_raw_pass": not errors and not structure_errors and not target_repairs,
    }


def combine_segment_responses(responses: list[str]) -> str:
    """Combine final raw responses from a segmented multi-workout generation."""
    if len(responses) <= 1:
        return responses[0] if responses else ""
    workouts: list[dict[str, Any]] = []
    for response in responses:
        try:
            parsed = yaml.safe_load(UnifiedLLMClient._extract_yaml(response))
        except yaml.YAMLError:
            return "\n\n".join(responses)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("workouts"), list):
            return "\n\n".join(responses)
        workouts.extend(item for item in parsed["workouts"] if isinstance(item, dict))
    return yaml.safe_dump(
        {"workouts": workouts},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def evaluate_case(
    *,
    case: dict[str, Any],
    source_text: str,
    raw_response: str,
    client_result: Any | None = None,
) -> dict[str, Any]:
    """Run raw-output and final-pipeline checks for one trial."""
    preflight = validate_source_markers(source_text)
    raw_checks = check_raw_candidate(raw_response, source_text)
    if client_result is None:
        from ..plan_processing import normalize_source_text

        analysis = normalize_source_text(source_text)
        result = UnifiedLLMClient._prepare_yaml_candidate(
            UnifiedLLMClient._extract_yaml(raw_response),
            analysis_repairs=[],
            analysis_ambiguities=analysis.ambiguities,
            expected_workout_count=int(case.get("expected_workout_count", analysis.expected_workouts)),
            source_text=source_text,
            repair_plan_data=repair_plan_data,
            validate_plan_data_detailed=validate_plan_data_detailed,
            group_issues_by_category=group_issues_by_category,
        )
        source_facts = UnifiedLLMClient._extract_workout_facts_from_source_text(source_text)
        UnifiedLLMClient._apply_source_fact_consistency_checks(result, source_facts)
        UnifiedLLMClient._demote_source_fact_mismatch(result)
    else:
        result = client_result

    final_yaml_errors: list[str] = []
    roundtrip_structure_errors: list[str] = []
    if result.yaml_text:
        try:
            final_data = yaml.safe_load(result.yaml_text)
            if not isinstance(final_data, dict):
                final_yaml_errors.append("serialized YAML root is not a mapping")
            else:
                schema_errors, _ = validate_plan_data_detailed(
                    final_data,
                    enforce_filename_name_match=True,
                )
                final_yaml_errors.extend(issue.message for issue in schema_errors)
                roundtrip_structure_errors = validate_marked_source_structure(
                    source_text,
                    final_data,
                )
        except yaml.YAMLError as exc:
            final_yaml_errors.append(f"serialized YAML parse error: {exc}")
    elif not result.validation_errors:
        final_yaml_errors.append("pipeline returned no serialized YAML")

    data = result.data if isinstance(result.data, dict) else None
    expectation_results = evaluate_case_expectations(data, case, source_text=None)
    hard_check_failures = [
        check.message
        for check in expectation_results
        if check.severity == "error" and not check.passed
    ]
    strict_pass = (
        not preflight["errors"]
        and not preflight["needs_user_input"]
        and not result.validation_errors
        and not final_yaml_errors
        and not roundtrip_structure_errors
        and not hard_check_failures
    )
    return {
        "case_id": str(case["id"]),
        "tags": list(case.get("tags", [])),
        "source_sha256": sha256_text(source_text),
        "source_preflight": preflight,
        "raw_candidate": raw_checks,
        "pipeline": {
            "passed": not result.validation_errors,
            "attempts": result.attempts,
            "validation_errors": result.validation_errors,
            "error_categories": result.error_categories,
            "warnings": result.warnings,
            "repairs": result.repairs,
        },
        "serialized_yaml": {
            "present": result.yaml_text is not None,
            "schema_errors": final_yaml_errors,
            "structure_errors": roundtrip_structure_errors,
        },
        "expectation_checks": [
            {
                "severity": check.severity,
                "passed": check.passed,
                "message": check.message,
            }
            for check in expectation_results
        ],
        "strict_pass": strict_pass,
        "warning_count": len(preflight["warnings"]) + len(result.warnings),
    }


def _render_summary(report: dict[str, Any]) -> str:
    rows = report["results"]
    passed = sum(bool(row["strict_pass"]) for row in rows)
    lines = [
        f"# LLM evaluation: {report['suite']}",
        "",
        f"Run: `{report['run_id']}`  ",
        f"Mode: `{report['mode']}`  ",
        f"Model: `{report['model']}`  ",
        f"Strict pass: **{passed}/{len(rows)}** trials",
        "",
        "| Case | Raw schema | Raw structure | Final pass | Errors |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        raw = row.get("raw_candidate", {})
        errors = row.get("pipeline", {}).get("validation_errors", [])
        lines.append(
            f"| {row['case_id']} | {bool(raw.get('schema_valid'))} "
            f"| {bool(raw.get('structure_valid'))} | {bool(row['strict_pass'])} "
            f"| {len(errors)} |"
        )
    lines.extend(["", "Raw replies and attempt events are in `trace.jsonl`."])
    return "\n".join(lines) + "\n"


def compare_reports(first_path: Path, second_path: Path, output_root: Path) -> tuple[dict[str, Any], Path]:
    """Compare two runs only when every paired trial used the same source text."""
    reports = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (first_path, second_path)
    ]
    keyed_results: list[dict[tuple[str, int], dict[str, Any]]] = []
    for report in reports:
        keyed: dict[tuple[str, int], dict[str, Any]] = {}
        for row in report.get("results", []):
            key = (str(row["case_id"]), int(row.get("trial", 1)))
            if key in keyed:
                raise ValueError(f"Duplicate case/trial in report: {key}")
            keyed[key] = row
        keyed_results.append(keyed)
    left, right = keyed_results
    if left.keys() != right.keys():
        missing_right = sorted(left.keys() - right.keys())
        missing_left = sorted(right.keys() - left.keys())
        raise ValueError(
            f"Reports have different case/trial sets; missing from second={missing_right}, "
            f"missing from first={missing_left}"
        )

    pairs = []
    for key in sorted(left):
        a, b = left[key], right[key]
        if a.get("source_sha256") != b.get("source_sha256"):
            raise ValueError(f"Source text differs for case/trial {key}")
        a_pass, b_pass = bool(a.get("strict_pass")), bool(b.get("strict_pass"))
        pairs.append({
            "case_id": key[0],
            "trial": key[1],
            "source_sha256": a.get("source_sha256"),
            "first_strict_pass": a_pass,
            "second_strict_pass": b_pass,
            "winner": "tie" if a_pass == b_pass else "first" if a_pass else "second",
            "first_latency_sec": a.get("runtime", {}).get("latency_sec"),
            "second_latency_sec": b.get("runtime", {}).get("latency_sec"),
        })
    first_times = [pair["first_latency_sec"] for pair in pairs if isinstance(pair["first_latency_sec"], (int, float))]
    second_times = [pair["second_latency_sec"] for pair in pairs if isinstance(pair["second_latency_sec"], (int, float))]
    comparison = {
        "first_run_id": reports[0].get("run_id"),
        "first_model": reports[0].get("model"),
        "second_run_id": reports[1].get("run_id"),
        "second_model": reports[1].get("model"),
        "paired_trials": len(pairs),
        "first_pass_count": sum(pair["first_strict_pass"] for pair in pairs),
        "second_pass_count": sum(pair["second_strict_pass"] for pair in pairs),
        "first_wins": sum(pair["winner"] == "first" for pair in pairs),
        "second_wins": sum(pair["winner"] == "second" for pair in pairs),
        "ties": sum(pair["winner"] == "tie" for pair in pairs),
        "first_median_latency_sec": statistics.median(first_times) if first_times else None,
        "second_median_latency_sec": statistics.median(second_times) if second_times else None,
        "pairs": pairs,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    comparison_path = output_root / f"comparison-{uuid.uuid4().hex[:8]}.json"
    comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# Paired LLM comparison: {comparison['first_model']} vs {comparison['second_model']}",
        "",
        f"Paired trials: **{len(pairs)}**  ",
        f"Strict pass: **{comparison['first_pass_count']}/{len(pairs)}** vs **{comparison['second_pass_count']}/{len(pairs)}**  ",
        f"Paired wins: **{comparison['first_wins']}** vs **{comparison['second_wins']}**, ties: **{comparison['ties']}**  ",
        f"Median latency: **{comparison['first_median_latency_sec']} s** vs **{comparison['second_median_latency_sec']} s**",
        "",
        "| Case | Trial | First | Second | Winner | Time (s) |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for pair in pairs:
        lines.append(
            f"| {pair['case_id']} | {pair['trial']} | {pair['first_strict_pass']} "
            f"| {pair['second_strict_pass']} | {pair['winner']} "
            f"| {pair['first_latency_sec']} / {pair['second_latency_sec']} |"
        )
    comparison_path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return comparison, comparison_path


def run_suite(
    suite_path: Path,
    *,
    mode: str,
    api: str,
    url: str,
    model: str,
    openai_mode: str,
    retries: int,
    timeout_sec: int,
    trials: int,
    output_root: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    suite = load_suite(suite_path)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = (output_root or (ARTIFACTS_DIR / "llm_eval")) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    trace_writer = JsonlTraceWriter(run_dir / "trace.jsonl")
    client = None
    if mode == "live":
        client = UnifiedLLMClient(
            model=model,
            base_url=url,
            api_type=api,
            openai_mode=openai_mode,
            request_timeout_sec=timeout_sec,
            trace_callback=trace_writer,
        )

    results: list[dict[str, Any]] = []
    for case in suite["cases"]:
        source_path = resolve_case_path(str(case["input_path"]), suite_path)
        source_text = source_path.read_text(encoding="utf-8")
        for trial in range(1, trials + 1):
            trace_writer({
                "event": "case_started",
                "case_id": str(case["id"]),
                "trial": trial,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "source_sha256": sha256_text(source_text),
            })
            raw_response = ""
            client_result = None
            runtime_metrics: dict[str, Any] = {}
            if mode == "live":
                assert client is not None
                client.set_trace_context(case_id=str(case["id"]), trial=trial, run_id=run_id)
                preflight = validate_source_markers(source_text)
                trace_writer({
                    "event": "source_preflight",
                    "case_id": str(case["id"]),
                    "trial": trial,
                    "result": preflight,
                })
                if preflight["errors"]:
                    row = {
                        "case_id": str(case["id"]),
                        "trial": trial,
                        "tags": list(case.get("tags", [])),
                        "source_sha256": sha256_text(source_text),
                        "source_preflight": preflight,
                        "strict_pass": False,
                        "pipeline": {"validation_errors": preflight["errors"]},
                    }
                    results.append(row)
                    trace_writer({
                        "event": "case_finished",
                        "case_id": str(case["id"]),
                        "trial": trial,
                        "strict_pass": False,
                        "reason": "source_preflight_errors",
                    })
                    continue
                trace_start = len(trace_writer.events)
                client_result = client.generate_yaml_draft(source_text, max_retries=retries)
                responses_by_generation: dict[str, str] = {}
                case_events = trace_writer.events[trace_start:]
                for event in case_events:
                    if event.get("event") != "llm_response" or event.get("case_id") != str(case["id"]):
                        continue
                    generation_id = str(event.get("generation_id", "ungrouped"))
                    responses_by_generation[generation_id] = str(event.get("raw_response") or "")
                response_events = [event for event in case_events if event.get("event") == "llm_response"]
                raw_response = combine_segment_responses(list(responses_by_generation.values()))
                runtime_metrics = {
                    "llm_call_count": len(response_events),
                    "latency_sec": round(sum(
                        float(event.get("client_elapsed_sec", 0) or 0)
                        for event in response_events
                    ), 6),
                    "ollama_total_duration_ns": sum(
                        int(event.get("total_duration", 0) or 0)
                        for event in response_events
                    ) or None,
                    "prompt_tokens": sum(
                        int(event.get("prompt_eval_count", event.get("prompt_tokens", 0)) or 0)
                        for event in response_events
                    ),
                    "completion_tokens": sum(
                        int(event.get("eval_count", event.get("completion_tokens", 0)) or 0)
                        for event in response_events
                    ),
                }
            else:
                raw_path_value = case.get("raw_response_path")
                if not raw_path_value:
                    raise ValueError(f"Offline case {case['id']} needs raw_response_path")
                raw_path = resolve_case_path(str(raw_path_value), suite_path)
                payload = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.suffix.lower() == ".json" else raw_path.read_text(encoding="utf-8")
                raw_response = extract_raw_response(payload)
                if isinstance(payload, dict):
                    latency = payload.get("elapsed_sec")
                    if latency is None and isinstance(payload.get("total_duration"), (int, float)):
                        latency = float(payload["total_duration"]) / 1_000_000_000
                    runtime_metrics = {
                        "latency_sec": latency,
                        "load_duration_ns": payload.get("load_duration"),
                        "prompt_eval_count": payload.get("prompt_eval_count"),
                        "prompt_eval_cached_count": payload.get("prompt_eval_cached_count"),
                        "prompt_eval_duration_ns": payload.get("prompt_eval_duration"),
                        "eval_count": payload.get("eval_count"),
                        "eval_duration_ns": payload.get("eval_duration"),
                    }
                trace_writer({
                    "event": "offline_response_loaded",
                    "case_id": str(case["id"]),
                    "trial": trial,
                    "raw_response": raw_response,
                    "raw_response_sha256": sha256_text(raw_response),
                })

            result_row = evaluate_case(
                case=case,
                source_text=source_text,
                raw_response=raw_response,
                client_result=client_result,
            )
            result_row["trial"] = trial
            result_row["runtime"] = runtime_metrics
            results.append(result_row)
            trace_writer({
                "event": "case_finished",
                "case_id": str(case["id"]),
                "trial": trial,
                "strict_pass": result_row["strict_pass"],
                "raw_schema_valid": result_row.get("raw_candidate", {}).get("schema_valid"),
                "raw_structure_valid": result_row.get("raw_candidate", {}).get("structure_valid"),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })

    model_fingerprint = (
        get_ollama_model_fingerprint(url, model)
        if mode == "live" and api == "ollama"
        else None
    )
    report = {
        "run_id": run_id,
        "started_at_utc": run_id.split("-")[0],
        "suite": suite.get("suite", suite_path.stem),
        "suite_sha256": sha256_text(suite_path.read_text(encoding="utf-8")),
        "mode": mode,
        "api": api if mode == "live" else None,
        "url": url if mode == "live" else None,
        "model": model,
        "model_fingerprint": model_fingerprint,
        "python": platform.python_version(),
        "case_count": len(suite["cases"]),
        "trial_count": trials,
        "strict_pass_count": sum(bool(row.get("strict_pass")) for row in results),
        "strict_fail_count": sum(not bool(row.get("strict_pass")) for row in results),
        "results": results,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "summary.md").write_text(_render_summary(report), encoding="utf-8")
    return report, run_dir


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the FitWeaver LLM evaluation harness")
    parser.add_argument("--suite", help="YAML suite manifest")
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("FIRST_RESULTS_JSON", "SECOND_RESULTS_JSON"),
        help="Create a paired comparison from two prior results.json files",
    )
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--api", choices=["ollama", "openai"], default="ollama")
    parser.add_argument("--url", default="http://localhost:11434")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--openai-mode", choices=["auto", "chat", "completions"], default="auto")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()
    if args.compare:
        output_root = args.output_root or (ARTIFACTS_DIR / "llm_eval")
        comparison, comparison_path = compare_reports(
            *(Path(value).expanduser() for value in args.compare),
            output_root,
        )
        print(comparison_path.with_suffix(".md").read_text(encoding="utf-8"))
        print(f"Artifacts: {comparison_path}")
        return 0
    if not args.suite:
        parser.error("--suite is required unless --compare is used")
    if args.trials < 1:
        parser.error("--trials must be positive")

    suite_path = Path(args.suite).expanduser()
    if not suite_path.is_absolute():
        suite_path = PROJECT_ROOT / suite_path
    report, run_dir = run_suite(
        suite_path,
        mode=args.mode,
        api=args.api,
        url=args.url,
        model=args.model,
        openai_mode=args.openai_mode,
        retries=args.retries,
        timeout_sec=args.timeout_sec,
        trials=args.trials,
        output_root=args.output_root,
    )
    print((run_dir / "summary.md").read_text(encoding="utf-8"))
    print(f"Artifacts: {run_dir}")
    return 0 if report["strict_fail_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
