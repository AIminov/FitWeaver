"""Deterministic parser for the marked training-text format (no LLM involved).

The format is described for users in ``docs/MARKED_PLAN_FORMAT.md`` and for the
LLM in ``llm/training_text_format.md``: ``==== ТРЕНИРОВКА ====`` headers,
``**** ШАГ ****`` steps with labelled fact lines, and
``**** ПОВТОР: N РАЗ **** … **** КОНЕЦ ПОВТОРА ****`` groups (nesting allowed).

Pipeline::

    text --parse_marked_plan()--> MarkedPlan (step tree)
         --plan_to_yaml_data()--> canonical Garmin YAML dict
    MarkedPlan --render_marked_plan()--> canonical marked text

Repeat groups are compiled here, so ``back_to_offset``/``count`` are never
typed by a person or produced by a model. Facts are never invented: a missing
measure becomes an open step and an incomplete target is dropped, each with a
warning that names the source line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Union

WORKOUT_MARKER = "==== ТРЕНИРОВКА ===="
STEP_MARKER = "**** ШАГ ****"
REPEAT_END_MARKER = "**** КОНЕЦ ПОВТОРА ****"

_WORKOUT_RE = re.compile(r"^={4}\s*ТРЕНИРОВКА\s*={4}\s*(?P<rest>.*)$", re.IGNORECASE)
_STEP_RE = re.compile(r"^\*{4}\s*ШАГ\s*\*{4}$", re.IGNORECASE)
_REPEAT_RE = re.compile(r"^\*{4}\s*ПОВТОР\s*:?\s*(?P<count>\S+)?\s*(?:РАЗ[А]?)?\s*\*{4}$", re.IGNORECASE)
_REPEAT_END_RE = re.compile(r"^\*{4}\s*КОНЕЦ\s+ПОВТОРА\s*\*{4}$", re.IGNORECASE)
_LABEL_RE = re.compile(r"^(?P<label>[^:：]{1,40})[:：]\s*(?P<value>.*)$")
_HEADER_DATE_RE = re.compile(
    r"^(?P<day>\d{1,2})\.(?P<month>\d{1,2})(?:\.(?P<year>\d{2}|\d{4}))?"
    r"(?:\s*[,(]?\s*(?P<weekday>[а-яё]+)\)?)?\s*$"
)
_TITLE_SPLIT_RE = re.compile(r"\s+[—–-]\s+|\s*[—–]\s*")
_NUMBER = r"\d+(?:[.,]\d+)?"
_DISTANCE_RE = re.compile(rf"(?P<value>{_NUMBER})\s*(?P<unit>километр(?:а|ов)?|км|km|метр(?:а|ов)?|м|m)(?![а-яa-z])", re.IGNORECASE)
_DURATION_RE = re.compile(
    rf"(?P<value>{_NUMBER})\s*(?P<unit>секунд[аы]?|сек|с|s|минут[аы]?|мин|min|часа|часов|час|ч|h)(?![а-яa-z])",
    re.IGNORECASE,
)
_PACE_RE = re.compile(r"(?<!\d)(?P<min>\d{1,2}):(?P<sec>\d{2})(?!\d)")
_RANGE_RE = re.compile(r"(?P<low>\d{2,3})\s*(?:[-–—]|\bдо\b)\s*(?P<high>\d{2,3})", re.IGNORECASE)
_ZONE_RE = re.compile(r"(?:\bz\s*|\bзона\s*)(?P<zone>[1-5])\b", re.IGNORECASE)
_NO_VALUE_RE = re.compile(r"^\s*(?:нет|не задан[аоы]?|нет данных|-|—)\s*\.?\s*$", re.IGNORECASE)
_APPROX_RE = re.compile(r"\b(?:около|примерно|приблизительно|порядка)\b|~|≈", re.IGNORECASE)
_DRILL_RE = re.compile(
    rf"^(?P<name>.+?)\s*[—–-]\s*(?:(?P<reps>\d+)\s*[×xх*]\s*)?(?P<value>{_NUMBER})\s*(?P<unit>сек|с|s|мин|min)\b",
    re.IGNORECASE,
)

# Pace targets with a single value get the project's agreed ±10 s/km window
# (the same rule repair_plan_data applies to equal pace bounds).
PACE_SINGLE_VALUE_WINDOW_SEC = 10

_INTENSITY_BY_KIND = {
    "разминка": "warmup",
    "warmup": "warmup",
    "заминка": "cooldown",
    "cooldown": "cooldown",
    "восстановление": "recovery",
    "recovery": "recovery",
    "работа": "active",
    "ускорение": "active",
    "active": "active",
    "work": "active",
}
_STEP_LABELS = {
    "тип": "kind",
    "дистанция": "distance",
    "длительность": "duration",
    "темп": "pace",
    "пульс": "hr",
    "чсс": "hr",
    "частота шагов": "cadence",
    "каденс": "cadence",
    "упражнения": "drills",
    "интенсивность": "note",
    "примечание": "note",
}
_WORKOUT_LABELS = {
    "общая дистанция": "total_distance",
    "общая длительность": "total_duration",
    "цель тренировки": "goal",
    "другое": "other",
}
_WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
_WEEKDAY_ALIASES = {
    **{name: i for i, name in enumerate(_WEEKDAYS_RU)},
    "среду": 2, "пятницу": 4, "субботу": 5,
    "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
}
_WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
})


@dataclass
class ParseIssue:
    line: int
    message: str
    # Stable identifier for callers that react to specific issues
    # (e.g. "missing_measure"); empty for purely informational ones.
    code: str = ""

    def __str__(self) -> str:
        return f"строка {self.line}: {self.message}" if self.line else self.message


@dataclass
class Target:
    kind: str  # "hr" | "pace" | "cadence"
    low: int  # pace: seconds per km, fastest bound
    high: int  # pace: seconds per km, slowest bound
    zone: str | None = None


@dataclass
class MarkedStep:
    line: int
    fields: list[tuple[int, str, str]] = field(default_factory=list)  # (line, label, value) as written
    kind: str = ""
    km: float | None = None
    seconds: int | None = None
    target: Target | None = None
    drills: list[dict[str, Any]] | None = None
    is_sbu: bool = False


@dataclass
class MarkedRepeat:
    line: int
    count: int
    items: list[MarkedItem] = field(default_factory=list)


MarkedItem = Union[MarkedStep, MarkedRepeat]


@dataclass
class MarkedWorkout:
    line: int
    title: str = ""
    date: date | None = None
    meta: list[tuple[int, str, str]] = field(default_factory=list)
    total_km: float | None = None
    total_minutes: float | None = None
    items: list[MarkedItem] = field(default_factory=list)


@dataclass
class MarkedPlan:
    workouts: list[MarkedWorkout] = field(default_factory=list)
    errors: list[ParseIssue] = field(default_factory=list)
    warnings: list[ParseIssue] = field(default_factory=list)


@dataclass
class MarkedCompileResult:
    data: dict[str, Any] | None
    errors: list[str]
    warnings: list[str]
    plan: MarkedPlan


# ---------------------------------------------------------------------------
# Detection and parsing
# ---------------------------------------------------------------------------

def is_marked_plan(text: str) -> bool:
    """True when the text uses step markers, i.e. it can be parsed without an LLM."""
    return any(_STEP_RE.match(line.strip()) for line in str(text or "").splitlines())


def parse_marked_plan(
    text: str,
    *,
    hr_zones: dict[str, Any] | None = None,
    default_year: int | None = None,
) -> MarkedPlan:
    """Parse marked text into a step tree, collecting errors and warnings by line."""
    plan = MarkedPlan()
    workout: MarkedWorkout | None = None
    step: MarkedStep | None = None
    stack: list[MarkedRepeat] = []
    ignored_preamble = False

    def container() -> list[MarkedItem]:
        assert workout is not None
        return stack[-1].items if stack else workout.items

    def finish_workout() -> None:
        if workout is None:
            return
        for repeat in stack:
            plan.errors.append(ParseIssue(repeat.line, "повтор не закрыт маркером «**** КОНЕЦ ПОВТОРА ****»"))
        if not _has_steps(workout.items):
            plan.errors.append(ParseIssue(workout.line, "в тренировке нет ни одного шага «**** ШАГ ****»"))
        _finalize_workout(workout, hr_zones or {}, plan)

    for number, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue

        header = _WORKOUT_RE.match(line)
        if header:
            finish_workout()
            workout = MarkedWorkout(line=number)
            _parse_header(header.group("rest"), workout, number, plan, default_year)
            plan.workouts.append(workout)
            step = None
            stack = []
            continue

        if line.startswith("****"):
            if workout is None:
                plan.errors.append(ParseIssue(number, "маркер до первого заголовка «==== ТРЕНИРОВКА ===="))
                continue
            if _STEP_RE.match(line):
                step = MarkedStep(line=number)
                container().append(step)
            elif _REPEAT_END_RE.match(line):
                step = None
                if not stack:
                    plan.errors.append(ParseIssue(number, "«КОНЕЦ ПОВТОРА» без открытого повтора"))
                else:
                    closed = stack.pop()
                    if not _has_steps(closed.items):
                        plan.errors.append(ParseIssue(closed.line, "в повторе нет ни одного шага"))
            elif _REPEAT_RE.match(line):
                step = None
                raw_count = _REPEAT_RE.match(line).group("count") or ""
                if not raw_count.isdigit() or int(raw_count) < 1:
                    plan.errors.append(ParseIssue(number, f"число повторов должно быть целым ≥ 1, получено «{raw_count}»"))
                    raw_count = "1"
                repeat = MarkedRepeat(line=number, count=int(raw_count))
                container().append(repeat)
                stack.append(repeat)
            else:
                plan.errors.append(ParseIssue(number, f"неизвестный маркер «{line}»"))
            continue

        if workout is None:
            if not ignored_preamble:
                plan.warnings.append(ParseIssue(number, "текст до первой тренировки не используется"))
                ignored_preamble = True
            continue

        label_match = _LABEL_RE.match(line)
        label = label_match.group("label").strip() if label_match else ""
        value = label_match.group("value").strip() if label_match else line
        key = label.casefold()

        if key in _WORKOUT_LABELS or step is None:
            if step is None and _has_steps(workout.items) and key not in _WORKOUT_LABELS:
                plan.warnings.append(ParseIssue(number, f"строка вне шага не используется: «{line}»"))
                continue
            workout.meta.append((number, label, value))
            continue

        if key not in _STEP_LABELS:
            plan.warnings.append(
                ParseIssue(number, f"неизвестное поле шага «{label or line}» сохранено только как примечание")
            )
        step.fields.append((number, label, value))

    finish_workout()
    if not plan.workouts:
        plan.errors.append(ParseIssue(0, "не найдено ни одной тренировки «==== ТРЕНИРОВКА ====»"))
    return plan


def _has_steps(items: list[MarkedItem]) -> bool:
    return any(isinstance(item, MarkedStep) or _has_steps(item.items) for item in items)


def _parse_header(rest: str, workout: MarkedWorkout, line: int, plan: MarkedPlan, default_year: int | None) -> None:
    parts = _TITLE_SPLIT_RE.split(rest.strip(), maxsplit=1)
    head = parts[0].strip()
    title = parts[1].strip() if len(parts) > 1 else ""

    if head.casefold() in {"без даты", "без даты."}:
        workout.title = title
        return

    match = _HEADER_DATE_RE.match(head)
    if not match:
        # No recognisable date: the whole remainder is the title.
        workout.title = rest.strip()
        return

    workout.title = title
    day, month = int(match.group("day")), int(match.group("month"))
    weekday_text = (match.group("weekday") or "").strip().casefold()
    expected = _WEEKDAY_ALIASES.get(weekday_text)
    raw_year = match.group("year")
    try:
        if raw_year:
            workout.date = date(int(raw_year) + (2000 if len(raw_year) == 2 else 0), month, day)
        elif default_year:
            workout.date = date(default_year, month, day)
        else:
            from .garmin_step_mapper import infer_date

            # Nearest real date to today, preferring the written weekday.
            workout.date = infer_date(month, day, weekday=expected)
            if workout.date is None:
                raise ValueError(head)
    except ValueError:
        plan.errors.append(ParseIssue(line, f"некорректная дата «{head}»"))
        return
    if not raw_year:
        plan.warnings.append(ParseIssue(line, f"в дате не указан год, использован {workout.date.year}"))

    if weekday_text and expected is not None and expected != workout.date.weekday():
        actual = _WEEKDAYS_RU[workout.date.weekday()]
        plan.warnings.append(
            ParseIssue(line, f"{workout.date:%d.%m.%Y} — это {actual}, а в заголовке «{weekday_text}»")
        )


# ---------------------------------------------------------------------------
# Field interpretation
# ---------------------------------------------------------------------------

def _finalize_workout(workout: MarkedWorkout, hr_zones: dict[str, Any], plan: MarkedPlan) -> None:
    for line, label, value in workout.meta:
        key = _WORKOUT_LABELS.get(label.casefold())
        if key == "total_distance":
            km = _parse_distance(value)
            if km is None:
                plan.warnings.append(ParseIssue(line, f"не удалось прочитать общую дистанцию «{value}»"))
            workout.total_km = km
        elif key == "total_duration":
            seconds = _parse_duration(value)
            if seconds is None:
                plan.warnings.append(ParseIssue(line, f"не удалось прочитать общую длительность «{value}»"))
            workout.total_minutes = round(seconds / 60, 1) if seconds else None

    for step in iter_marked_steps(workout.items):
        _finalize_step(step, hr_zones, plan)


def iter_marked_steps(items: list[MarkedItem]):
    """Yield every step of a workout's item tree in execution-source order."""
    for item in items:
        if isinstance(item, MarkedStep):
            yield item
        else:
            yield from iter_marked_steps(item.items)



