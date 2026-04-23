"""LLM benchmark runner for workout YAML generation quality."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..config import ARTIFACTS_DIR, PROJECT_ROOT
from ..plan_validator import validate_plan_data_detailed
from .client import UnifiedLLMClient

DEFAULT_SUITE = PROJECT_ROOT / "tests" / "fixtures" / "llm_benchmark" / "plan_week_2026_03_02.yaml"


@dataclass(slots=True)
class CheckResult:
    severity: str
    passed: bool
    message: str


def load_suite(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Benchmark suite must be a YAML mapping")
    return data


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
) -> dict[str, Any]:
    suite = load_suite(suite_path)
    client = UnifiedLLMClient(
        model=model,
        base_url=url,
        api_type=api,
        openai_mode=openai_mode,
        request_timeout_sec=timeout_sec,
    )
    cases = []
    failed = 0
    warnings = 0

    for case in suite.get("cases", []):
        case_result = run_case(
            case,
            mode=mode,
            client=client,
            retries=retries,
        )
        cases.append(case_result)
        if case_result["status"] == "fail":
            failed += 1
        warnings += case_result["warning_count"]

    status = "pass" if failed == 0 else "fail"
    return {
        "suite": suite.get("suite", suite_path.stem),
        "mode": mode,
        "status": status,
        "case_count": len(cases),
        "failed_case_count": failed,
        "warning_count": warnings,
        "cases": cases,
    }


def run_case(
    case: dict[str, Any],
    *,
    mode: str,
    client: UnifiedLLMClient,
    retries: int,
) -> dict[str, Any]:
    case_id = str(case["id"])
    input_path = ROOT / str(case["input_path"])
    yaml_path = ROOT / str(case.get("yaml_path", ""))

    source_text = input_path.read_text(encoding="utf-8")
    if mode == "generate":
        generated = client.generate_yaml_draft(source_text, max_retries=retries)
        data = generated.data if isinstance(generated.data, dict) else None
        validation_errors = list(generated.validation_errors)
        yaml_text = generated.yaml_text
    else:
        yaml_text = yaml_path.read_text(encoding="utf-8")
        data = yaml.safe_load(yaml_text)
        errors, _warnings = validate_plan_data_detailed(
            data,
            enforce_filename_name_match=True,
        )
        validation_errors = [issue.message for issue in errors]

    check_results = evaluate_case_expectations(data, case, source_text=source_text)
    hard_failures = [item for item in check_results if item.severity == "error" and not item.passed]
    soft_failures = [item for item in check_results if item.severity == "warning" and not item.passed]

    status = "pass"
    if validation_errors or hard_failures:
        status = "fail"
    elif soft_failures:
        status = "warn"

    return {
        "id": case_id,
        "status": status,
        "input_path": str(input_path.relative_to(ROOT)),
        "yaml_path": str(yaml_path.relative_to(ROOT)) if yaml_path.exists() else None,
        "validation_errors": validation_errors,
        "warning_count": len(soft_failures),
        "checks": [
            {
                "severity": item.severity,
                "passed": item.passed,
                "message": item.message,
            }
            for item in check_results
        ],
        "yaml_preview": yaml_text[:1000] if isinstance(yaml_text, str) else None,
    }


def evaluate_case_expectations(
    data: dict[str, Any] | None,
    case: dict[str, Any],
    *,
    source_text: str | None = None,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    if not isinstance(data, dict):
        return [CheckResult(severity="error", passed=False, message="generated YAML data is missing")]

    workouts = data.get("workouts")
    if not isinstance(workouts, list):
        return [CheckResult(severity="error", passed=False, message="workouts list is missing")]

    expected_count = case.get("expected_workout_count")
    if isinstance(expected_count, int):
        results.append(
            CheckResult(
                severity="error",
                passed=len(workouts) == expected_count,
                message=f"expected workout count {expected_count}, got {len(workouts)}",
            )
        )

    expected_filenames = case.get("expected_filenames")
    if isinstance(expected_filenames, list):
        actual_filenames = [item.get("filename") for item in workouts if isinstance(item, dict)]
        results.append(
            CheckResult(
                severity="error",
                passed=actual_filenames == expected_filenames,
                message=f"expected filenames {expected_filenames}, got {actual_filenames}",
            )
        )

    for check in case.get("checks", []):
        result = evaluate_single_check(workouts, check)
        results.append(result)

    if source_text:
        facts = UnifiedLLMClient._extract_workout_facts_from_source_text(source_text)
        for fact in facts:
            passed, message = UnifiedLLMClient._evaluate_workouts_against_source_fact(workouts, fact)
            results.append(
                CheckResult(
                    severity="error",
                    passed=passed,
                    message=message,
                )
            )

    return results


def evaluate_single_check(workouts: list[dict[str, Any]], check: dict[str, Any]) -> CheckResult:
    severity = str(check.get("severity", "error"))
    kind = str(check.get("kind"))
    workout_name = str(check.get("workout"))
    workout = next((item for item in workouts if item.get("filename") == workout_name), None)

    if workout is None:
        return CheckResult(
            severity=severity,
            passed=False,
            message=f"{kind}: workout '{workout_name}' not found",
        )

    if kind == "workout_field":
        field = str(check["field"])
        expected = check.get("equals")
        actual = workout.get(field)
        return CheckResult(
            severity=severity,
            passed=actual == expected,
            message=f"{workout_name}.{field}: expected {expected!r}, got {actual!r}",
        )

    if kind == "step_field":
        step_index = int(check["step_index"])
        steps = workout.get("steps")
        if not isinstance(steps, list) or step_index >= len(steps):
            return CheckResult(
                severity=severity,
                passed=False,
                message=f"{workout_name}.steps[{step_index}] missing",
            )
        field = str(check["field"])
        expected = check.get("equals")
        actual = steps[step_index].get(field)
        return CheckResult(
            severity=severity,
            passed=actual == expected,
            message=f"{workout_name}.steps[{step_index}].{field}: expected {expected!r}, got {actual!r}",
        )

    return CheckResult(
        severity=severity,
        passed=False,
        message=f"unsupported benchmark check kind '{kind}'",
    )


def save_report(report: dict[str, Any], suite_path: Path) -> Path:
    out_dir = ARTIFACTS_DIR
    out_dir.mkdir(exist_ok=True)
    output_path = out_dir / f"{suite_path.stem}.llm_benchmark_report.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run LLM quality benchmark for workout YAML generation")
    parser.add_argument("--suite", type=str, default=str(DEFAULT_SUITE), help="Path to benchmark suite YAML")
    parser.add_argument("--mode", choices=["existing", "generate"], default="existing")
    parser.add_argument("--api", choices=["ollama", "openai"], default="openai")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:1234/v1")
    parser.add_argument("--model", type=str, default="qwen/qwen3.5-9b")
    parser.add_argument("--openai-mode", choices=["auto", "chat", "completions"], default="completions")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    args = parser.parse_args()

    suite_path = Path(args.suite)
    if not suite_path.is_absolute():
        suite_path = ROOT / suite_path

    report = run_suite(
        suite_path,
        mode=args.mode,
        api=args.api,
        url=args.url,
        model=args.model,
        openai_mode=args.openai_mode,
        retries=args.retries,
        timeout_sec=args.timeout_sec,
    )
    report_path = save_report(report, suite_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nSaved: {report_path}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
