"""
Validation helpers for workout plan YAML.

Provides schema and semantic checks for YAML plans before direct build
or optional template export.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

import yaml

from .plan_domain import ALLOWED_INTENSITY, KNOWN_PACE_CONSTANTS, STEP_REQUIRED_FIELDS
from .plan_schema import _is_valid_pace, _pace_to_seconds

# ---------------------------------------------------------------------------
# Pydantic structural validation (optional — gracefully skipped if unavailable)
# ---------------------------------------------------------------------------

def _loc_to_path(loc: tuple) -> str:
    """Convert a Pydantic error location tuple to a dot/bracket path string."""
    parts: list[str] = []
    for part in loc:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        elif parts:
            parts.append(f".{part}")
        else:
            parts.append(str(part))
    return "".join(parts)


_PYDANTIC_TYPE_TO_CATEGORY: dict[str, str] = {
    "missing": "missing_field",
    "literal_error": "unsupported_step_type",
    "string_too_long": "invalid_value",
    "greater_than": "invalid_value",
    "greater_than_equal": "invalid_value",
    "less_than": "invalid_value",
    "less_than_equal": "invalid_value",
    "int_type": "schema_error",
    "float_type": "schema_error",
    "str_type": "schema_error",
    "bool_type": "schema_error",
    "list_type": "schema_error",
    "value_error": "invalid_value",
}


def _validate_with_pydantic(data: Any) -> List[ValidationIssue]:
    """Run Pydantic structural validation and return issues. Returns [] on success."""
    try:
        from pydantic import ValidationError as PydanticValidationError

        from .plan_schema import WorkoutPlanSchema

        WorkoutPlanSchema.model_validate(data)
        return []
    except Exception as exc:
        # Import error (pydantic not installed) or unexpected error — skip silently
        try:
            from pydantic import ValidationError as PydanticValidationError

            if not isinstance(exc, PydanticValidationError):
                return []
        except ImportError:
            return []

        issues: List[ValidationIssue] = []
        for err in exc.errors():
            path = _loc_to_path(err["loc"])
            category = _PYDANTIC_TYPE_TO_CATEGORY.get(err["type"], "schema_error")
            issues.append(
                ValidationIssue(
                    path=path,
                    detail=err["msg"],
                    category=category,
                    severity="error",
                )
            )
        return issues


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    path: str
    detail: str
    category: str
    severity: str

    @property
    def message(self) -> str:
        if self.path:
            return f"{self.path}: {self.detail}"
        return self.detail


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _issue(
    issues: List[ValidationIssue],
    *,
    path: str,
    detail: str,
    category: str,
    severity: str,
) -> None:
    issues.append(
        ValidationIssue(
            path=path,
            detail=detail,
            category=category,
            severity=severity,
        )
    )


def validate_plan_data_detailed(
    data: Dict[str, Any],
    *,
    enforce_filename_name_match: bool = True,
) -> Tuple[List[ValidationIssue], List[ValidationIssue]]:
    """Validate already parsed YAML plan data and return structured issues."""
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []

    # --- Pydantic structural pass (prepended, non-blocking) ---
    errors.extend(_validate_with_pydantic(data))

    if not isinstance(data, dict):
        _issue(
            errors,
            path="",
            detail="YAML root must be a mapping",
            category="schema_error",
            severity="error",
        )
        return errors, warnings

    workouts = data.get("workouts")
    if not isinstance(workouts, list):
        _issue(
            errors,
            path="workouts",
            detail="missing or invalid workouts list",
            category="missing_field",
            severity="error",
        )
        return errors, warnings
    if not workouts:
        _issue(
            errors,
            path="workouts",
            detail="workouts list is empty",
            category="missing_field",
            severity="error",
        )
        return errors, warnings

    seen_filenames: set[str] = set()
    seen_names: set[str] = set()

    for w_idx, workout in enumerate(workouts):
        prefix = f"workouts[{w_idx}]"
        if not isinstance(workout, dict):
            _issue(
                errors,
                path=prefix,
                detail="workout must be a mapping",
                category="schema_error",
                severity="error",
            )
            continue

        filename = workout.get("filename")
        name = workout.get("name")
        steps = workout.get("steps")

        if not isinstance(filename, str) or not filename.strip():
            _issue(
                errors,
                path=f"{prefix}.filename",
                detail="missing or invalid filename",
                category="missing_field",
                severity="error",
            )
        if not isinstance(name, str) or not name.strip():
            _issue(
                errors,
                path=f"{prefix}.name",
                detail="missing or invalid name",
                category="missing_field",
                severity="error",
            )
        if (
            enforce_filename_name_match
            and isinstance(filename, str)
            and isinstance(name, str)
            and filename != name
        ):
            _issue(
                errors,
                path=prefix,
                detail="filename and name must be identical",
                category="naming_rule_violation",
                severity="error",
            )

        if isinstance(filename, str) and filename in seen_filenames:
            _issue(
                errors,
                path=f"{prefix}.filename",
                detail=f"duplicate filename '{filename}'",
                category="naming_rule_violation",
                severity="error",
            )
        if isinstance(name, str) and name in seen_names:
            _issue(
                errors,
                path=f"{prefix}.name",
                detail=f"duplicate name '{name}'",
                category="naming_rule_violation",
                severity="error",
            )
        if isinstance(filename, str):
            seen_filenames.add(filename)
        if isinstance(name, str):
            seen_names.add(name)

        if not isinstance(steps, list) or not steps:
            _issue(
                errors,
                path=f"{prefix}.steps",
                detail="missing or empty steps list",
                category="missing_field",
                severity="error",
            )
            continue

        for s_idx, step in enumerate(steps):
            s_prefix = f"{prefix}.steps[{s_idx}]"
            if not isinstance(step, dict):
                _issue(
                    errors,
                    path=s_prefix,
                    detail="step must be a mapping",
                    category="schema_error",
                    severity="error",
                )
                continue

            step_type = step.get("type")
            if step_type not in STEP_REQUIRED_FIELDS:
                _issue(
                    errors,
                    path=f"{s_prefix}.type",
                    detail=f"unsupported step type '{step_type}'",
                    category="unsupported_step_type",
                    severity="error",
                )
                continue

            missing = STEP_REQUIRED_FIELDS[step_type] - set(step.keys())
            if missing:
                _issue(
                    errors,
                    path=s_prefix,
                    detail=f"missing required fields {sorted(missing)}",
                    category="missing_field",
                    severity="error",
                )

            intensity = step.get("intensity")
            if intensity is not None and intensity not in ALLOWED_INTENSITY:
                _issue(
                    errors,
                    path=f"{s_prefix}.intensity",
                    detail=f"invalid intensity '{intensity}'",
                    category="invalid_value",
                    severity="error",
                )

            if step_type in {"dist_hr", "dist_pace", "dist_open"}:
                km = step.get("km")
                if not _is_number(km) or km <= 0:
                    _issue(
                        errors,
                        path=f"{s_prefix}.km",
                        detail="km must be > 0",
                        category="invalid_value",
                        severity="error",
                    )

            if step_type in {"time_hr", "time_pace", "time_step"}:
                seconds = step.get("seconds")
                if not _is_number(seconds) or seconds <= 0:
                    _issue(
                        errors,
                        path=f"{s_prefix}.seconds",
                        detail="seconds must be > 0",
                        category="invalid_value",
                        severity="error",
                    )

            if step_type in {"dist_hr", "time_hr"}:
                hr_low = step.get("hr_low")
                hr_high = step.get("hr_high")
                if not _is_number(hr_low) or not _is_number(hr_high):
                    _issue(
                        errors,
                        path=s_prefix,
                        detail="hr_low/hr_high must be numeric",
                        category="hr_range_issue",
                        severity="error",
                    )
                else:
                    if hr_low <= 0 or hr_high <= 0 or hr_low >= hr_high:
                        _issue(
                            errors,
                            path=s_prefix,
                            detail=f"invalid HR range {hr_low}-{hr_high}",
                            category="hr_range_issue",
                            severity="error",
                        )
                    if hr_low < 30 or hr_high > 240:
                        _issue(
                            warnings,
                            path=s_prefix,
                            detail=f"unusual HR range {hr_low}-{hr_high}",
                            category="hr_range_issue",
                            severity="warning",
                        )

            if step_type in {"dist_pace", "time_pace"}:
                pf_valid = _is_valid_pace(step.get("pace_fast"))
                ps_valid = _is_valid_pace(step.get("pace_slow"))
                if not pf_valid:
                    _issue(
                        errors,
                        path=f"{s_prefix}.pace_fast",
                        detail="invalid pace_fast",
                        category="pace_format_issue",
                        severity="error",
                    )
                if not ps_valid:
                    _issue(
                        errors,
                        path=f"{s_prefix}.pace_slow",
                        detail="invalid pace_slow",
                        category="pace_format_issue",
                        severity="error",
                    )
                if pf_valid and ps_valid:
                    pf_sec = _pace_to_seconds(step["pace_fast"])
                    ps_sec = _pace_to_seconds(step["pace_slow"])
                    if pf_sec >= ps_sec:
                        _issue(
                            errors,
                            path=s_prefix,
                            detail=f"pace_fast '{step['pace_fast']}' must be faster (lower) than pace_slow '{step['pace_slow']}'",
                            category="pace_format_issue",
                            severity="error",
                        )

            if step_type == "repeat":
                back_to_offset = step.get("back_to_offset")
                count = step.get("count")
                if not isinstance(back_to_offset, int) or back_to_offset < 0:
                    _issue(
                        errors,
                        path=f"{s_prefix}.back_to_offset",
                        detail="back_to_offset must be integer >= 0",
                        category="repeat_semantics_error",
                        severity="error",
                    )
                elif back_to_offset >= s_idx:
                    _issue(
                        errors,
                        path=f"{s_prefix}.back_to_offset",
                        detail="back_to_offset must point to a previous step",
                        category="repeat_semantics_error",
                        severity="error",
                    )

                if not isinstance(count, int) or count <= 0:
                    _issue(
                        errors,
                        path=f"{s_prefix}.count",
                        detail="count must be integer > 0",
                        category="repeat_semantics_error",
                        severity="error",
                    )

            if step_type == "sbu_block":
                drills = step.get("drills")
                if drills is not None:
                    if not isinstance(drills, list) or not drills:
                        _issue(
                            errors,
                            path=f"{s_prefix}.drills",
                            detail="drills must be a non-empty list when provided",
                            category="drill_configuration_issue",
                            severity="error",
                        )
                    else:
                        for d_idx, drill in enumerate(drills):
                            d_prefix = f"{s_prefix}.drills[{d_idx}]"
                            if not isinstance(drill, dict):
                                _issue(
                                    errors,
                                    path=d_prefix,
                                    detail="drill must be a mapping",
                                    category="drill_configuration_issue",
                                    severity="error",
                                )
                                continue
                            drill_name = drill.get("name")
                            seconds = drill.get("seconds", 60)
                            reps = drill.get("reps", 2)
                            if not isinstance(drill_name, str) or not drill_name.strip():
                                _issue(
                                    errors,
                                    path=f"{d_prefix}.name",
                                    detail="missing or invalid drill name",
                                    category="drill_configuration_issue",
                                    severity="error",
                                )
                            elif len(drill_name) > 12:
                                _issue(
                                    warnings,
                                    path=f"{d_prefix}.name",
                                    detail="name longer than 12 chars for Garmin display",
                                    category="drill_configuration_issue",
                                    severity="warning",
                                )
                            if not isinstance(seconds, int) or seconds <= 0:
                                _issue(
                                    errors,
                                    path=f"{d_prefix}.seconds",
                                    detail="seconds must be integer > 0",
                                    category="drill_configuration_issue",
                                    severity="error",
                                )
                            if not isinstance(reps, int) or reps <= 0:
                                _issue(
                                    errors,
                                    path=f"{d_prefix}.reps",
                                    detail="reps must be integer > 0",
                                    category="drill_configuration_issue",
                                    severity="error",
                                )

    return errors, warnings


def validate_plan_data(
    data: Dict[str, Any],
    *,
    enforce_filename_name_match: bool = True,
) -> Tuple[List[str], List[str]]:
    """Validate already parsed YAML plan data."""
    errors, warnings = validate_plan_data_detailed(
        data,
        enforce_filename_name_match=enforce_filename_name_match,
    )
    return [issue.message for issue in errors], [issue.message for issue in warnings]


def parse_and_validate_yaml_text_detailed(
    yaml_text: str,
    *,
    enforce_filename_name_match: bool = True,
) -> Tuple[Dict[str, Any] | None, List[ValidationIssue], List[ValidationIssue]]:
    """Parse YAML text and run schema + semantic validation with structured issues."""
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return None, [
            ValidationIssue(
                path="",
                detail=f"YAML parse error: {exc}",
                category="schema_error",
                severity="error",
            )
        ], []

    if data is None:
        return None, [
            ValidationIssue(
                path="",
                detail="YAML is empty",
                category="schema_error",
                severity="error",
            )
        ], []

    errors, warnings = validate_plan_data_detailed(
        data,
        enforce_filename_name_match=enforce_filename_name_match,
    )
    return data, errors, warnings


def parse_and_validate_yaml_text(
    yaml_text: str,
    *,
    enforce_filename_name_match: bool = True,
) -> Tuple[Dict[str, Any] | None, List[str], List[str]]:
    """Parse YAML text and run schema + semantic validation."""
    data, errors, warnings = parse_and_validate_yaml_text_detailed(
        yaml_text,
        enforce_filename_name_match=enforce_filename_name_match,
    )
    return data, [issue.message for issue in errors], [issue.message for issue in warnings]


def group_issues_by_category(issues: Sequence[ValidationIssue]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for issue in issues:
        grouped.setdefault(issue.category, []).append(issue.message)
    return grouped
