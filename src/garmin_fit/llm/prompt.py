"""
Strict contract-first LLM prompt builder for workout YAML generation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

_LLM_DIR = Path(__file__).parent
LLM_CONTRACT_FILE = _LLM_DIR / "llm_contract.yaml"
STRICT_EXAMPLES_FILE = _LLM_DIR / "strict_examples.yaml"
EXAMPLES_TEXT_FILE = _LLM_DIR / "text_variations.txt"

DEFAULT_WORKOUT_KEYS_EXACT = [
    "filename",
    "name",
    "desc",
    "type_code",
    "distance_km",
    "estimated_duration_min",
    "steps",
]

DEFAULT_STEP_TYPES: dict[str, dict[str, Any]] = {
    "dist_open": {
        "required": ["type", "km"],
        "optional": ["intensity"],
        "fit_duration": "distance",
        "fit_target": "open",
    },
    "dist_hr": {
        "required": ["type", "km", "hr_low", "hr_high"],
        "optional": ["intensity"],
        "fit_duration": "distance",
        "fit_target": "heart_rate",
    },
    "dist_pace": {
        "required": ["type", "km", "pace_fast", "pace_slow"],
        "optional": ["intensity"],
        "fit_duration": "distance",
        "fit_target": "pace",
    },
    "time_open": {
        "required": ["type", "seconds"],
        "optional": ["intensity"],
        "fit_duration": "time",
        "fit_target": "open",
    },
    "time_hr": {
        "required": ["type", "seconds", "hr_low", "hr_high"],
        "optional": ["intensity"],
        "fit_duration": "time",
        "fit_target": "heart_rate",
    },
    "time_pace": {
        "required": ["type", "seconds", "pace_fast", "pace_slow"],
        "optional": ["intensity"],
        "fit_duration": "time",
        "fit_target": "pace",
    },
    "repeat": {
        "required": ["type", "back_to_offset", "count"],
        "optional": [],
        "fit_duration": "repeat",
        "fit_target": "repeat",
    },
    "sbu_block": {
        "required": ["type", "drills"],
        "optional": [],
        "fit_duration": "composite",
        "fit_target": "open",
    },
}


SBU_DRILLS_PROMPT_PREFIX = """You are a running drill parser. Convert the user's exercise description into YAML format.

## Output Format
```yaml
drills:
- name: "Exercise name (short, max 12 chars for watch display)"
  seconds: <duration in seconds>
  reps: <number of repetitions>
```

## Rules
1. Keep drill names SHORT (max 12 characters) for Garmin watch display
2. If duration is not specified, use 60 seconds
3. If reps are not specified, use 2
4. Output ONLY valid YAML inside ```yaml ... ``` block
5. Abbreviate long names if needed