def _finalize_step(step: MarkedStep, hr_zones: dict[str, Any], plan: MarkedPlan) -> None:
    targets: list[Target] = []
    for line, label, value in step.fields:
        key = _STEP_LABELS.get(label.casefold())
        if key == "kind" and not step.kind:
            step.kind = value
            step.is_sbu = value.casefold() == "сбу"
        elif key == "distance":
            km = _parse_distance(value)
            if km is None:
                plan.errors.append(ParseIssue(line, f"не удалось прочитать дистанцию «{value}» (нужно число и м/км)"))
                continue
            if step.km is not None or step.seconds is not None:
                plan.warnings.append(ParseIssue(line, "у шага уже есть дистанция или длительность; строка не используется"))
                continue
            _warn_if_approximate(value, line, plan)
            step.km = km
        elif key == "duration":
            seconds = _parse_duration(value)
            if seconds is None:
                plan.errors.append(ParseIssue(line, f"не удалось прочитать длительность «{value}» (нужно число и сек/мин/ч)"))
                continue
            if step.km is not None or step.seconds is not None:
                plan.warnings.append(ParseIssue(line, "у шага уже есть дистанция или длительность; строка не используется"))
                continue
            _warn_if_approximate(value, line, plan)
            step.seconds = seconds
        elif key in {"hr", "pace", "cadence"}:
            target = _parse_target(key, value, line, hr_zones, plan)
            if target is not None:
                targets.append(target)
        elif key == "drills":
            step.drills = _parse_drills(value, line, plan)

    if not step.kind:
        plan.warnings.append(ParseIssue(step.line, "у шага не указан «Тип»; интенсивность не задана"))

    if step.is_sbu:
        if step.drills is None:
            plan.warnings.append(ParseIssue(step.line, "СБУ без строки «Упражнения»: будет стандартный набор упражнений"))
        return

    if len(targets) > 1:
        plan.warnings.append(
            ParseIssue(step.line, "у шага несколько целей; Garmin поддерживает одну, использована первая")
        )
    step.target = targets[0] if targets else None

    if step.km is None and step.seconds is None:
        plan.warnings.append(ParseIssue(
            step.line,
            "не указаны дистанция или длительность: шаг завершается кнопкой круга",
            code="missing_measure",
        ))
        if step.target is not None:
            plan.warnings.append(ParseIssue(step.line, "цель шага без дистанции/длительности не используется"))
            step.target = None


