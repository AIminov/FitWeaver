"""
Normalization and repair helpers for plan text and YAML data.
"""

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .plan_domain import INTENSITY_ALIASES, INTENSITY_DEFAULTS, STEP_TYPE_ALIASES

FILENAME_SAFE_RE = re.compile(r"[^\w.-]+", re.UNICODE)

# Step types where intensity should always be set but LLM may omit it.
# Positional heuristic is used: first step → warmup, last non-repeat step → cooldown, else → active.
_POSITIONAL_INTENSITY_TYPES = frozenset({"dist_hr", "dist_pace", "time_hr", "time_pace"})
HR_CAP_ONLY_DEFAULT_LOW = 80
INTERVAL_MULTIPLIER_RE = re.compile(r"(?<=\d)\s*[xX\u0445\u0425\u00D7]\s*(?=\d)")
MULTISPACE_RE = re.compile(r"[ \t]{2,}")
TOO_MANY_BLANKS_RE = re.compile(r"\n{3,}")
PACE_RE = re.compile(r"^\s*(\d{1,2})\s*[:.,-]\s*(\d{1,2})\s*$")
PACE_SPACED_RE = re.compile(r"^\s*(\d{1,2})\s+(\d{1,2})\s*$")
INT_RE = re.compile(r"^\s*-?\d+\s*$")
FLOAT_RE = re.compile(r"^\s*-?\d+(?:[.,]\d+)?\s*$")
WEEK_PREFIX_TOKEN_RE = re.compile(r"^[Ww]\d{1,3}$")
SEQUENCE_PREFIX_TOKEN_RE = re.compile(r"^[Nn]\d{1,3}$")
SEQUENCE_TOKEN_RE = re.compile(r"^\d{1,3}$")
DAY_MONTH_DOTTED_RE = re.compile(r"^(?P<day>\d{1,2})\.(?P<month>\d{1,2})(?:\.(?P<year>\d{2,4}))?$")
MONTH_DAY_DASHED_RE = re.compile(r"^(?P<month>\d{1,2})-(?P<day>\d{1,2})$")
YEAR_TOKEN_RE = re.compile(r"^\d{2,4}$")

REFERENCE_WEEK_YEAR = date.today().year

WEEKDAY_ALIASES = {
    "mon": "Mon",
    "monday": "Mon",
    "пн": "Mon",
    "пон": "Mon",
    "понед": "Mon",
    "понедельник": "Mon",
    "tue": "Tue",
    "tues": "Tue",
    "tuesday": "Tue",
    "вт": "Tue",
    "втор": "Tue",
    "вторник": "Tue",
    "wed": "Wed",
    "wednesday": "Wed",
    "ср": "Wed",
    "среда": "Wed",
    "thu": "Thu",
    "thur": "Thu",
    "thurs": "Thu",
    "thursday": "Thu",
    "чт": "Thu",
    "чет": "Thu",
    "четв": "Thu",
    "четверг": "Thu",
    "fri": "Fri",
    "friday": "Fri",
    "пт": "Fri",
    "пят": "Fri",
    "пятница": "Fri",
    "sat": "Sat",
    "saturday": "Sat",
    "сб": "Sat",
    "суб": "Sat",
    "суббота": "Sat",
    "sun": "Sun",
    "sunday": "Sun",
    "вс": "Sun",
    "воскр": "Sun",
    "воскресенье": "Sun",
}

MONTH_ALIASES = {
    "jan": 1,
    "january": 1,
    "янв": 1,
    "января": 1,
    "январь": 1,
    "feb": 2,
    "february": 2,
    "фев": 2,
    "февраля": 2,
    "февраль": 2,
    "mar": 3,
    "march": 3,
    "мар": 3,
    "марта": 3,
    "март": 3,
    "apr": 4,
    "april": 4,
    "апр": 4,
    "апреля": 4,
    "апрель": 4,
    "may": 5,
    "мая": 5,
    "май": 5,
    "jun": 6,
    "june": 6,
    "июн": 6,
    "июня": 6,
    "июнь": 6,
    "jul": 7,
    "july": 7,
    "июл": 7,
    "июля": 7,
    "июль": 7,
    "aug": 8,
    "august": 8,
    "авг": 8,
    "августа": 8,
    "август": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "сен": 9,
    "сент": 9,
    "сентября": 9,
    "сентябрь": 9,
    "oct": 10,
    "october": 10,
    "окт": 10,
    "октября": 10,
    "октябрь": 10,
    "nov": 11,
    "november": 11,
    "ноя": 11,
    "нояб": 11,
    "ноября": 11,
    "ноябрь": 11,
    "dec": 12,
    "december": 12,
    "дек": 12,
    "декабря": 12,
    "декабрь": 12,
}