## User Input
"""


def load_llm_contract() -> dict[str, Any]:
    """Load the strict contract used to constrain LLM output."""
    if not LLM_CONTRACT_FILE.exists():
        raise FileNotFoundError(f"LLM contract file not found: {LLM_CONTRACT_FILE}")

    data = yaml.safe_load(LLM_CONTRACT_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("LLM contract must be a YAML mapping")

    output = data.setdefault("output", {})
    output.setdefault("workout_keys_exact", list(DEFAULT_WORKOUT_KEYS_EXACT))

    step_types = data.get("step_types", {})
    normalized_step_types: dict[str, dict[str, Any]] = {
        name: dict(spec) for name, spec in DEFAULT_STEP_TYPES.items()
    }
    if isinstance(step_types, dict):
        for step_name, step_spec in step_types.items():
            if isinstance(step_spec, dict):
                normalized_step_types[step_name] = {
                    **normalized_step_types.get(step_name, {}),
                    **step_spec,
                }
            else:
                normalized_step_types[step_name] = {"required": [], "optional": []}
    data["step_types"] = normalized_step_types
    return data


def load_strict_examples(
    include_text_variations: bool = False,
    *,
    source_text: str | None = None,
    max_examples: int = 2,
) -> str:
    """Load only the most relevant compact examples for the current source block."""
    sections: list[str] = []

    if STRICT_EXAMPLES_FILE.exists():
        payload = yaml.safe_load(STRICT_EXAMPLES_FILE.read_text(encoding="utf-8")) or {}
        examples = payload.get("examples", [])
        selected = _select_examples(examples, source_text=source_text, max_examples=max_examples)
        if selected:
            rendered = []
            for example in selected:
                rendered.append(
                    "\n".join(
                        [
                            f"EXAMPLE {example['id']}",
                            "INPUT:",
                            str(example["input"]).strip(),
                            "OUTPUT:",
                            str(example["output"]).strip(),
                        ]
                    )
                )
            sections.append("EXAMPLES\n" + "\n\n".join(rendered))
    else:
        logger.warning(f"Strict LLM examples file not found: {STRICT_EXAMPLES_FILE}")

    if include_text_variations and EXAMPLES_TEXT_FILE.exists():
        lines = EXAMPLES_TEXT_FILE.read_text(encoding="utf-8").splitlines()
        compact_variations = "\n".join(line for line in lines[:6] if line.strip())
        if compact_variations:
            sections.append("SHORT INPUT VARIATIONS\n" + compact_variations)

    return "\n\n".join(sections)


def _render_list(title: str, values: list[str]) -> list[str]:
    lines = [title]
    lines.extend(f"- {value}" for value in values)
    return lines


def render_llm_contract(
    contract: dict[str, Any],
    *,
    user_profile: Optional[dict[str, Any]] = None,
) -> str:
    """Render structured contract YAML into a compact prompt section."""
    output = contract.get("output", {})
    naming = contract.get("naming", {})
    step_types = contract.get("step_types", {})
    type_codes = list(contract.get("allowed_type_codes", []))
    intensities = list(contract.get("allowed_intensity", []))
    russian_hints = list(contract.get("russian_hints", []))
    forbidden_patterns = list(contract.get("forbidden_patterns", []))

    lines: list[str] = [
        "STRICT YAML CONTRACT",
        f"root={output.get('root_key', 'workouts')}; start={output.get('root_key', 'workouts')}:; yaml_only=true; skip_rest_days=true",
        "workout_keys=" + ",".join(output.get("workout_keys_exact", [])),
        "forbid_extra_workout_keys=plan,mapped_to,date,notes",
        "filename_equals_name=true; unique_names=true",
        "known_name_pattern=" + naming.get("known_date_pattern", "W{calendar_week}_{MM-DD}_{DayName}_{Type}_{Details}"),
        "fallback_name_pattern=" + naming.get("fallback_pattern", "N{order}_{DayName?}_{Type}_{Details}"),
        "date_token=" + naming.get("date_output_token", "MM-DD"),
        "calendar_week_rule=" + naming.get("calendar_week_rule", "Jan 1-7 = W01, Jan 8-14 = W02, etc."),
        "source_date_forms=" + ", ".join(naming.get("supported_source_date_forms", [])),
        "day_names=" + ", ".join(naming.get("day_names_allowed", [])),
        "type_code_allowed=" + ", ".join(type_codes),
        "intensity_allowed=" + ", ".join(intensities),
        "STEP SCHEMA",
    ]

    for step_name, spec in step_types.items():
        required = ", ".join(spec.get("required", [])) or "none"
        optional = ", ".join(spec.get("optional", [])) or "none"
        duration = spec.get("fit_duration", "").lower()
        target = spec.get("fit_target", "").lower()
        lines.append(f"- {step_name}: req={required}; opt={optional}; fit={duration}/{target}")
        for note in spec.get("notes", []):
            lines.append(f"  {note}")

    if user_profile and isinstance(user_profile.get("hr_zones"), dict):
        lines.extend(
            [
                "PERSONAL HR ZONES",
            ]
        )
        for zone_name, zone_data in user_profile["hr_zones"].items():
            if isinstance(zone_data, dict) and "low" in zone_data and "high" in zone_data:
                lines.append(f"- {zone_name}={zone_data['low']}-{zone_data['high']} bpm")

    lines.extend(
        [
            "RUSSIAN PLAN HINTS",
        ]
    )
    lines.extend(f"- {item}" for item in russian_hints)
    lines.extend(
        [
            "FORBIDDEN OUTPUT PATTERNS",
        ]
    )
    lines.extend(f"- {item}" for item in forbidden_patterns)

    return "\n".join(lines)


def _build_json_schema_section() -> str:
    """
    Generate a compact JSON Schema section from Pydantic models.
    Derived programmatically — always in sync with plan_schema.py.
    """
    try:

        from ..plan_schema import WorkoutPlanSchema

        schema = WorkoutPlanSchema.model_json_schema()
        defs = schema.get("$defs", {})

        lines = ["MACHINE-READABLE STEP SCHEMA"]
        step_models = [
            "DistHrStep", "TimeHrStep", "DistPaceStep", "TimePaceStep",
            "DistOpenStep", "TimeStepStep", "OpenStep", "RepeatStep", "SbuBlockStep",
        ]
        for model_name in step_models:
            model_def = defs.get(model_name, {})
            props = model_def.get("properties", {})
            required = set(model_def.get("required", []))
            type_val = props.get("type", {}).get("const", "?")
            fields = []
            for field_name, field_info in props.items():
                if field_name == "type":
                    continue
                # Resolve type from anyOf (optional fields) or direct type
                any_of = field_info.get("anyOf", [])
                if any_of:
                    ftype = next(
                        (x.get("type", "") for x in any_of if x.get("type") != "null"),
                        "any",
                    )
                else:
                    ftype = field_info.get("type", "any")
                marker = "req" if field_name in required else "opt"
                fields.append(f"{field_name}({marker}:{ftype})")
            lines.append(f"- {type_val}: {', '.join(fields)}")
        return "\n".join(lines)
    except Exception:
        return ""


def get_plan_json_schema() -> dict[str, Any]:
    """
    Return the full JSON Schema for a workout plan (generated from Pydantic models).

    Useful for embedding in ChatGPT / Claude prompts when generating YAML manually:

        import json
        from garmin_fit.llm.prompt import get_plan_json_schema
        print(json.dumps(get_plan_json_schema(), indent=2))
    """
    from ..plan_schema import WorkoutPlanSchema

    return WorkoutPlanSchema.model_json_schema()


def create_system_prompt(
    include_text_variations: bool = False,
    user_profile: Optional[dict[str, Any]] = None,
    source_text: str | None = None,
    include_json_schema: bool = False,
) -> str:
    """Create the strict LLM system prompt.

    Args:
        include_text_variations: Include text variation examples.
        user_profile: User HR zone profile (optional).
        source_text: Source plan text for targeted example selection.
        include_json_schema: Inject a compact machine-readable schema section
            derived from Pydantic models. Recommended for capable models
            (GPT-4, Claude). Disable for small local LLMs to save context.
    """
    contract = load_llm_contract()
    contract_block = render_llm_contract(contract, user_profile=user_profile)
    examples = load_strict_examples(
        include_text_variations=include_text_variations,
        source_text=source_text,
        max_examples=2 if source_text else 3,
    )

    sections = [
        "Convert running plan text into strict YAML for Garmin workouts.",
        "Return only YAML. No reasoning. No markdown.",
        contract_block,
    ]

    if include_json_schema:
        schema_section = _build_json_schema_section()
        if schema_section:
            sections.append(schema_section)
    if examples:
        sections.append(examples)
    sections.append(
        "\n".join(
            [
                "FINAL RULES",
                "- only listed keys/enums; no invented fields or second documents",
                "- pace(explicit)->dist_pace/time_pace; HR(explicit)->dist_hr/time_hr",
                "- time intervals->time_hr/time_pace, not dist_*",
                "- intensity required on dist_hr/dist_pace/time_hr/time_pace; first step=warmup, last=cooldown",
                "- sbu_block drills: {name,seconds,reps} only — no 'type' key",
                "- repeat: back_to_offset=0-based index of first repeating step; no nested repeats",
                "VALIDATE: filenames unique; filename==name; pattern W{wk}_{MM-DD}_{Day}_{Type}_{Detail}",
                "dist/seconds>0; hr_low<hr_high; 30≤hr≤240; pace=\"MM:SS\"; no mixed hr*/pace*",
                "sbu drill name≤12chars; repeat back_to_offset<step_idx",
            ]
        )
    )
    return "\n\n".join(section.strip() for section in sections if section.strip())


def get_system_prompt(
    include_text_variations: bool = False,
    source_text: str | None = None,
    include_json_schema: bool = False,
) -> str:
    """Create the strict system prompt, loading user HR zones if available.

    Args:
        include_text_variations: Include text variation examples.
        source_text: Source plan text for targeted example selection.
        include_json_schema: Inject compact Pydantic-derived schema section.
            Recommended for GPT-4 / Claude. Off by default for local LLMs.
    """
    profile = None
    try:
        from ..workout_utils import load_user_profile

        profile = load_user_profile()
    except Exception:
        profile = None

    return create_system_prompt(
        include_text_variations=include_text_variations,
        user_profile=profile,
        source_text=source_text,
        include_json_schema=include_json_schema,
    )


def get_sbu_drills_prompt(user_text: str) -> str:
    """Return prompt for SBU drill parsing. Safe against braces in user text."""
    return SBU_DRILLS_PROMPT_PREFIX + str(user_text)


def _select_examples(
    examples: list[dict[str, Any]],
    *,
    source_text: str | None,
    max_examples: int,
) -> list[dict[str, Any]]:
    if not examples:
        return []
    if not source_text:
        return examples[:max_examples]

    lowered = source_text.lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    unmatched: list[dict[str, Any]] = []
    for example in examples:
        score = 0
        for token in example.get("match_any", []):
            if str(token).lower() in lowered:
                score += 1
        if score > 0:
            scored.append((score, example))
        else:
            unmatched.append(example)

    if not scored:
        return examples[:max_examples]

    scored.sort(key=lambda item: item[0], reverse=True)
    return [example for _, example in scored[:max_examples]]


SYSTEM_PROMPT = create_system_prompt(include_text_variations=False)