def _warn_if_approximate(value: str, line: int, plan: MarkedPlan) -> None:
    if _APPROX_RE.search(value):
        plan.warnings.append(ParseIssue(line, f"приблизительное значение «{value}» использовано как точное"))


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


def _parse_distance(value: str) -> float | None:
    match = _DISTANCE_RE.search(value)
    if not match:
        return None
    number = _to_float(match.group("value"))
    unit = match.group("unit").casefold()
    km = number if unit.startswith("к") or unit == "km" else number / 1000
    return round(km, 3) if km > 0 else None


def _parse_duration(value: str) -> int | None:
    total = 0.0
    for match in _DURATION_RE.finditer(value):
        number = _to_float(match.group("value"))
        unit = match.group("unit").casefold()
        if unit in {"ч", "час", "часа", "часов", "h"}:
            total += number * 3600
        elif unit.startswith("мин") or unit == "min":
            total += number * 60
        else:
            total += number
    seconds = int(round(total))
    return seconds if seconds > 0 else None


def _parse_target(
    kind: str, value: str, line: int, hr_zones: dict[str, Any], plan: MarkedPlan
) -> Target | None:
    if not value or _NO_VALUE_RE.match(value):
        return None

    if kind == "pace":
        paces = [int(m.group("min")) * 60 + int(m.group("sec")) for m in _PACE_RE.finditer(value)]
        paces = [p for p in paces if p >= 60]
        if not paces:
            plan.warnings.append(ParseIssue(line, f"темп «{value}» не распознан (нужно ММ:СС); цель не задана"))
            return None
        if len(paces) == 1 or paces[0] == paces[1]:
            return Target("pace", paces[0] - PACE_SINGLE_VALUE_WINDOW_SEC, paces[0] + PACE_SINGLE_VALUE_WINDOW_SEC)
        low, high = sorted(paces[:2])
        return Target("pace", low, high)

    zone = _ZONE_RE.search(value) if kind == "hr" else None
    if zone:
        bounds = _lookup_zone(hr_zones, zone.group("zone"))
        if bounds is not None:
            return Target("hr", bounds[0], bounds[1], zone=f"Z{zone.group('zone')}")

    bounds_match = _RANGE_RE.search(value)
    if bounds_match:
        low, high = sorted((int(bounds_match.group("low")), int(bounds_match.group("high"))))
        if low < high and 30 <= low and high <= 250:
            return Target(kind, low, high)
    if zone:
        plan.warnings.append(
            ParseIssue(line, f"зона Z{zone.group('zone')} не настроена в HR-профиле; цель по пульсу не задана")
        )
        return None
    label = "пульс" if kind == "hr" else "частота шагов"
    plan.warnings.append(
        ParseIssue(line, f"{label} «{value}» не задаёт полный диапазон; цель не задана, границы не додумываются")
    )
    return None


