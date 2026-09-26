"""Deterministic rules for common free-text workout lines (no LLM).

Turns one workout written the usual way ::

    14.04.2026 (вт)
    Интервалы 6x800м
    Разминка: 2 км (5:45-6:00)
    6x800м по 4:20-4:30, восстановление 400 м трусцой (5:30-6:00)
    Заминка: 1 км (5:45-6:00)
    Итого: ~10.2 км, 55 мин

into the marked format, which ``marked_plan`` then compiles and validates.

Precision over coverage: a workout is converted only when every line is
understood and every number in it is accounted for (numbers carry the facts).
Anything else returns ``None`` and the workout goes to the LLM as before.
"""

from __future__ import annotations

import re
from typing import Any

_NUMBER = r"\d+(?:[.,]\d+)?"
_DATE_HEADER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?P<date>\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s*"
    r"(?:\(?\s*(?P<weekday>пн|вт|ср|чт|пт|сб|вс|понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)\s*\)?)?"
    r"\s*[,:—–-]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_MEASURE_RE = re.compile(
    rf"(?P<value>{_NUMBER})\s*(?P<unit>км|km|м|m|мин(?:ут[аы]?)?|min|сек(?:унд[аы]?)?|с|s)(?![а-яa-z])",
    re.IGNORECASE,
)
_PACE_RANGE_RE = re.compile(r"(?<![\d:])(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})(?![\d:])")
_HR_RANGE_RE = re.compile(r"(?<![\d:.,])(\d{2,3})\s*[-–—]\s*(\d{2,3})(?![\d:.,])")
_HR_CAP_RE = re.compile(r"пульс\w*\s*(?:до|не выше|<=?|≤)\s*(\d{2,3})", re.IGNORECASE)
_INTERVAL_RE = re.compile(
    r"^\s*(?P<count>\d{1,2})\s*(?:[xх×*]\s*(?=\d)|цикл(?:а|ов)?\s*:?\s*|раз\s*:?\s*)(?P<work>.+)$",
    re.IGNORECASE,
)
# "Интервалы 6x800м": a title that names the interval set without targets.
_INTERVAL_TITLE_RE = re.compile(r"^[А-Яа-яA-Za-z][^\d]*\d+\s*[xх×]\s*\d", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"^\s*(?:итого|всего)\s*:?\s*(?P<rest>.*)$", re.IGNORECASE)
_SBU_RE = re.compile(r"^\s*сбу\s*:?\s*(?P<rest>.+)$", re.IGNORECASE)
_DRILL_RE = re.compile(
    r"^\s*(?P<name>[^\d,;]+?)\s+(?P<seconds>\d+)\s*(?:с|сек)\s*[xх×]\s*(?P<reps>\d+)\s*$",
    re.IGNORECASE,
)

_ROLE_WORDS = [
    (re.compile(r"\bразминк\w*", re.IGNORECASE), "разминка"),
    (re.compile(r"\bзаминк\w*", re.IGNORECASE), "заминка"),
    (re.compile(r"\b(?:восстановлени\w*|восстановительн\w*|отдых\w*)", re.IGNORECASE), "восстановление"),
    (re.compile(r"\b(?:темп|темпов\w*|работ\w*|быстро|ускорени\w*)\b", re.IGNORECASE), "работа"),
]
# Words that describe structure these rules do not model: leave such
# workouts to the LLM rather than guess.
_UNSUPPORTED_RE = re.compile(
    r"сери[яиейю]|повтор|лесенк|каждый|кажд|быстрее|медленнее|прогресс|или\b|если\b|до отказа|"
    r"между сериями|по самочувствию|ощущени|"
    # effort described only in words: the user should give a number
    r"комфортно|тяжел|трудно|разговар|усили|"
    # not running at all
    r"бассейн|плаван|вольн\w* стил|вело|йог|растяжк|\bзал\b|присед|жим|планк|отжиман|берпи|"
    r"пресс|\bкор\b|без бега|вместо бега|кругов",
    re.IGNORECASE,
)
_WEEKDAY_NAMES = {
    "пн": "понедельник", "вт": "вторник", "ср": "среда", "чт": "четверг",
    "пт": "пятница", "сб": "суббота", "вс": "воскресенье",
}


