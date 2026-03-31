"""
Shared application services for plan generation and preview.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import yaml

from .llm.client import GeneratedYamlResult, UnifiedLLMClient
from .llm.prompt import get_sbu_drills_prompt
from .plan_domain import plan_from_data
from .plan_processing import repair_plan_data
from .plan_validator import validate_plan_data


def build_plan_draft(
    llm_client: UnifiedLLMClient,
    plan_text: str,
    *,
    max_retries: int = 3,
) -> GeneratedYamlResult:
    """Generate a previewable YAML draft from raw plan text."""
    return llm_client.generate_yaml_draft(plan_text, max_retries=max_retries)


def count_workouts(data: dict[str, Any] | None) -> int:
    """Count workouts in parsed plan data."""
    if not isinstance(data, dict):
        return 0
    return len(plan_from_data(data).workouts)


def has_default_sbu_block(data: dict[str, Any] | None) -> bool:
    """Return True when plan still contains unresolved default SBU blocks."""
    if not isinstance(data, dict):
        return False

    for workout in plan_from_data(data).workouts:
        for step in workout.steps:
            if step.step_type == "sbu_block" and not step.drills:
                return True
    return False


def apply_custom_sbu_choice(
    llm_client: UnifiedLLMClient,
    yaml_data: dict[str, Any],
    user_text: str,
) -> GeneratedYamlResult:
    """Parse custom drill text and inject it into default SBU blocks."""
    prompt = get_sbu_drills_prompt(user_text)
    drills_yaml = llm_client.generate_custom(prompt)
    if not drills_yaml:
        raise ValueError("Could not parse drills")

    drills_data = yaml.safe_load(drills_yaml)
    drills_list = drills_data.get("drills", []) if isinstance(drills_data, dict) else []
    if not isinstance(drills_list, list) or not drills_list:
        raise ValueError("Drills list is empty")

    updated_data = deepcopy(yaml_data)
    applied = False
    for workout in updated_data.get("workouts", []):
        if not isinstance(workout, dict):
            continue
        for step in workout.get("steps", []):
            if isinstance(step, dict) and step.get("type") == "sbu_block" and not step.get("drills"):
                step["drills"] = deepcopy(drills_list)
                applied = True

    if not applied:
        raise ValueError("No default SBU blocks found to update")

    repaired_data, repairs = repair_plan_data(updated_data)
    errors, warnings = validate_plan_data(repaired_data, enforce_filename_name_match=True)
    if errors:
        joined = "; ".join(errors[:5])
        raise ValueError(f"Custom SBU YAML is still invalid: {joined}")

    rendered_yaml = yaml.safe_dump(
        repaired_data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return GeneratedYamlResult(
        yaml_text=rendered_yaml,
        data=repaired_data,
        warnings=warnings,
        repairs=repairs,
        attempts=1,
    )


def format_plan_preview(result: GeneratedYamlResult, *, max_chars: int = 1500) -> str:
    """Render a compact preview with repair, warning, and ambiguity context."""
    parts: list[str] = []

    if result.repairs:
        repair_lines = "\n".join(f"- {line}" for line in result.repairs[:5])
        parts.append(f"Auto-repair:\n{repair_lines}")

    if result.ambiguities:
        ambiguity_lines = "\n".join(f"- {line}" for line in result.ambiguities[:5])
        parts.append(f"Ambiguities:\n{ambiguity_lines}")

    if result.warnings:
        warning_lines = "\n".join(f"- {line}" for line in result.warnings[:5])
        parts.append(f"Warnings:\n{warning_lines}")

    yaml_preview = result.yaml_text or ""
    if len(yaml_preview) > max_chars:
        yaml_preview = yaml_preview[:max_chars] + "..."
    parts.append(f"Preview:\n{yaml_preview}")
    return "\n\n".join(parts)