def _lookup_zone(hr_zones: dict[str, Any], number: str) -> tuple[int, int] | None:
    for key, bounds in (hr_zones or {}).items():
        if str(key).casefold() in {f"zone{number}", f"z{number}"} and isinstance(bounds, dict):
            try:
                low, high = int(bounds["low"]), int(bounds["high"])
            except (KeyError, TypeError, ValueError):
                return None
            return (low, high) if low < high else None
    return None


def _parse_drills(value: str, line: int, plan: MarkedPlan) -> list[dict[str, Any]] | None:
    drills: list[dict[str, Any]] = []
    for chunk in re.split(r"[;\n]", value):
        chunk = chunk.strip().rstrip(".")
        if not chunk:
            continue
        match = _DRILL_RE.match(chunk)
        if not match:
            plan.warnings.append(
                ParseIssue(line, f"упражнение «{chunk}» без повторов/длительности: использовано 2×60 сек")
            )
            drills.append({"name": chunk, "seconds": 60, "reps": 2})
            continue
        seconds = _to_float(match.group("value"))
        if match.group("unit").casefold() in {"мин", "min"}:
            seconds *= 60
        reps = match.group("reps")
        if reps is None:
            plan.warnings.append(ParseIssue(line, f"у упражнения «{match.group('name')}» не указаны повторы: использован 1"))
        drills.append({
            "name": match.group("name").strip(),
            "seconds": max(1, int(round(seconds))),
            "reps": int(reps) if reps else 1,
        })
    return drills or None


