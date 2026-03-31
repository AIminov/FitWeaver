"""
Helpers for repaired YAML and machine-readable build reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import yaml

from .config import ARTIFACTS_DIR
from .plan_processing import repair_plan_data, sanitize_workout_name
from .plan_validator import group_issues_by_category, validate_plan_data_detailed


@dataclass(slots=True)
class PreparedPlanArtifacts:
    source_yaml_path: Path
    repaired_yaml_path: Path
    build_report_path: Path
    raw_yaml_text: str | None = None
    repaired_yaml_text: str | None = None
    planned_workouts: int = 0
    source_matches_repaired: bool = False
    repairs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    error_categories: dict[str, list[str]] = field(default_factory=dict)

    def existing_paths(self) -> list[Path]:
        return [path for path in (self.repaired_yaml_path, self.build_report_path) if path.exists()]


def get_plan_artifact_paths(
    yaml_path: Path,
    *,
    artifacts_dir: Path | None = None,
) -> tuple[Path, Path]:
    yaml_path = Path(yaml_path)
    artifacts_dir = ARTIFACTS_DIR if artifacts_dir is None else Path(artifacts_dir)
    stem = sanitize_workout_name(yaml_path.stem)
    return (
        artifacts_dir / f"{stem}.repaired.yaml",
        artifacts_dir / f"{stem}.build_report.json",
    )


def get_build_mode_compare_path(
    yaml_path: Path,
    *,
    artifacts_dir: Path | None = None,
) -> Path:
    yaml_path = Path(yaml_path)
    artifacts_dir = ARTIFACTS_DIR if artifacts_dir is None else Path(artifacts_dir)
    stem = sanitize_workout_name(yaml_path.stem)
    return artifacts_dir / f"{stem}.build_mode_compare.json"


def prepare_plan_artifacts(
    yaml_path: Path,
    *,
    artifacts_dir: Path | None = None,
) -> PreparedPlanArtifacts:
    yaml_path = Path(yaml_path)
    artifacts_dir = ARTIFACTS_DIR if artifacts_dir is None else Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    repaired_yaml_path, build_report_path = get_plan_artifact_paths(yaml_path, artifacts_dir=artifacts_dir)

    bundle = PreparedPlanArtifacts(
        source_yaml_path=yaml_path,
        repaired_yaml_path=repaired_yaml_path,
        build_report_path=build_report_path,
    )

    if not yaml_path.exists():
        bundle.validation_errors = [f"YAML file not found: {yaml_path}"]
        bundle.error_categories = {"schema_error": bundle.validation_errors[:]}
        repaired_yaml_path.unlink(missing_ok=True)
        return bundle

    bundle.raw_yaml_text = yaml_path.read_text(encoding="utf-8")

    try:
        data = yaml.safe_load(bundle.raw_yaml_text)
    except yaml.YAMLError as exc:
        error = f"YAML parse error: {exc}"
        bundle.validation_errors = [error]
        bundle.error_categories = {"schema_error": [error]}
        repaired_yaml_path.unlink(missing_ok=True)
        return bundle

    if data is None:
        error = "YAML is empty"
        bundle.validation_errors = [error]
        bundle.error_categories = {"schema_error": [error]}
        repaired_yaml_path.unlink(missing_ok=True)
        return bundle

    repaired_data, repair_notes = repair_plan_data(data)
    errors, warnings = validate_plan_data_detailed(
        repaired_data,
        enforce_filename_name_match=True,
    )
    rendered_yaml = yaml.safe_dump(
        repaired_data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    repaired_yaml_path.write_text(rendered_yaml, encoding="utf-8")

    workouts = repaired_data.get("workouts") if isinstance(repaired_data, dict) else None
    bundle.repaired_yaml_text = rendered_yaml
    bundle.planned_workouts = len(workouts) if isinstance(workouts, list) else 0
    bundle.source_matches_repaired = bundle.raw_yaml_text.strip() == rendered_yaml.strip()
    bundle.repairs = repair_notes
    bundle.warnings = [issue.message for issue in warnings]
    bundle.validation_errors = [issue.message for issue in errors]
    bundle.error_categories = group_issues_by_category(errors)
    return bundle


def write_build_report(
    prepared: PreparedPlanArtifacts,
    *,
    build_mode: str,
    validate_strict: bool,
    run_id: str | None,
    success: bool,
    built_count: int,
    build_total_count: int,
    valid_count: int,
    total_count: int,
    fit_files: list[Path],
    errors: list[str],
    template_export_count: int = 0,
    template_export_total_count: int = 0,
    archive_path: Path | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> Path:
    prepared.build_report_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = started_at or datetime.now(timezone.utc)
    finished_at = finished_at or datetime.now(timezone.utc)

    report = {
        "report_version": 1,
        "run_id": run_id,
        "generated_at": finished_at.isoformat(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "source_yaml_path": str(prepared.source_yaml_path),
        "repaired_yaml_path": (
            str(prepared.repaired_yaml_path) if prepared.repaired_yaml_path.exists() else None
        ),
        "archive_path": str(archive_path) if archive_path is not None else None,
        "build_mode": build_mode,
        "validate_strict": validate_strict,
        "success": success,
        "planned_workouts": prepared.planned_workouts,
        "source_matches_repaired": prepared.source_matches_repaired,
        "repairs": prepared.repairs,
        "warnings": prepared.warnings,
        "preparation_validation_errors": prepared.validation_errors,
        "preparation_error_categories": prepared.error_categories,
        "build": {
            "built_count": built_count,
            "build_total_count": build_total_count,
            "fit_files": [path.name for path in fit_files],
        },
        "validation": {
            "valid_count": valid_count,
            "total_count": total_count,
        },
        "template_exports": {
            "generated_count": template_export_count,
            "expected_count": template_export_total_count,
        },
        "errors": errors,
    }
    prepared.build_report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return prepared.build_report_path
