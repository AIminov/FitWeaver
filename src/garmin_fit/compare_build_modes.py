"""
Compare direct FIT build output with the legacy templates-based path.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from . import build_fits
from . import build_from_plan
from . import generate_from_yaml
from . import orchestrator as orchestrator_module
from . import plan_artifacts as plan_artifacts_module
from . import state_manager
from .check_fit import validate_fit_file
from .logging_utils import setup_file_logging as _setup_logging
from .plan_artifacts import get_build_mode_compare_path


logger = logging.getLogger(__name__)

WORKOUT_COMPARE_FIELDS = (
    "sport",
    "num_valid_steps",
)

STEP_COMPARE_FIELDS = (
    "message_index",
    "wkt_step_name",
    "duration_type",
    "duration_value",
    "target_type",
    "target_value",
    "custom_target_value_low",
    "custom_target_value_high",
    "intensity",
    "notes",
)


def setup_file_logging(run_id=None):
    """Setup file logging for build mode comparison."""
    return _setup_logging(prefix="compare_build_modes", run_id=run_id)


def compare_build_modes(
    yaml_path: Path,
    *,
    validate_strict: bool = False,
    run_id: str | None = None,
    artifacts_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Compare the direct pipeline against the legacy templates path for one YAML plan.

    Returns:
        dict with compare summary, per-mode snapshots, mismatch list, and report path.
    """
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML plan not found: {yaml_path}")

    compare_report_path = get_build_mode_compare_path(yaml_path, artifacts_dir=artifacts_dir)
    compare_report_path.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        direct = _run_mode_in_temp(
            yaml_path,
            build_mode="direct",
            validate_strict=validate_strict,
            temp_root=temp_root,
        )
        templates = _run_mode_in_temp(
            yaml_path,
            build_mode="templates",
            validate_strict=validate_strict,
            temp_root=temp_root,
        )

    mismatches = _collect_mismatches(direct, templates)
    matches = direct["success"] and templates["success"] and not mismatches
    generated_at = datetime.now(timezone.utc).isoformat()

    report = {
        "report_version": 1,
        "run_id": run_id,
        "generated_at": generated_at,
        "source_yaml_path": str(yaml_path),
        "validate_strict": validate_strict,
        "matches": matches,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "direct": direct,
        "templates": templates,
    }
    compare_report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report["compare_report_path"] = compare_report_path
    return report


def _run_mode_in_temp(
    yaml_path: Path,
    *,
    build_mode: str,
    validate_strict: bool,
    temp_root: Path,
) -> dict[str, Any]:
    runtime_root = temp_root / build_mode
    output_dir = runtime_root / "Output_fit"
    templates_dir = runtime_root / "Workout_templates"
    artifacts_dir = runtime_root / "Build_artifacts"
    state_file = runtime_root / "state.json"
    lock_file = runtime_root / "state.lock"

    output_dir.mkdir(parents=True, exist_ok=True)
    templates_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    original_build_fit = build_from_plan.build_fit_from_workout

    def _build_fit_to_temp(workout, serial_number, timestamp):
        return original_build_fit(
            workout,
            serial_number,
            timestamp,
            output_dir=output_dir,
        )

    with ExitStack() as stack:
        stack.enter_context(patch.object(orchestrator_module, "OUTPUT_DIR", output_dir))
        stack.enter_context(patch.object(orchestrator_module, "TEMPLATES_DIR", templates_dir))
        stack.enter_context(patch.object(build_from_plan, "OUTPUT_DIR", output_dir))
        stack.enter_context(patch.object(build_fits, "OUTPUT_DIR", output_dir))
        stack.enter_context(patch.object(build_fits, "TEMPLATES_DIR", templates_dir))
        stack.enter_context(patch.object(generate_from_yaml, "TEMPLATES_DIR", templates_dir))
        stack.enter_context(patch.object(plan_artifacts_module, "ARTIFACTS_DIR", artifacts_dir))
        stack.enter_context(patch.object(state_manager, "STATE_FILE", state_file))
        stack.enter_context(patch.object(state_manager, "LOCK_FILE", lock_file))
        stack.enter_context(
            patch.object(
                build_from_plan,
                "build_fit_from_workout",
                new=_build_fit_to_temp,
            )
        )
        result = orchestrator_module.run_generation_pipeline(
            yaml_path,
            validate_strict=validate_strict,
            cleanup_first=True,
            auto_archive=False,
            build_mode=build_mode,
        )

    fit_summaries = {
        fit_path.name: _summarize_fit_validation(validate_fit_file(fit_path, strict=False))
        for fit_path in sorted(output_dir.glob("*.fit"))
    }

    return {
        "build_mode": result["build_mode"],
        "success": result["success"],
        "built_count": result["built_count"],
        "build_total_count": result["build_total_count"],
        "valid_count": result["valid_count"],
        "total_count": result["total_count"],
        "template_export_count": result["template_export_count"],
        "template_export_total_count": result["template_export_total_count"],
        "fit_files": sorted(fit_summaries),
        "fit_summaries": fit_summaries,
        "errors": list(result["errors"]),
    }