# ---------------------------------------------------------------------------
# Compilation to Garmin YAML
# ---------------------------------------------------------------------------

def plan_to_yaml_data(plan: MarkedPlan) -> dict[str, Any]:
    """Compile a parsed plan into the canonical Garmin YAML structure."""
    workouts: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, workout in enumerate(plan.workouts, 1):
        steps: list[dict[str, Any]] = []
        _emit_items(workout.items, steps)

        identifier = _workout_identifier(workout, index)
        candidate, suffix = identifier, 2
        while candidate in used:
            candidate = f"{identifier}_{suffix}"
            suffix += 1
        used.add(candidate)

        entry: dict[str, Any] = {"filename": candidate, "name": candidate}
        desc = _workout_desc(workout)
        if desc:
            entry["desc"] = desc
        if workout.total_km is not None:
            entry["distance_km"] = workout.total_km
        if workout.total_minutes is not None:
            entry["estimated_duration_min"] = workout.total_minutes
        entry["steps"] = steps
        workouts.append(entry)
    return {"workouts": workouts}


def _emit_items(items: list[MarkedItem], out: list[dict[str, Any]]) -> None:
    for item in items:
        if isinstance(item, MarkedStep):
            out.append(_step_to_yaml(item))
            continue
        start = len(out)
        _emit_items(item.items, out)
        if item.count > 1 and len(out) > start:
            # back_to_offset is the YAML index of the first body step; both
            # builders translate it to the FIT index (sbu_block expansion).
            out.append({"type": "repeat", "back_to_offset": start, "count": item.count})


