"""FunctionGemma zero-shot baseline runner against golden_examples_v1.yaml.

Point this at a local LM Studio (or any OpenAI-compatible) server serving
FunctionGemma 270M (or any other candidate model, per the size ladder in
your plan), and it runs every VALID group's text variants through the
*existing* production prompt (garmin_fit.llm.prompt / UnifiedLLMClient --
same one the Qwen pipeline uses), then scores the result with a real
semantic-exact-match comparison (order-independent, MM:SS pace constants
resolved, int/float normalized) against the group's canonical structure.

This deliberately does NOT use a function-calling prompt yet (see
SCHEMA_V1.md Sec.4) -- it reuses the existing YAML-contract prompt as-is,
so the first measurement answers "can this model follow FitWeaver's
existing prompt at all, zero-shot, in Russian" before any decision about
function-call framing. NEEDS_CLARIFICATION / UNSUPPORTED groups are
excluded for now -- the current prompt pipeline has no way to emit or
grade that status yet (SCHEMA_V1.md Sec.3), only VALID groups are graded.

Usage (from the project root, after `pip install -e ".[dev]"`):

    python docs/llm_finetune/run_baseline.py \\
        --api openai --url http://127.0.0.1:1234/v1 \\
        --model functiongemma-270m-it

Add --dry-run to validate the golden dataset and the comparator itself
without calling any LLM server (useful as a smoke test before the real run).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_FILE = Path(__file__).resolve().parent / "golden_examples_v1.yaml"


# ---------------------------------------------------------------------------
# Semantic-exact-match comparator (SCHEMA_V1.md Sec.5 gap)
# ---------------------------------------------------------------------------

_STEP_IGNORED_KEYS_IF_ABSENT_ON_EITHER_SIDE = {"intensity"}


def _resolve_pace(key: str, value: Any) -> Any:
    from garmin_fit.plan_domain import PACE_CONSTANT_VALUES

    if key in ("pace_fast", "pace_slow") and isinstance(value, str):
        return PACE_CONSTANT_VALUES.get(value, value)
    return value


def _normalize_scalar(key: str, value: Any) -> Any:
    value = _resolve_pace(key, value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in step.items():
        if value is None and key in _STEP_IGNORED_KEYS_IF_ABSENT_ON_EITHER_SIDE:
            continue
        if key == "drills" and isinstance(value, list):
            out[key] = [
                {dk: _normalize_scalar(dk, dv) for dk, dv in sorted(drill.items())}
                for drill in value
            ]
            continue
        out[key] = _normalize_scalar(key, value)
    return out


@dataclass(slots=True)
class SemanticDiff:
    path: str
    detail: str


def compare_workouts(expected: dict[str, Any], actual: dict[str, Any] | None) -> list[SemanticDiff]:
    """Compare one expected workout dict against one actual workout dict.

    Order-sensitive on `steps` (step order is semantic -- a workout is a
    sequence of instructions), order-insensitive on dict keys, normalizes
    int/float and pace constants. Returns an empty list iff they match.
    """
    diffs: list[SemanticDiff] = []
    if actual is None:
        return [SemanticDiff("", "no matching workout produced")]

    scalar_fields = ["filename", "name", "type_code", "distance_km", "estimated_duration_min"]
    for field_name in scalar_fields:
        exp_val = _normalize_scalar(field_name, expected.get(field_name))
        act_val = _normalize_scalar(field_name, actual.get(field_name))
        if exp_val != act_val:
            diffs.append(SemanticDiff(field_name, f"expected {exp_val!r}, got {act_val!r}"))

    exp_steps = expected.get("steps") or []
    act_steps = actual.get("steps") or []
    if len(exp_steps) != len(act_steps):
        diffs.append(
            SemanticDiff("steps", f"expected {len(exp_steps)} step(s), got {len(act_steps)}")
        )

    for idx, exp_step in enumerate(exp_steps):
        if idx >= len(act_steps):
            break
        act_step = act_steps[idx]
        exp_norm = _normalize_step(exp_step if isinstance(exp_step, dict) else {})
        act_norm = _normalize_step(act_step if isinstance(act_step, dict) else {})
        if exp_norm != act_norm:
            diffs.append(SemanticDiff(f"steps[{idx}]", f"expected {exp_norm!r}, got {act_norm!r}"))

    return diffs


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class VariantResult:
    group_id: str
    variant_id: str
    style: str
    status: str  # "pass" | "fail" | "generation_error"
    schema_valid: bool
    semantic_exact_match: bool
    diffs: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    attempts: int = 0


def load_valid_groups(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [g for g in data["groups"] if g["status"] == "VALID"]


def run_variant(client, group: dict[str, Any], variant: dict[str, Any], max_retries: int) -> VariantResult:
    text = variant["text"]
    result = client.generate_yaml_draft(text, max_retries=max_retries)

    base = dict(
        group_id=group["group_id"],
        variant_id=variant["id"],
        style=variant.get("style", ""),
        attempts=result.attempts,
        validation_errors=list(result.validation_errors),
    )

    if result.data is None or not isinstance(result.data.get("workouts"), list):
        return VariantResult(
            **base, status="generation_error", schema_valid=False, semantic_exact_match=False
        )

    expected_workout = group["canonical"]["workouts"][0]
    actual_workout = result.data["workouts"][0] if result.data["workouts"] else None
    diffs = compare_workouts(expected_workout, actual_workout)
    exact_match = not diffs

    return VariantResult(
        **base,
        status="pass" if exact_match else "fail",
        schema_valid=not result.validation_errors,
        semantic_exact_match=exact_match,
        diffs=[f"{d.path}: {d.detail}" for d in diffs],
    )


def run_baseline(
    *,
    api: str,
    url: str,
    model: str,
    openai_mode: str,
    retries: int,
    timeout_sec: int,
    groups: list[dict[str, Any]],
) -> list[VariantResult]:
    from garmin_fit.llm.client import UnifiedLLMClient

    client = UnifiedLLMClient(
        model=model,
        base_url=url,
        api_type=api,
        openai_mode=openai_mode,
        request_timeout_sec=timeout_sec,
    )

    results: list[VariantResult] = []
    total_variants = sum(len(g["variants"]) for g in groups)
    done = 0
    for group in groups:
        for variant in group["variants"]:
            done += 1
            print(f"[{done}/{total_variants}] {group['group_id']} / {variant['id']} ...", flush=True)
            results.append(run_variant(client, group, variant, retries))
    return results


def dry_run_self_test(groups: list[dict[str, Any]]) -> list[VariantResult]:
    """No network calls: score each group's canonical against itself (must be
    a perfect match) and against a deliberately mutated copy (must fail),
    to prove the comparator works before spending time on a real model run.
    """
    results: list[VariantResult] = []
    for group in groups:
        expected = group["canonical"]["workouts"][0]

        diffs = compare_workouts(expected, expected)
        results.append(
            VariantResult(
                group_id=group["group_id"],
                variant_id="<self-match self-test>",
                style="self_test",
                status="pass" if not diffs else "fail",
                schema_valid=True,
                semantic_exact_match=not diffs,
                diffs=[f"{d.path}: {d.detail}" for d in diffs],
            )
        )

        mutated = json.loads(json.dumps(expected))
        if mutated.get("steps"):
            first_step = mutated["steps"][0]
            if "km" in first_step:
                first_step["km"] = float(first_step["km"]) + 1.0
            elif "seconds" in first_step:
                first_step["seconds"] = int(first_step["seconds"]) + 1
        mutated["filename"] = str(mutated.get("filename", "")) + "_MUTATED"
        diffs = compare_workouts(expected, mutated)
        results.append(
            VariantResult(
                group_id=group["group_id"],
                variant_id="<mutation-detection self-test>",
                style="self_test",
                status="pass" if diffs else "fail",  # "pass" here means the mutation WAS caught
                schema_valid=True,
                semantic_exact_match=not diffs,
                diffs=[f"{d.path}: {d.detail}" for d in diffs],
            )
        )
    return results


def summarize(results: list[VariantResult]) -> dict[str, Any]:
    n = len(results)
    schema_valid = sum(1 for r in results if r.schema_valid)
    exact_match = sum(1 for r in results if r.semantic_exact_match)
    generation_errors = sum(1 for r in results if r.status == "generation_error")
    return {
        "total_variants": n,
        "schema_valid_rate": schema_valid / n if n else 0.0,
        "semantic_exact_match_rate": exact_match / n if n else 0.0,
        "generation_error_count": generation_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--groups-file", type=str, default=str(GOLDEN_FILE))
    parser.add_argument("--api", choices=["ollama", "openai"], default="openai")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:1234/v1")
    parser.add_argument("--model", type=str, default="functiongemma-270m-it")
    parser.add_argument("--openai-mode", choices=["auto", "chat", "completions"], default="auto")
    parser.add_argument("--retries", type=int, default=1, help="Attempts per variant (default: 1 -- this is a ZERO-SHOT baseline, not the production retry-corrected pipeline)")
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true", help="Self-test the comparator only, no LLM calls")
    parser.add_argument("--limit", type=int, default=0, help="Only run the first N groups (0 = all)")
    args = parser.parse_args()

    groups = load_valid_groups(Path(args.groups_file))
    if args.limit:
        groups = groups[: args.limit]

    if args.dry_run:
        print(f"Dry run: self-testing comparator against {len(groups)} VALID groups (no LLM calls).\n")
        results = dry_run_self_test(groups)
    else:
        print(
            f"Running {sum(len(g['variants']) for g in groups)} variants across {len(groups)} "
            f"VALID groups against {args.model} @ {args.url} ...\n"
        )
        results = run_baseline(
            api=args.api,
            url=args.url,
            model=args.model,
            openai_mode=args.openai_mode,
            retries=args.retries,
            timeout_sec=args.timeout_sec,
            groups=groups,
        )

    summary = summarize(results)
    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2))

    print("\n=== Failures ===")
    for r in results:
        if r.status != "pass":
            print(f"- {r.group_id} / {r.variant_id} [{r.status}]")
            for d in r.diffs[:5]:
                print(f"    {d}")
            for e in r.validation_errors[:3]:
                print(f"    validation_error: {e}")

    try:
        from garmin_fit.config import ARTIFACTS_DIR

        ARTIFACTS_DIR.mkdir(exist_ok=True, parents=True)
        report_path = ARTIFACTS_DIR / f"llm_finetune_baseline.{'dry_run' if args.dry_run else args.model}.json"
        report_path.write_text(
            json.dumps(
                {
                    "summary": summary,
                    "results": [
                        {
                            "group_id": r.group_id,
                            "variant_id": r.variant_id,
                            "style": r.style,
                            "status": r.status,
                            "schema_valid": r.schema_valid,
                            "semantic_exact_match": r.semantic_exact_match,
                            "diffs": r.diffs,
                            "validation_errors": r.validation_errors,
                            "attempts": r.attempts,
                        }
                        for r in results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nSaved: {report_path}")
    except Exception as exc:  # pragma: no cover - best-effort convenience only
        print(f"\n(could not save report: {exc})")

    return 0 if summary["semantic_exact_match_rate"] == 1.0 or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
