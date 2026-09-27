"""Source-text facts used to sanity-check and repair LLM workouts.

Deterministic heuristics over the plan text a model was given: dated headers,
interval counts, distances and HR caps. They align identifiers with the source
header, restore a lost repeat, encode an upper-only HR cap, and flag answers
that contradict the source. Moved out of ``client.py``; the client keeps
aliases with the old ``UnifiedLLMClient._name`` spelling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

SEGMENT_HEADER_DATE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:====\s*ТРЕНИРОВКА\s*====\s*)?"
    r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})(?:\.(?P<year>\d{2,4}))?"
    r"(?:\s*\((?P<weekday>[^)]{1,24})\))?(?:\s*,?\s+(?P<title>[^\n]+))?\s*$",
    re.IGNORECASE,
)

IDENTIFIER_PREFIX_RE = re.compile(
    r"^(?:[WwNn]\d{1,3}_)?(?:\d{2}-\d{2}_)?(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun_)?(?P<suffix>.*)$"
)

FILENAME_DATE_RE = re.compile(r"_(?P<month>\d{2})-(?P<day>\d{2})_")

INTERVAL_SOURCE_RE = re.compile(
    r"(?P<count>\d{1,2})\s*[xх×]\s*(?P<distance>\d+(?:[.,]\d+)?)\s*(?P<unit>км|km|м|m)\b",
    re.IGNORECASE,
)

DISTANCE_KM_SOURCE_RE = re.compile(r"(?P<distance>\d+(?:[.,]\d+)?)\s*(?:км|km)\b", re.IGNORECASE)

HR_CAP_RE = re.compile(
    r"(?:пульс|чсс|hr)[^\n\r]{0,32}?(?:до|up\s*to|<=?)\s*(?P<hr>\d{2,3})",
    re.IGNORECASE,
)

WEEKDAY_TOKEN_ALIASES = {
    "mon": "Mon",
    "monday": "Mon",
    "пн": "Mon",
    "пон": "Mon",
    "понедельник": "Mon",
    "понедельника": "Mon",
    "tue": "Tue",
    "tues": "Tue",
    "tuesday": "Tue",
    "вт": "Tue",
    "втор": "Tue",
    "вторник": "Tue",
    "вторника": "Tue",
    "wed": "Wed",
    "wednesday": "Wed",
    "ср": "Wed",
    "среда": "Wed",
    "среду": "Wed",
    "среды": "Wed",
    "thu": "Thu",
    "thur": "Thu",
    "thurs": "Thu",
    "thursday": "Thu",
    "чт": "Thu",
    "четв": "Thu",
    "четверг": "Thu",
    "четверга": "Thu",
    "fri": "Fri",
    "friday": "Fri",
    "пт": "Fri",
    "пят": "Fri",
    "пятница": "Fri",
    "пятницу": "Fri",
    "пятницы": "Fri",
    "sat": "Sat",
    "saturday": "Sat",
    "сб": "Sat",
    "суб": "Sat",
    "суббота": "Sat",
    "субботу": "Sat",
    "субботы": "Sat",
    "sun": "Sun",
    "sunday": "Sun",
    "вс": "Sun",
    "воскр": "Sun",
    "воскресенье": "Sun",
    "воскресенья": "Sun",
}

_WEEKDAY_ORDER = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(slots=True)
class SourceWorkoutFact:
    month: int | None = None
    day: int | None = None
    week: int | None = None
    weekday: str | None = None
    header: str = ""
    interval_count: int | None = None
    interval_rep_km: float | None = None
    steady_distance_km: float | None = None
    hr_cap: int | None = None


def extract_segment_header_info(block_text: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in str(block_text or "").splitlines() if line.strip()]
    if not lines:
        return None
    match = SEGMENT_HEADER_DATE_RE.match(lines[0])
    if not match:
        return None

    day = int(match.group("day"))
    month = int(match.group("month"))
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None

    weekday = normalize_weekday_token(match.group("weekday"))
    if weekday is None:
        title_prefix = re.split(r"\s*[—–-]\s*", match.group("title") or "", maxsplit=1)[0]
        weekday = normalize_weekday_token(title_prefix)

    raw_year = match.group("year")
    if raw_year:
        year = int(raw_year)
        if year < 100:
            year += 2000
        try:
            parsed_date = date(year, month, day)
        except ValueError:
            return None
    else:
        # No year in the header: take the nearest real date (matching the
        # weekday when one is written), never a fixed calendar year.
        from ..garmin_step_mapper import infer_date

        weekday_index = _WEEKDAY_ORDER.index(weekday) if weekday in _WEEKDAY_ORDER else None
        parsed_date = infer_date(month, day, weekday=weekday_index)
        if parsed_date is None:
            return None

    # The date is the fact. A written weekday only helps choose the year when
    # none is given; with an explicit year, a mistyped weekday ("01.05.2026 (Чт)",
    # a Friday) must not reach the filename -- the year would later be re-derived
    # from that weekday and the workout scheduled a year off.
    weekday = _WEEKDAY_ORDER[parsed_date.weekday()]

    return {
        "month": month,
        "day": day,
        "week": parsed_date.isocalendar()[1],
        "weekday": weekday,
        "date_iso": parsed_date.isoformat(),
    }


def extract_workout_facts_from_source_text(plan_text: str) -> list[SourceWorkoutFact]:
    from ..plan_processing import normalize_source_text

    analysis = normalize_source_text(plan_text)
    return [
        fact
        for block in analysis.workout_blocks
        if (fact := extract_single_workout_fact(block)) is not None
    ]


def extract_single_workout_fact(block_text: str) -> SourceWorkoutFact | None:
    lines = [line.strip() for line in str(block_text or "").splitlines() if line.strip()]
    if not lines:
        return None
    header = lines[0]
    info = extract_segment_header_info(block_text)
    if info is None:
        return None

    lowered = "\n".join(lines[1:]).lower()
    interval_match = INTERVAL_SOURCE_RE.search(lowered)
    interval_count: int | None = None
    interval_rep_km: float | None = None
    if interval_match:
        interval_count = int(interval_match.group("count"))
        raw_dist = float(interval_match.group("distance").replace(",", "."))
        unit = interval_match.group("unit").lower()
        interval_rep_km = raw_dist if unit in {"km", "км"} else raw_dist / 1000.0

    steady_distance_km: float | None = None
    km_values = [
        float(match.group("distance").replace(",", "."))
        for match in DISTANCE_KM_SOURCE_RE.finditer(lowered)
    ]
    if km_values and interval_match is None:
        if len(km_values) == 1:
            steady_distance_km = km_values[0]

    hr_cap: int | None = None
    hr_match = HR_CAP_RE.search(lowered)
    if hr_match:
        hr_cap = int(hr_match.group("hr"))

    return SourceWorkoutFact(
        month=info["month"],
        day=info["day"],
        week=info["week"],
        weekday=info["weekday"],
        header=header,
        interval_count=interval_count,
        interval_rep_km=interval_rep_km,
        steady_distance_km=steady_distance_km,
        hr_cap=hr_cap,
    )


def format_source_facts_for_retry_prompt(facts: list[SourceWorkoutFact]) -> str:
    if not facts:
        return ""

    lines: list[str] = []
    for fact in facts[:12]:
        prefix = "unknown-date"
        if fact.month and fact.day:
            prefix = f"{fact.day:02d}.{fact.month:02d}"
        bits = [prefix]
        if fact.interval_count and fact.interval_rep_km:
            bits.append(f"intervals {fact.interval_count}x{fact.interval_rep_km:.3g}km")
        if fact.steady_distance_km:
            bits.append(f"distance {fact.steady_distance_km:.3g}km")
        if fact.hr_cap:
            bits.append(f"hr<= {fact.hr_cap}")
        lines.append("- " + ", ".join(bits))
    return "\n".join(lines)


def detect_suspicious_workout_against_fact(
    workout: dict[str, Any],
    fact: SourceWorkoutFact | None,
) -> list[str]:
    if fact is None:
        return []
    issues: list[str] = []
    steps = workout.get("steps") if isinstance(workout.get("steps"), list) else []

    if fact.interval_count and fact.interval_rep_km:
        repeat_counts = [
            step.get("count")
            for step in steps
            if isinstance(step, dict) and step.get("type") == "repeat"
        ]
        if fact.interval_count not in repeat_counts:
            issues.append(f"missing repeat count {fact.interval_count}")

        rep_distances = [
            float(step.get("km"))
            for step in steps
            if isinstance(step, dict)
            and str(step.get("type", "")).startswith("dist_")
            and isinstance(step.get("km"), (int, float))
        ]
        if not any(abs(value - fact.interval_rep_km) <= 0.08 for value in rep_distances):
            issues.append(f"missing interval distance {fact.interval_rep_km:.3g}km")

        type_code = str(workout.get("type_code", "")).lower()
        if type_code and type_code not in {"intervals", "threshold", "tempo", "fartlek"}:
            issues.append("unexpected workout type for interval source block")

    if isinstance(fact.steady_distance_km, (int, float)):
        step_distances = [
            float(step.get("km"))
            for step in steps
            if isinstance(step, dict)
            and str(step.get("type", "")).startswith("dist_")
            and isinstance(step.get("km"), (int, float))
        ]
        if not any(
            abs(value - float(fact.steady_distance_km)) <= 0.35
            for value in step_distances
        ):
            issues.append(
                f"missing source distance step {fact.steady_distance_km:.3g}km"
            )


    return issues


def evaluate_workouts_against_source_fact(
    workouts: list[dict[str, Any]],
    fact: SourceWorkoutFact,
) -> tuple[bool, str]:
    def _matches_date(workout_item: dict[str, Any]) -> bool:
        filename = str(workout_item.get("filename", ""))
        match = FILENAME_DATE_RE.search(filename)
        if not match or fact.month is None or fact.day is None:
            return False
        return (
            int(match.group("month")) == fact.month
            and int(match.group("day")) == fact.day
        )

    candidates = [item for item in workouts if isinstance(item, dict) and _matches_date(item)]
    if not candidates:
        return False, f"source date {fact.day:02d}.{fact.month:02d} not found in generated filenames"

    for candidate in candidates:
        issues = detect_suspicious_workout_against_fact(candidate, fact)
        if not issues:
            return True, (
                f"source facts for {fact.day:02d}.{fact.month:02d} are preserved"
            )

    return False, (
        f"source facts mismatch for {fact.day:02d}.{fact.month:02d}: "
        f"{'; '.join(detect_suspicious_workout_against_fact(candidates[0], fact)[:3])}"
    )


def normalize_weekday_token(token: str | None) -> str | None:
    if token is None:
        return None
    key = token.strip().lower().strip(".")
    return WEEKDAY_TOKEN_ALIASES.get(key)


def align_workout_identifier_with_source_header(
    workout: dict[str, Any],
    *,
    month: int,
    day: int,
    week: int,
    weekday: str,
) -> None:
    base = workout.get("filename") or workout.get("name") or ""
    base = str(base).strip()
    if not base:
        return

    suffix = base
    match = IDENTIFIER_PREFIX_RE.match(base)
    if match:
        suffix = (match.group("suffix") or "").strip("_")

    prefix = f"W{week:02d}_{month:02d}-{day:02d}_{weekday}"
    aligned = f"{prefix}_{suffix}" if suffix else prefix
    workout["filename"] = aligned
    workout["name"] = aligned


def encode_source_hr_cap(workout: dict[str, Any], fact: SourceWorkoutFact | None) -> None:
    """The source states only "пульс до N": any HR step capped at N gets the 60 floor.

    Models tend to invent a lower bound (80, 120, ...); the agreed encoding of
    an upper-only cap is HR_CAP_FLOOR_BPM..N.
    """
    from ..plan_domain import HR_CAP_FLOOR_BPM

    if fact is None or not isinstance(fact.hr_cap, int):
        return
    for step in workout.get("steps") or []:
        if (
            isinstance(step, dict)
            and str(step.get("type", "")).endswith("_hr")
            and step.get("hr_high") == fact.hr_cap
            and step.get("hr_low") != HR_CAP_FLOOR_BPM
        ):
            step["hr_low"] = HR_CAP_FLOOR_BPM


def repair_missing_source_repeat(
    workout: dict[str, Any], fact: SourceWorkoutFact | None
) -> None:
    """Restore an explicit repeat when the model emitted its content steps."""
    if fact is None or not fact.interval_count or not fact.interval_rep_km:
        return
    steps = workout.get("steps")
    if not isinstance(steps, list):
        return
    if any(
        isinstance(step, dict) and step.get("type") == "repeat"
        for step in steps
    ):
        return
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not str(step.get("type", "")).startswith("dist_"):
            continue
        km = step.get("km")
        if isinstance(km, (int, float)) and abs(float(km) - fact.interval_rep_km) <= 0.08:
            steps.append(
                {
                    "type": "repeat",
                    "count": fact.interval_count,
                    "back_to_offset": index,
                }
            )
            return


def build_segment_fact_retry_input(
    block_text: str,
    fact: SourceWorkoutFact | None,
    suspicious: list[str],
) -> str:
    lines = ["\nMandatory facts:"]
    if fact:
        if fact.month and fact.day and fact.weekday:
            lines.append(f"- date: {fact.day:02d}.{fact.month:02d} ({fact.weekday})")
        if fact.interval_count and fact.interval_rep_km:
            lines.append(
                f"- intervals: {fact.interval_count} x {fact.interval_rep_km:.3g} km"
            )
        if fact.steady_distance_km:
            lines.append(f"- distance_km: {fact.steady_distance_km:.3g}")
        if fact.hr_cap:
            lines.append(f"- hr cap: {fact.hr_cap}")
        if fact.interval_count and fact.interval_rep_km:
            lines.append(
                "- interval output must contain a repeat step with "
                f"count: {fact.interval_count} and back_to_offset pointing to the active step"
            )
    lines.append("Issues to fix:")
    lines.extend(f"- {item}" for item in suspicious[:5])
    return block_text + "\n" + "\n".join(lines)