def _summarize_fit_validation(results: dict[str, Any]) -> dict[str, Any]:
    workout = results.get("workout") or {}
    steps = results.get("steps") or []

    return {
        "valid": bool(results.get("valid")),
        "workout": {
            "name": workout.get("wkt_name") or workout.get("workout_name"),
            **{
                field: workout.get(field)
                for field in WORKOUT_COMPARE_FIELDS
                if workout.get(field) is not None
            },
        },
        "steps": [_normalize_step(step) for step in steps],
    }


def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    return {
        field: step.get(field)
        for field in STEP_COMPARE_FIELDS
        if step.get(field) is not None
    }


def _collect_mismatches(direct: dict[str, Any], templates: dict[str, Any]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []

    for snapshot in (direct, templates):
        if not snapshot["success"]:
            mismatches.append(
                {
                    "type": "mode_failure",
                    "mode": snapshot["build_mode"],
                    "errors": snapshot["errors"],
                }
            )

    for field in ("built_count", "build_total_count", "valid_count", "total_count"):
        if direct[field] != templates[field]:
            mismatches.append(
                {
                    "type": "count_mismatch",
                    "field": field,
                    "direct": direct[field],
                    "templates": templates[field],
                }
            )

    direct_files = set(direct["fit_files"])
    template_files = set(templates["fit_files"])
    if direct_files != template_files:
        mismatches.append(
            {
                "type": "fit_file_set_mismatch",
                "direct_only": sorted(direct_files - template_files),
                "templates_only": sorted(template_files - direct_files),
            }
        )

    for fit_name in sorted(direct_files & template_files):
        direct_summary = direct["fit_summaries"][fit_name]
        template_summary = templates["fit_summaries"][fit_name]
        if direct_summary != template_summary:
            mismatches.append(
                {
                    "type": "fit_content_mismatch",
                    "fit_file": fit_name,
                    "direct": direct_summary,
                    "templates": template_summary,
                }
            )

    return mismatches


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Compare direct and legacy template Garmin FIT build paths",
    )
    parser.add_argument("yaml_path", help="Path to YAML plan")
    parser.add_argument(
        "--validate-mode",
        choices=["soft", "strict"],
        default="soft",
        help="Validation mode: soft (warnings allowed) or strict (warnings fail)",
    )
    parser.add_argument("--run-id", help="Optional run identifier for logs/report")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    setup_file_logging(run_id=args.run_id)

    result = compare_build_modes(
        args.yaml_path,
        validate_strict=args.validate_mode == "strict",
        run_id=args.run_id,
    )
    logger.info(f"Compare report: {result['compare_report_path']}")
    if result["matches"]:
        logger.info("Direct and legacy template build outputs match.")
        sys.exit(0)

    logger.error("Build mode comparison found mismatches.")
    for mismatch in result["mismatches"]:
        logger.error(f"  - {mismatch['type']}")
    sys.exit(1)
