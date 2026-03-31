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


def create_system_prompt(
    include_text_variations: bool = False,
    user_profile: Optional[dict[str, Any]] = None,
    source_text: str | None = None,
) -> str:
    """Create the strict LLM system prompt."""
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
    if examples:
        sections.append(examples)
    sections.append(
        "\n".join(
            [
                "FINAL INSTRUCTIONS",
                "- choose only listed keys and enum values",
                "- do not invent fields, step types, intensity values, or second documents",
                "- use repeat only for one flat interval+recovery loop",
                "- back_to_offset is 0-based step index of the FIRST step in the repeating block",
                "  example: [WU(0), interval(1), recovery(2), repeat back_to_offset=1 count=N(3)]",
                "- explicit pace -> dist_pace/time_pace; explicit HR -> dist_hr/time_hr",
                "- time-based intervals (мин/seconds) -> time_pace or time_step, not dist_pace",
                "- ALWAYS set intensity on dist_hr/dist_pace/time_hr/time_pace steps; never omit it",
                "- multi-step workout: first content step → intensity warmup; last non-repeat step → intensity cooldown",
                "- sbu_block drills: list of {name, seconds, reps} ONLY — no 'type' key, no step keys",
                "",
                "VALIDATION CHECKLIST (before returning YAML):",
                "  1. All filenames are UNIQUE across workouts",
                "  2. filename == name (exactly identical)",
                "  3. Filenames follow pattern: W{week}_{MM-DD}_{DayName}_{Type}_{Details}",
                "  4. All distances (km) are > 0 (no zeros or negatives)",
                "  5. All durations (seconds) are > 0 (no zeros or negatives)",
                "  6. For dist_hr/time_hr: hr_low < hr_high (CRITICAL!)",
                "  7. For dist_hr/time_hr: 30 ≤ hr_low and hr_high ≤ 240",
                "  8. For dist_pace/time_pace: pace values are quoted strings \"MM:SS\"",
                "  9. For dist_pace/time_pace: MM ≥ 1, SS ∈ [00-59]",
                " 10. NEVER mix hr_* with pace_* in the same step",
                " 11. For sbu_block: drill names ≤ 12 characters only",
                " 12. For sbu_block: drills have ONLY {name, seconds, reps} — no 'type'",
                " 13. For repeat: back_to_offset < current step index",
                " 14. For repeat: back_to_offset points to a valid step (≥ 0)",
                " 15. intensity values (if used) are one of: active, warmup, cooldown, recovery",
                " 16. No nested repeat blocks (one repeat per section only)",
            ]
        )
    )
    return "\n\n".join(section.strip() for section in sections if section.strip())


def get_system_prompt(
    include_text_variations: bool = False,
    source_text: str | None = None,
) -> str:
    """Create the strict system prompt, loading user HR zones if available."""
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