class _NotUnderstood(Exception):
    pass


def free_text_to_marked(block_text: str) -> str | None:
    """Marked-format text for one workout block, or None if any part is not understood."""
    try:
        return _convert(block_text)
    except _NotUnderstood:
        return None


def parse_workout_with_rules(
    block_text: str, *, hr_zones: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Compiled Garmin YAML workout for one block, or None to fall back to the LLM."""
    marked = free_text_to_marked(block_text)
    if marked is None:
        return None
    from .marked_plan import compile_marked_text

    compiled = compile_marked_text(marked, hr_zones=hr_zones)
    if compiled.data is None or len(compiled.data.get("workouts", [])) != 1:
        return None
    return compiled.data["workouts"][0]


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"[–—]", "-", text)
    return text


def _split_lines(block_text: str) -> list[str]:
    lines: list[str] = []
    for raw in _normalise(block_text).splitlines():
        # Several sentences on one line: split at ". " before a capital/digit.
        for part in re.split(r"(?<=[^\d])\.\s+(?=[А-ЯA-Z0-9])", raw.strip()):
            part = part.strip().rstrip(".").strip()
            if part:
                lines.append(part)
    return lines


def _convert(block_text: str) -> str:
    lines = _split_lines(block_text)
    if not lines:
        raise _NotUnderstood
    if any(_UNSUPPORTED_RE.search(line) for line in lines):
        raise _NotUnderstood

    header_date = "без даты"
    title = ""
    first = _DATE_HEADER_RE.match(lines[0])
    if first:
        weekday = (first.group("weekday") or "").lower()
        weekday = _WEEKDAY_NAMES.get(weekday, weekday)
        header_date = first.group("date") + (f" ({weekday})" if weekday else "")
        rest = first.group("rest").strip()
        lines = lines[1:]
        if rest:
            lines.insert(0, rest)

    if lines and _is_title(lines[0]):
        title = lines.pop(0)

    meta: list[str] = []
    body: list[str] = []
    pending_role: str | None = None
    for line in lines:
        summary = _SUMMARY_RE.match(line)
        if summary:
            meta.extend(_summary_lines(summary.group("rest")))
            continue
        sbu = _SBU_RE.match(line)
        if sbu:
            body.extend(_sbu_step(sbu.group("rest")))
            continue
        role_only = _role_only(line)
        if role_only:
            pending_role = role_only
            continue
        interval = _INTERVAL_RE.match(line)
        if interval:
            body.extend(_interval_steps(int(interval.group("count")), interval.group("work")))
            pending_role = None
            continue
        body.extend(_simple_step(line, pending_role))
        pending_role = None

    if not body:
        raise _NotUnderstood
    header = f"==== ТРЕНИРОВКА ==== {header_date}" + (f" — {title}" if title else "")
    return "\n".join([header, *meta, "", *body]) + "\n"


def _is_title(line: str) -> bool:
    """First line after the date that names the workout (no target, not a step)."""
    if _PACE_RANGE_RE.search(line) or _HR_RANGE_RE.search(line) or _HR_CAP_RE.search(line):
        return False
    if line[:1].isdigit() or _role_only(line) or _SUMMARY_RE.match(line) or _SBU_RE.match(line):
        return False
    if _MEASURE_RE.search(line) and not _INTERVAL_TITLE_RE.search(line):
        return False  # "Темп 5 км по ..." is a step; "Темповый бег" is a title
    return bool(re.match(r"^[А-ЯA-Zа-яa-z]", line))


def _role_only(line: str) -> str | None:
    stripped = line.strip().rstrip(":").strip()
    if _MEASURE_RE.search(stripped) or re.search(r"\d", stripped):
        return None
    for pattern, role in _ROLE_WORDS:
        if pattern.fullmatch(stripped):
            return role
    return None


def _role_of(text: str) -> str | None:
    for pattern, role in _ROLE_WORDS:
        if pattern.search(text):
            return role
    return None


def _measure(text: str) -> tuple[str, str]:
    """(field label, value) for the single distance/duration in text."""
    matches = list(_MEASURE_RE.finditer(text))
    if len(matches) != 1:
        raise _NotUnderstood
    match = matches[0]
    value = match.group("value").replace(",", ".")
    unit = match.group("unit").lower()
    if unit in {"км", "km"}:
        return "Дистанция", f"{value} км"
    if unit in {"м", "m"}:
        return "Дистанция", f"{value} м"
    if unit.startswith("мин") or unit == "min":
        return "Длительность", f"{value} мин"
    return "Длительность", f"{value} сек"


def _target(text: str) -> tuple[str, str] | None:
    pace = _PACE_RANGE_RE.search(text)
    if pace:
        return "Темп", f"{pace.group(1)}-{pace.group(2)} мин/км"
    hr = _HR_RANGE_RE.search(text)
    if hr:
        low, high = int(hr.group(1)), int(hr.group(2))
        if 40 <= low < high <= 230:
            return "Пульс", f"{low}-{high} уд/мин"
        raise _NotUnderstood
    cap = _HR_CAP_RE.search(text)
    if cap:
        # An upper cap alone is not a Garmin range; keep it as a note.
        return "Примечание", f"пульс до {cap.group(1)}"
    return None


def _check_numbers_consumed(text: str) -> None:
    """Every number must belong to a measure or a target we understood."""
    leftover = _MEASURE_RE.sub(" ", text)
    leftover = _PACE_RANGE_RE.sub(" ", leftover)
    leftover = _HR_RANGE_RE.sub(" ", leftover)
    leftover = _HR_CAP_RE.sub(" ", leftover)
    if re.search(r"\d", leftover):
        raise _NotUnderstood


def _step_lines(text: str, role: str | None) -> list[str]:
    _check_numbers_consumed(text)
    label, value = _measure(text)
    lines = ["**** ШАГ ****"]
    if role:
        lines.append(f"Тип: {role}")
    lines.append(f"{label}: {value}")
    target = _target(text)
    if target:
        lines.append(f"{target[0]}: {target[1]}")
    return lines


def _simple_step(line: str, pending_role: str | None) -> list[str]:
    return _step_lines(line, _role_of(line) or pending_role)


def _interval_steps(count: int, rest: str) -> list[str]:
    """``N x work[, recovery]`` or ``N циклов: work + recovery``."""
    parts = re.split(r"\s*[,+/]\s*(?=[^\d]*\d)", rest, maxsplit=1)
    work = parts[0]
    lines = [f"**** ПОВТОР: {count} РАЗ ****"]
    lines += _step_lines(work, "работа")
    if len(parts) == 2:
        lines += _step_lines(parts[1], "восстановление")
    lines.append("**** КОНЕЦ ПОВТОРА ****")
    return lines


def _sbu_step(rest: str) -> list[str]:
    drills = []
    for chunk in re.split(r"\s*[,;]\s*", rest.strip().rstrip(".")):
        match = _DRILL_RE.match(chunk)
        if not match:
            raise _NotUnderstood
        drills.append(f"{match.group('name').strip()} — {match.group('reps')}×{match.group('seconds')} сек")
    if not drills:
        raise _NotUnderstood
    return ["**** ШАГ ****", "Тип: СБУ", "Упражнения: " + "; ".join(drills)]


def _summary_lines(rest: str) -> list[str]:
    meta: list[str] = []
    approximate = bool(re.search(r"~|около|примерно", rest, re.IGNORECASE))
    prefix = "около " if approximate else ""
    for match in _MEASURE_RE.finditer(rest):
        value = match.group("value").replace(",", ".")
        unit = match.group("unit").lower()
        if unit in {"км", "km"}:
            meta.append(f"Общая дистанция: {prefix}{value} км")
        elif unit.startswith("мин") or unit == "min":
            meta.append(f"Общая длительность: {prefix}{value} мин")
    leftover = _MEASURE_RE.sub(" ", rest)
    if re.search(r"\d", leftover):
        raise _NotUnderstood
    return meta