SOURCE_REPLACEMENTS = (
    (
        re.compile("\\b\u0440\u0430\u0437\u043c\\.?\\b", re.IGNORECASE),
        "\u0440\u0430\u0437\u043c\u0438\u043d\u043a\u0430",
        "expanded razminka shorthand",
    ),
    (
        re.compile("\\b\u0437\u0430\u043c\\.?\\b", re.IGNORECASE),
        "\u0437\u0430\u043c\u0438\u043d\u043a\u0430",
        "expanded zaminka shorthand",
    ),
    (
        re.compile("\\b\u0432\u043e\u0441\u0441\u0442\\.?\\b", re.IGNORECASE),
        "\u0432\u043e\u0441\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0439",
        "expanded recovery shorthand",
    ),
    (
        re.compile("\\b\u0447\u0441\u0441\\b", re.IGNORECASE),
        "\u043f\u0443\u043b\u044c\u0441",
        "normalized HR abbreviation",
    ),
)

AMBIGUITY_PATTERNS = (
    (re.compile(r"(^|[\s(])~"), "source text contains approximate values"),
    (
        re.compile("\\b\u043f\u0440\u0438\u043c\u0435\u0440\u043d\u043e\\b", re.IGNORECASE),
        "source text contains approximate values",
    ),
    (
        re.compile("\\b\u043e\u043a\u043e\u043b\u043e\\b", re.IGNORECASE),
        "source text contains approximate values",
    ),
    (
        re.compile("\\b\u0438\u043b\u0438\\b", re.IGNORECASE),
        "source text contains alternative interpretations",
    ),
    (
        re.compile("\\b\u043f\u043e \u0441\u0430\u043c\u043e\u0447\u0443\u0432\u0441\u0442\u0432\u0438\u044e\\b", re.IGNORECASE),
        "source text contains effort-based ambiguity",
    ),
    (re.compile(r"\?"), "source text contains explicit uncertainty"),
)