def _step_to_yaml(step: MarkedStep) -> dict[str, Any]:
    if step.is_sbu:
        result: dict[str, Any] = {"type": "sbu_block"}
        if step.drills:
            result["drills"] = [dict(drill) for drill in step.drills]
        return result

    if step.km is not None:
        prefix, measure = "dist", {"km": step.km}
    elif step.seconds is not None:
        prefix, measure = "time", {"seconds": step.seconds}
    else:
        prefix, measure = None, {}

    target = step.target
    if prefix is None:
        result = {"type": "open_step"}
    elif target is None:
        result = {"type": "dist_open" if prefix == "dist" else "time_step", **measure}
    else:
        result = {"type": f"{prefix}_{target.kind}", **measure}
        if target.kind == "hr":
            result.update(hr_low=target.low, hr_high=target.high)
        elif target.kind == "pace":
            result.update(pace_fast=_format_pace(target.low), pace_slow=_format_pace(target.high))
        else:
            result.update(cad_low=target.low, cad_high=target.high)

    intensity = _INTENSITY_BY_KIND.get(step.kind.casefold())
    if intensity:
        result["intensity"] = intensity
    return result


def _format_pace(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _slug(title: str) -> str:
    text = title.casefold().translate(_TRANSLIT)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    parts = [part.capitalize() for part in text.split("_") if part]
    return "_".join(parts)[:40].strip("_")


def _workout_identifier(workout: MarkedWorkout, index: int) -> str:
    slug = _slug(workout.title) or f"Workout_{index}"
    if workout.date is None:
        return slug
    iso_week = workout.date.isocalendar()[1]
    weekday = _WEEKDAYS_EN[workout.date.weekday()]
    return f"W{iso_week:02d}_{workout.date:%m-%d}_{weekday}_{slug}"


def _workout_desc(workout: MarkedWorkout) -> str:
    parts = [workout.title] if workout.title else []
    for _line, label, value in workout.meta:
        key = _WORKOUT_LABELS.get(label.casefold())
        if key in {"total_distance", "total_duration"}:
            continue
        text = f"{label}: {value}" if label else value
        if text:
            parts.append(text)
    return ". ".join(parts)


def compile_marked_text(
    text: str,
    *,
    hr_zones: dict[str, Any] | None = None,
    default_year: int | None = None,
) -> MarkedCompileResult:
    """Parse marked text, compile it to YAML data and validate the result."""
    from .plan_validator import validate_plan_data

    plan = parse_marked_plan(text, hr_zones=hr_zones, default_year=default_year)
    warnings = [str(issue) for issue in plan.warnings]
    if plan.errors:
        return MarkedCompileResult(None, [str(issue) for issue in plan.errors], warnings, plan)

    data = plan_to_yaml_data(plan)
    errors, validator_warnings = validate_plan_data(data, enforce_filename_name_match=True)
    warnings.extend(validator_warnings)
    return MarkedCompileResult(None if errors else data, list(errors), warnings, plan)


# ---------------------------------------------------------------------------
# Rendering back to marked text
# ---------------------------------------------------------------------------

def render_marked_plan(plan: MarkedPlan) -> str:
    """Render a parsed plan as canonical marked text (normalised markers and spacing)."""
    blocks: list[str] = []
    for workout in plan.workouts:
        lines = [_render_header(workout)]
        lines.extend(_render_field(label, value) for _line, label, value in workout.meta)
        _render_items(workout.items, lines)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _render_header(workout: MarkedWorkout) -> str:
    if workout.date is None:
        when = "без даты"
    else:
        when = f"{workout.date:%d.%m.%Y} ({_WEEKDAYS_RU[workout.date.weekday()]})"
    return f"{WORKOUT_MARKER} {when} — {workout.title}".rstrip(" —")


def _render_field(label: str, value: str) -> str:
    return f"{label}: {value}" if label else value


def _render_items(items: list[MarkedItem], lines: list[str]) -> None:
    for item in items:
        if isinstance(item, MarkedStep):
            lines.extend(["", STEP_MARKER])
            lines.extend(_render_field(label, value) for _line, label, value in item.fields)
        else:
            lines.extend(["", f"**** ПОВТОР: {item.count} РАЗ ****"])
            _render_items(item.items, lines)
            lines.append(REPEAT_END_MARKER)


# ---------------------------------------------------------------------------
# Garmin YAML -> marked text (for human review of generated plans)
# ---------------------------------------------------------------------------

_KIND_BY_INTENSITY = {
    "warmup": "разминка",
    "cooldown": "заминка",
    "recovery": "восстановление",
    "active": "работа",
}


def plan_data_to_marked_text(data: dict[str, Any]) -> str:
    """Render Garmin YAML plan data as marked text a person can check and edit.

    Repeats are shown as nested ``ПОВТОР`` groups, distances/durations in
    natural units, and targets in the notation the parser reads back, so the
    text compiles to the same steps (identifiers may differ: they are derived
    from the title).
    """
    from .garmin_step_mapper import extract_date_from_filename
    from .plan_domain import plan_from_data

    plan = MarkedPlan()
    for workout in plan_from_data(data).workouts:
        marked = MarkedWorkout(line=0, title=_review_title(workout))
        date_text = extract_date_from_filename(workout.filename or "")
        if date_text:
            marked.date = date.fromisoformat(date_text)
        if workout.distance_km:
            marked.meta.append((0, "Общая дистанция", f"{_number(float(workout.distance_km))} км"))
        if workout.estimated_duration_min:
            marked.meta.append((0, "Общая длительность", f"{_number(float(workout.estimated_duration_min))} мин"))
        marked.items = _steps_to_items(workout.steps)
        plan.workouts.append(marked)
    return render_marked_plan(plan)


def _review_title(workout) -> str:
    desc = (workout.desc or "").strip()
    if desc:
        return desc.split(". ")[0].strip()
    return workout.name or workout.filename or ""


def _steps_to_items(steps) -> list[MarkedItem]:
    """Fold flat YAML steps (repeat after its body) back into a tree."""
    nodes: list[tuple[int, MarkedItem]] = []
    for index, step in enumerate(steps):
        if step.step_type != "repeat":
            nodes.append((index, _step_to_marked(step)))
            continue
        back_to = int(step.back_to_offset or 0)
        body: list[MarkedItem] = []
        while nodes and nodes[-1][0] >= back_to:
            body.insert(0, nodes.pop()[1])
        nodes.append((back_to, MarkedRepeat(line=0, count=int(step.count or 1), items=body)))
    return [item for _start, item in nodes]


def _step_to_marked(step) -> MarkedStep:
    from .plan_domain import PACE_CONSTANT_VALUES

    fields: list[tuple[int, str, str]] = []
    stype = step.step_type or ""
    if stype == "sbu_block":
        fields.append((0, "Тип", "СБУ"))
        if step.drills:
            drills = "; ".join(
                f"{drill.name} — {drill.reps or 2}×{drill.seconds or 60} сек" for drill in step.drills
            )
            fields.append((0, "Упражнения", drills))
        return MarkedStep(line=0, fields=fields)

    kind = _KIND_BY_INTENSITY.get(step.intensity or "", "работа")
    fields.append((0, "Тип", kind))
    if stype.startswith("dist_") and step.km:
        km = float(step.km)
        fields.append((0, "Дистанция", f"{_number(km)} км" if km >= 1 else f"{round(km * 1000)} м"))
    elif (stype.startswith("time_") or stype == "time_step") and step.seconds:
        fields.append((0, "Длительность", _duration_text(int(step.seconds))))
    if stype.endswith("_hr"):
        fields.append((0, "Пульс", f"{step.hr_low}–{step.hr_high} уд/мин"))
    elif stype.endswith("_pace"):
        fast = PACE_CONSTANT_VALUES.get(str(step.pace_fast), str(step.pace_fast))
        slow = PACE_CONSTANT_VALUES.get(str(step.pace_slow), str(step.pace_slow))
        fields.append((0, "Темп", f"{fast}–{slow} мин/км"))
    elif stype.endswith("_cadence"):
        fields.append((0, "Частота шагов", f"{step.cad_low}–{step.cad_high}"))
    return MarkedStep(line=0, fields=fields)


def _number(value: float) -> str:
    return f"{value:g}"


def _duration_text(seconds: int) -> str:
    if seconds % 60 == 0:
        return f"{seconds // 60} мин"
    if seconds > 60:
        return f"{seconds // 60} мин {seconds % 60} сек"
    return f"{seconds} сек"