SOURCE_WORKOUT_HEADER_RE = re.compile(
    r"^\s*(?P<header>\d{1,2}\.\d{1,2}(?:\.\d{2,4})?(?:\s*\([^)]{1,12}\))?)\s*$",
    re.IGNORECASE,
)
# Also detect "Тренировка N" / "Workout N" / "Тренировка N — ..." headers
SOURCE_WORKOUT_NUMBERED_RE = re.compile(
    r"^\s*(?:тренировка|workout|training)\s+\d{1,3}(?:\s*[-—–].*)?$",
    re.IGNORECASE,
)
# Phase-structured plan detection ("ФАЗА N: ... (недели A–B)" style)
PHASE_WEEK_RANGE_RE = re.compile(
    r"\bнедел[ьи]\w*\s+(\d{1,2})\s*[–—-]\s*(\d{1,2})\b",
    re.IGNORECASE,
)
PHASE_SINGLE_WEEK_RE = re.compile(
    r"\bнедел[яь]\s+(\d{1,2})\b(?!\s*[–—-]\s*\d)",
    re.IGNORECASE,
)
PHASE_DAY_HEADER_RE = re.compile(
    r"^#{1,4}\s+("
    r"Понедельник|Вторник|Среда|Четверг|Пятница|Суббота|Воскресенье"
    r"|Mon|Tue|Wed|Thu|Fri|Sat|Sun"
    r")\b",
    re.IGNORECASE | re.MULTILINE,
)
REST_DAY_RE = re.compile(
    "\\b(?:\u0432\u044b\u0445\u043e\u0434\\w*|\u043e\u0442\u0434\u044b\u0445\\w*|rest(?:\\s+day)?|off)\\b",
    re.IGNORECASE,
)
REST_DAY_ONLY_RE = re.compile(
    r"^\s*(?:"
    r"\u0432\u044b\u0445\u043e\u0434(?:\u043d(?:\u043e(?:\u0439|\u0435)|\u044b\u0439|\u044b\u0435|\u043e\u0433\u043e|\u043e\u043c))?"
    r"|\u043e\u0442\u0434\u044b\u0445(?:\u0430\u0435\u043c|\u0430\u0435\u0442\u0435|\u0430\u0442\u044c)?"
    r"|rest(?:\s+day)?"
    r"|off(?:\s*day)?"
    r")\s*[.!?]?\s*$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class SourceTextAnalysis:
    text: str
    changes: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    workout_headers: list[str] = field(default_factory=list)
    workout_blocks: list[str] = field(default_factory=list)
    expected_workouts: int = 0
    phase_weeks: int = 0        # total weeks detected from phase headers (e.g. "недели 1–4")
    days_per_week: int = 0      # training days/week detected from section headers (e.g. "### Среда")


def sanitize_workout_name(raw_name: Any) -> str:
    """Sanitize YAML filename/name to a safe workout identifier."""
    if not isinstance(raw_name, str):
        raise ValueError("Workout filename must be a string")

    value = raw_name.strip().replace("/", "_").replace("\\", "_")
    value = FILENAME_SAFE_RE.sub("_", value)
    value = value.strip("._")

    if not value:
        raise ValueError("Workout filename is empty after sanitization")

    return value[:120]


def _estimate_phase_plan_workouts(text: str) -> tuple[int, int, int]:
    """Estimate workout count for ФАЗА-structured plans.

    Looks for week-range annotations like "недели 1–4" in phase headers and
    training-day section headers like "### Среда".

    Returns (total_weeks, days_per_week, expected_workouts).
    Returns (0, 0, 0) if the plan doesn't look phase-structured.
    """
    total_weeks = 0
    for match in PHASE_WEEK_RANGE_RE.finditer(text):
        start, end = int(match.group(1)), int(match.group(2))
        if 1 <= start <= end <= 52:
            total_weeks += end - start + 1

    for match in PHASE_SINGLE_WEEK_RE.finditer(text):
        n = int(match.group(1))
        if 1 <= n <= 52:
            total_weeks += 1

    if total_weeks == 0:
        return 0, 0, 0

    day_names: set[str] = set()
    for match in PHASE_DAY_HEADER_RE.finditer(text):
        day_names.add(match.group(1).lower())

    days_per_week = len(day_names)
    if days_per_week == 0:
        return 0, 0, 0

    return total_weeks, days_per_week, total_weeks * days_per_week


def normalize_source_text(text: str) -> SourceTextAnalysis:
    """Normalize raw training plan text before it goes to the LLM."""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    changes: list[str] = []

    canonical = normalized.replace("\r\n", "\n").replace("\r", "\n")
    if canonical != normalized:
        changes.append("normalized line endings")
    normalized = canonical

    compact = INTERVAL_MULTIPLIER_RE.sub("x", normalized)
    if compact != normalized:
        changes.append("normalized interval notation")
    normalized = compact

    for pattern, replacement, description in SOURCE_REPLACEMENTS:
        updated = pattern.sub(replacement, normalized)
        if updated != normalized:
            changes.append(description)
        normalized = updated

    compact = MULTISPACE_RE.sub(" ", normalized)
    compact = TOO_MANY_BLANKS_RE.sub("\n\n", compact).strip()
    if compact != normalized:
        changes.append("collapsed extra whitespace")
    normalized = compact

    ambiguities = detect_source_ambiguities(normalized)
    workout_blocks = _extract_workout_blocks(normalized)
    workout_headers = [block.splitlines()[0].strip() for block in workout_blocks if block.strip()]
    expected_workouts = len(workout_headers)

    # Fallback: detect phase-structured plans ("ФАЗА N: ... (недели A–B)" + "### Среда" style).
    # These plans don't have individual dated workout headers, so block detection returns nothing.
    phase_weeks = 0
    days_per_week = 0
    if expected_workouts == 0:
        phase_weeks, days_per_week, estimated = _estimate_phase_plan_workouts(normalized)
        if estimated > 0:
            expected_workouts = estimated

    return SourceTextAnalysis(
        text=normalized,
        changes=_unique(changes),
        ambiguities=ambiguities,
        workout_headers=workout_headers,
        workout_blocks=workout_blocks,
        expected_workouts=expected_workouts,
        phase_weeks=phase_weeks,
        days_per_week=days_per_week,
    )


def detect_source_ambiguities(text: str) -> list[str]:
    messages: list[str] = []
    for pattern, message in AMBIGUITY_PATTERNS:
        if pattern.search(text):
            messages.append(message)
    return _unique(messages)


def _extract_workout_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current_header: str | None = None
    current_lines: list[str] = []

    def flush_current() -> None:
        if current_header is None:
            return
        block_text = "\n".join(current_lines)
        if not _looks_like_rest_day_block(current_lines):
            blocks.append(block_text.strip())

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current_header is not None:
                current_lines.append("")
            continue

        if SOURCE_WORKOUT_HEADER_RE.match(line) or SOURCE_WORKOUT_NUMBERED_RE.match(line):
            flush_current()
            current_header = line
            current_lines = [line]
            continue

        if current_header is not None:
            current_lines.append(line)

    flush_current()
    return blocks


def _looks_like_rest_day_block(lines: list[str]) -> bool:
    """Treat a block as rest day only when workout content is actually absent."""
    if not lines:
        return False

    # First line is the workout header (date/index), the rest is day content.
    content_lines = [line.strip() for line in lines[1:] if line.strip()]
    if not content_lines:
        return False

    # Any explicit workout markers mean this is a training day, not rest.
    for line in content_lines:
        lowered = line.lower()
        if (
            re.search(r"\d+\s*(?:км|km|м|min|мин)\b", lowered)
            or "x" in lowered
            or "\u0440\u0430\u0437\u043c" in lowered
            or "\u0437\u0430\u043c\u0438\u043d" in lowered
            or "\u043f\u0443\u043b\u044c\u0441" in lowered
            or "\u0438\u043d\u0442\u0435\u0440\u0432" in lowered
            or "\u043a\u0440\u043e\u0441\u0441" in lowered
            or "\u0431\u0435\u0433" in lowered
        ):
            return False

    # Rest day if all content lines are short rest/off statements.
    return all(REST_DAY_ONLY_RE.match(line) for line in content_lines)


def normalize_step_type(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    key = value.strip().lower()
    return STEP_TYPE_ALIASES.get(key, key)


def normalize_intensity(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    key = value.strip().lower()
    return INTENSITY_ALIASES.get(key, key)


def normalize_pace_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    stripped = value.strip().strip("\"'")
    if not stripped:
        return value

    match = PACE_RE.fullmatch(stripped) or PACE_SPACED_RE.fullmatch(stripped)
    if not match:
        return stripped

    minutes = int(match.group(1))
    seconds = int(match.group(2))
    return f"{minutes}:{seconds:02d}"


def repair_plan_data(data: Any) -> tuple[Any, list[str]]:
    """
    Apply safe deterministic repairs to parsed YAML data.

    Returns a deep-copied data structure and a list of applied repair notes.
    """
    repaired = deepcopy(data)
    notes: list[str] = []

    if not isinstance(repaired, dict):
        return repaired, notes

    workouts = repaired.get("workouts")
    if not isinstance(workouts, list):
        return repaired, notes

    inferred_year = _infer_plan_year(workouts)
    for w_idx, workout in enumerate(workouts):
        prefix = f"workouts[{w_idx}]"
        if not isinstance(workout, dict):
            continue

        filename = workout.get("filename")
        name = workout.get("name")
        canonical = next(
            (
                value
                for value in (filename, name)
                if isinstance(value, str) and value.strip()
            ),
            None,
        )
        if canonical is not None:
            normalized = normalize_workout_identifier(
                canonical,
                workout_index=w_idx,
                inferred_year=inferred_year,
            )
            if normalized != canonical:
                notes.append(f"{prefix}: normalized workout identifier '{canonical}' -> '{normalized}'")

            sanitized = sanitize_workout_name(normalized)
            if sanitized != normalized:
                notes.append(f"{prefix}: sanitized workout name '{normalized}' -> '{sanitized}'")
            if filename != sanitized or name != sanitized:
                workout["filename"] = sanitized
                workout["name"] = sanitized
                notes.append(f"{prefix}: aligned filename/name to '{sanitized}'")

        steps = workout.get("steps")
        if not isinstance(steps, list):
            continue

        for s_idx, step in enumerate(steps):
            s_prefix = f"{prefix}.steps[{s_idx}]"
            if not isinstance(step, dict):
                continue

            original_type = step.get("type")
            normalized_type = normalize_step_type(original_type)
            if normalized_type != original_type:
                step["type"] = normalized_type
                notes.append(f"{s_prefix}: normalized step type '{original_type}' -> '{normalized_type}'")

            step_type = step.get("type")
            original_intensity = step.get("intensity")
            normalized_intensity = normalize_intensity(original_intensity)
            if normalized_intensity != original_intensity and normalized_intensity is not None:
                step["intensity"] = normalized_intensity
                notes.append(
                    f"{s_prefix}: normalized intensity '{original_intensity}' -> '{normalized_intensity}'"
                )
            elif original_intensity is None and step_type in INTENSITY_DEFAULTS:
                default_intensity = INTENSITY_DEFAULTS[step_type]
                step["intensity"] = default_intensity
                notes.append(f"{s_prefix}: applied default intensity '{default_intensity}'")
            elif original_intensity is None and step_type in _POSITIONAL_INTENSITY_TYPES:
                last_content_idx = max(
                    (i for i, s in enumerate(steps) if isinstance(s, dict) and s.get("type") != "repeat"),
                    default=-1,
                )
                content_step_count = sum(
                    1 for s in steps if isinstance(s, dict) and s.get("type") != "repeat"
                )
                if content_step_count == 1:
                    positional_default = "active"
                elif s_idx == 0:
                    positional_default = "warmup"
                elif s_idx == last_content_idx:
                    positional_default = "cooldown"
                else:
                    positional_default = "active"
                step["intensity"] = positional_default
                notes.append(f"{s_prefix}: applied positional default intensity '{positional_default}'")

            for field_name in ("pace_fast", "pace_slow"):
                if field_name not in step:
                    continue
                original_value = step.get(field_name)
                normalized_value = normalize_pace_value(original_value)
                if normalized_value != original_value:
                    step[field_name] = normalized_value
                    notes.append(
                        f"{s_prefix}: normalized {field_name} '{original_value}' -> '{normalized_value}'"
                    )

            for field_name in ("seconds", "hr_low", "hr_high", "back_to_offset", "count"):
                coerced = _coerce_int(step.get(field_name))
                if coerced != step.get(field_name):
                    step[field_name] = coerced
                    notes.append(f"{s_prefix}: coerced {field_name} to integer {coerced}")

            if "km" in step:
                coerced_km = _coerce_float(step.get("km"))
                if coerced_km != step.get("km"):
                    step["km"] = coerced_km
                    notes.append(f"{s_prefix}: coerced km to number {coerced_km}")

            step_type = step.get("type")
            if _is_cooldown_hr_cap_only_step(step):
                hr_high = step["hr_high"]
                step["hr_low"] = HR_CAP_ONLY_DEFAULT_LOW
                notes.append(
                    f"{s_prefix}: repaired cooldown upper-only HR cap "
                    f"to {HR_CAP_ONLY_DEFAULT_LOW}-{hr_high}"
                )

            if (
                step_type in _POSITIONAL_INTENSITY_TYPES
                and step.get("intensity") in {"warmup", "cooldown"}
                and _count_content_steps(steps) == 1
            ):
                original_value = step["intensity"]
                step["intensity"] = "active"
                notes.append(
                    f"{s_prefix}: normalized single-step intensity "
                    f"'{original_value}' -> 'active'"
                )

            if step_type == "sbu_block":
                drills = step.get("drills")
                if drills == []:
                    step.pop("drills")
                    notes.append(f"{s_prefix}: removed empty drills list to use default SBU block")
                elif isinstance(drills, list):
                    for d_idx, drill in enumerate(drills):
                        d_prefix = f"{s_prefix}.drills[{d_idx}]"
                        if not isinstance(drill, dict):
                            continue

                        if drill.get("seconds") is None:
                            drill["seconds"] = 60
                            notes.append(f"{d_prefix}: applied default seconds=60")
                        elif (coerced_seconds := _coerce_int(drill.get("seconds"))) != drill.get("seconds"):
                            drill["seconds"] = coerced_seconds
                            notes.append(f"{d_prefix}: coerced seconds to integer {coerced_seconds}")

                        if drill.get("reps") is None:
                            drill["reps"] = 2
                            notes.append(f"{d_prefix}: applied default reps=2")
                        elif (coerced_reps := _coerce_int(drill.get("reps"))) != drill.get("reps"):
                            drill["reps"] = coerced_reps
                            notes.append(f"{d_prefix}: coerced reps to integer {coerced_reps}")

                        if isinstance(drill.get("name"), str):
                            trimmed = drill["name"].strip()
                            if trimmed != drill["name"]:
                                drill["name"] = trimmed
                                notes.append(f"{d_prefix}: trimmed drill name")

    return repaired, _unique(notes)


def _is_cooldown_hr_cap_only_step(step: dict[str, Any]) -> bool:
    step_type = step.get("type")
    if step_type not in {"dist_hr", "time_hr"}:
        return False
    if step.get("intensity") != "cooldown":
        return False

    hr_low = step.get("hr_low")
    hr_high = step.get("hr_high")
    return (
        isinstance(hr_high, int)
        and hr_high > HR_CAP_ONLY_DEFAULT_LOW
        and (hr_low is None or (isinstance(hr_low, int) and hr_low >= hr_high))
    )


def _count_content_steps(steps: list[Any]) -> int:
    return sum(1 for item in steps if isinstance(item, dict) and item.get("type") != "repeat")


def _coerce_int(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and INT_RE.fullmatch(value):
        return int(value.strip())
    return value


def _coerce_float(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and FLOAT_RE.fullmatch(value):
        return float(value.strip().replace(",", "."))
    return value


def normalize_workout_identifier(
    raw_name: Any,
    *,
    workout_index: int,
    inferred_year: int | None = None,
) -> str:
    """Normalize workout identifier with calendar-week or sequence fallback prefix."""
    if not isinstance(raw_name, str):
        raise ValueError("Workout filename must be a string")

    tokens = _tokenize_identifier(raw_name)
    if not tokens:
        return sanitize_workout_name(raw_name)

    parts = _build_identifier_parts(
        tokens,
        workout_index=workout_index,
        inferred_year=inferred_year,
    )
    return "_".join(parts)


def _build_identifier_parts(
    tokens: list[str],
    *,
    workout_index: int,
    inferred_year: int | None,
) -> list[str]:
    idx = 0
    explicit_prefix_token: str | None = None
    if WEEK_PREFIX_TOKEN_RE.fullmatch(tokens[idx]) or SEQUENCE_PREFIX_TOKEN_RE.fullmatch(tokens[idx]):
        explicit_prefix_token = tokens[idx]
        idx += 1
        if idx >= len(tokens):
            return [_normalize_explicit_prefix(explicit_prefix_token)]

    parsed_date, weekday_token, next_idx = _extract_date_weekday(tokens, idx, inferred_year=inferred_year)
    remaining = tokens[next_idx:]

    if parsed_date is not None:
        calendar_week = _calendar_week_from_date(parsed_date)
        parts = [f"W{calendar_week:02d}", f"{parsed_date.month:02d}-{parsed_date.day:02d}"]
        if weekday_token:
            parts.append(weekday_token)
        parts.extend(remaining)
        return parts

    sequence_number = _extract_sequence_number(tokens, idx, fallback=workout_index + 1)
    seq_idx = idx + 1 if idx < len(tokens) and SEQUENCE_TOKEN_RE.fullmatch(tokens[idx]) else idx

    if weekday_token is None and seq_idx < len(tokens):
        weekday_token = _normalize_weekday_token(tokens[seq_idx])
        if weekday_token:
            seq_idx += 1

    if explicit_prefix_token is not None:
        prefix = _normalize_explicit_prefix(explicit_prefix_token)
    else:
        prefix = f"N{sequence_number:02d}"

    parts = [prefix]
    if weekday_token:
        parts.append(weekday_token)
    parts.extend(tokens[seq_idx:])
    return parts


def _tokenize_identifier(raw_name: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", raw_name)
    normalized = normalized.replace("/", " ").replace("\\", " ")
    normalized = re.sub(r"[()\[\]{}:,;]+", " ", normalized)
    normalized = re.sub(r"[_\s]+", " ", normalized).strip()
    if not normalized:
        return []
    return [token for token in normalized.split(" ") if token]


def _extract_date_weekday(
    tokens: list[str],
    start_idx: int,
    *,
    inferred_year: int | None,
) -> tuple[date | None, str | None, int]:
    if start_idx >= len(tokens):
        return None, None, start_idx

    token = tokens[start_idx]
    parsed_date = _parse_date_token(token, inferred_year=inferred_year)
    if parsed_date is not None:
        next_idx = start_idx + 1
        weekday_token = _normalize_weekday_token(tokens[next_idx]) if next_idx < len(tokens) else None
        if weekday_token:
            next_idx += 1
        return parsed_date, weekday_token, next_idx

    if (
        start_idx + 1 < len(tokens)
        and SEQUENCE_TOKEN_RE.fullmatch(tokens[start_idx])
        and (month_number := _normalize_month_token(tokens[start_idx + 1])) is not None
    ):
        year = inferred_year
        next_idx = start_idx + 2
        if next_idx < len(tokens) and YEAR_TOKEN_RE.fullmatch(tokens[next_idx]):
            year = _normalize_year(int(tokens[next_idx]))
            next_idx += 1
        parsed_date = _safe_date(year or REFERENCE_WEEK_YEAR, month_number, int(tokens[start_idx]))
        if parsed_date is not None:
            weekday_token = _normalize_weekday_token(tokens[next_idx]) if next_idx < len(tokens) else None
            if weekday_token:
                next_idx += 1
            return parsed_date, weekday_token, next_idx

    return None, None, start_idx


def _parse_date_token(token: str, *, inferred_year: int | None) -> date | None:
    if match := DAY_MONTH_DOTTED_RE.fullmatch(token):
        day = int(match.group("day"))
        month = int(match.group("month"))
        year_raw = match.group("year")
        year = _normalize_year(int(year_raw)) if year_raw is not None else (inferred_year or REFERENCE_WEEK_YEAR)
        return _safe_date(year, month, day)

    if match := MONTH_DAY_DASHED_RE.fullmatch(token):
        month = int(match.group("month"))
        day = int(match.group("day"))
        year = inferred_year or REFERENCE_WEEK_YEAR
        return _safe_date(year, month, day)

    return None


def _normalize_weekday_token(token: str) -> str | None:
    normalized = token.strip().strip(".").lower().replace("ё", "е")
    return WEEKDAY_ALIASES.get(normalized)


def _normalize_month_token(token: str) -> int | None:
    normalized = token.strip().strip(".").lower().replace("ё", "е")
    return MONTH_ALIASES.get(normalized)


def _normalize_year(year: int) -> int:
    if year < 100:
        return 2000 + year
    return year


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _calendar_week_from_date(value: date) -> int:
    return value.isocalendar()[1]


def _extract_sequence_number(tokens: list[str], start_idx: int, *, fallback: int) -> int:
    if start_idx < len(tokens) and SEQUENCE_TOKEN_RE.fullmatch(tokens[start_idx]):
        return int(tokens[start_idx])
    return fallback


def _normalize_explicit_prefix(token: str) -> str:
    if WEEK_PREFIX_TOKEN_RE.fullmatch(token):
        return f"W{int(token[1:]):02d}"
    if SEQUENCE_PREFIX_TOKEN_RE.fullmatch(token):
        return f"N{int(token[1:]):02d}"
    return token


def _infer_plan_year(workouts: list[Any]) -> int | None:
    years: set[int] = set()

    for workout in workouts:
        if not isinstance(workout, dict):
            continue
        for field_name in ("filename", "name", "desc"):
            value = workout.get(field_name)
            if not isinstance(value, str):
                continue
            for token in _tokenize_identifier(value):
                if match := DAY_MONTH_DOTTED_RE.fullmatch(token):
                    year_raw = match.group("year")
                    if year_raw is not None:
                        years.add(_normalize_year(int(year_raw)))

    if len(years) == 1:
        return next(iter(years))
    return None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
