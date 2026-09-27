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
_WEEKDAY_WORDS = r"пн|вт|ср|чт|пт|сб|вс|понедельник|вторник|среда|четверг|пятница|суббота|воскресенье"
_DATE_HEADER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?P<date>\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s*"
    rf"(?:\(?\s*(?P<weekday>{_WEEKDAY_WORDS})\s*\)?)?"
    r"\s*(?P<sep>[,:—–-])?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
# "вт 3.03: ..." -- weekday before the date
_WEEKDAY_FIRST_RE = re.compile(
    rf"^\s*(?P<weekday>{_WEEKDAY_WORDS})\.?\s+(?P<date>\d{{1,2}}\.\d{{1,2}}(?:\.\d{{2,4}})?)"
    r"\s*(?P<sep>[,:—–-])?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
# "чт: ..." -- weekday only, no date
_WEEKDAY_ONLY_RE = re.compile(rf"^\s*(?P<weekday>{_WEEKDAY_WORDS})\s*:\s*(?P<rest>.+)$", re.IGNORECASE)
_MEASURE_RE = re.compile(
    rf"(?P<value>{_NUMBER})\s*(?P<unit>км|km|м|m|мин(?:ут[аы]?)?|min|сек(?:унд[аы]?)?|с|s)(?![а-яa-z])",
    re.IGNORECASE,
)
_PACE_RANGE_RE = re.compile(r"(?<![\d:])(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})(?![\d:])")
# Punctuation around a range is fine ("пульс 135-145,"); only a decimal
# continuation ("1,135-145" / "135-145.5") means these are not HR values.
_HR_RANGE_RE = re.compile(r"(?<![\d:])(?<!\d[.,])(\d{2,3})\s*[-–—]\s*(\d{2,3})(?![\d:])(?![.,]\d)")
_HR_CAP_RE = re.compile(r"пульс\w*\s*(?:до|не выше|<=?|≤)\s*(\d{2,3})", re.IGNORECASE)
_INTERVAL_RE = re.compile(
    r"^\s*(?P<count>\d{1,2})\s*(?:[xх×*]\s*(?=\d)|цикл(?:а|ов)?\s*:?\s*|раз\s*:?\s*)(?P<work>.+)$",
    re.IGNORECASE,
)
# "Интервалы 6x800м": a title that names the interval set without targets.
_INTERVAL_TITLE_RE = re.compile(r"^[А-Яа-яA-Za-z][^\d]*\d+\s*[xх×]\s*\d", re.IGNORECASE)
# "Пороговая тренировка: разминка 2 км, ..." -- a title before the first step.
_COLON_TITLE_RE = re.compile(r"^(?P<title>[А-ЯA-Zа-яa-z«\"][^:\d]{2,60}?)\s*:\s*(?P<rest>.*\d.*)$")
# "Итого: 10 км" -- the colon matters: "всего 20 минут бега" is a step, not a summary.
_SUMMARY_RE = re.compile(r"^\s*(?:итого|всего)\s*:\s*(?P<rest>.*)$", re.IGNORECASE)
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
    r"комфортно|тяжел|трудно|разговар|разговор|усили|"
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
    for raw in _join_wrapped(_normalise(block_text).splitlines()):
        # Several sentences on one line: split at ". " before a capital/digit.
        for part in re.split(r"(?<=[^\d])\.\s+(?=[А-ЯA-Z0-9])", raw.strip()):
            part = part.strip().rstrip(".").strip()
            # Coach shorthand chains segments with " + " (outside parentheses).
            # A cycle line ("5 циклов: A + B") keeps its " + " -- it joins work and recovery.
            chained = " + " in part and not _INTERVAL_RE.match(part)
            for segment in _split_plus(part) if chained else [part]:
                segment = _expand_shorthand(segment.strip())
                for clause in _split_clauses(segment):
                    if clause:
                        lines.append(clause)
    return lines


def _join_wrapped(raw_lines: list[str]) -> list[str]:
    """Re-join a sentence wrapped over several lines (next line lowercase or after a comma)."""
    joined: list[str] = []
    for raw in raw_lines:
        line = raw.strip()
        if joined and line and joined[-1] and (line[0].islower() or joined[-1].endswith(",")):
            joined[-1] = f"{joined[-1]} {line}"
        else:
            joined.append(line)
    return joined


_CLAUSE_SPLIT_RE = re.compile(
    r"\s*[,;]\s*(?:(?:а\s+)?затем|потом|после этого|и)?\s*|\s+(?:затем|потом|после этого)\s+",
    re.IGNORECASE,
)
_RECOVERY_START_RE = re.compile(r"^(?:отдых|восстановлени|трусц|между|спуск)", re.IGNORECASE)


def _split_clauses(line: str) -> list[str]:
    """Split "разминка 2 км, затем 5x1 км ..., отдых 400 м, заминка 1 км" into steps.

    A part without its own distance/duration ("пульс 135-145", "ровно")
    belongs to the step before it; a recovery part right after an interval
    ("отдых 400 м трусцой") stays in that interval clause. Lines with fewer
    than two measured parts are returned unchanged.
    """
    if _INTERVAL_RE.match(line) and len(_MEASURE_RE.findall(line)) <= 2:
        return [line]  # "6x800м по ..., восстановление 400 м" is one interval clause
    if _SUMMARY_RE.match(line) or _SBU_RE.match(line):
        return [line]  # "Итого: 10 км, 55 мин" / "СБУ: A 30с x2, B 30с x2" are single lines
    clauses: list[str] = []
    for part in (p for p in _CLAUSE_SPLIT_RE.split(line) if p and p.strip()):
        part = part.strip()
        has_measure = bool(_MEASURE_RE.search(part))
        joins_interval = (
            clauses and _INTERVAL_RE.match(clauses[-1]) and _RECOVERY_START_RE.match(part)
        )
        if clauses and (not has_measure or joins_interval):
            clauses[-1] = f"{clauses[-1]}, {part}"
        else:
            clauses.append(part)
    return clauses if len(clauses) >= 2 else [line]


def _split_plus(text: str) -> list[str]:
    parts, depth, current = [], 0, []
    tokens = re.split(r"(\s\+\s|[()\[\]])", text)
    for token in tokens:
        if token in ("(", "["):
            depth += 1
        elif token in (")", "]"):
            depth -= 1
        if token == " + " and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(token)
    parts.append("".join(current))
    return parts


# Coach shorthand -> the formal wording the rules below understand. Only
# unambiguous forms: "р2"/"з1"/"темп5" (letter first) are kilometres, while
# "10р" could be 10 minutes or 10 km and is left alone (-> LLM).
_SHORTHAND = [
    (re.compile(r"^р\s*(\d+(?:[.,]\d+)?)(?!\s*(?:км|km|м|m|мин|сек|с)(?![а-яa-z]))(?=\s|\(|$)", re.IGNORECASE), r"Разминка \1 км"),
    (re.compile(r"^з\s*(\d+(?:[.,]\d+)?)(?!\s*(?:км|km|м|m|мин|сек|с)(?![а-яa-z]))(?=\s|\(|$)", re.IGNORECASE), r"Заминка \1 км"),
    (re.compile(r"^темп\s*(\d+(?:[.,]\d+)?)(?!\s*(?:км|km|м|m|мин|сек|с)(?![а-яa-z]))(?=\s|\(|$)", re.IGNORECASE), r"Темп \1 км"),
    # dotted pace range "4.50-5.00" -> "4:50-5:00"
    (re.compile(r"(?<![\d.:])(\d{1,2})\.(\d{2})\s*-\s*(\d{1,2})\.(\d{2})(?![\d.:])"), r"\1:\2-\3:\4"),
    # "6х800" (no unit, >= 100) -> metres
    (re.compile(r"^(\d{1,2})\s*[xх×]\s*(\d{3,5})(?!\s*(?:м|км|m|km|мин|сек|с)\b)(?![\d.,])", re.IGNORECASE),
     r"\1x\2 м"),
    # "отд 400" -> recovery 400 m, "отд90с" / "отд 60с" -> recovery seconds
    (re.compile(r"\bотд\.?\s*(\d{3,4})(?!\s*(?:м|км|с|сек|мин)\b)(?![\d.,])", re.IGNORECASE),
     r"восстановление \1 м"),
    (re.compile(r"\bотд\.?\s*(\d{1,3})\s*(?:с|сек)\b!?", re.IGNORECASE), r"восстановление \1 сек"),
    # "пульс165-172" -> "пульс 165-172"
    (re.compile(r"пульс(?=\d)", re.IGNORECASE), "пульс "),
]


def _expand_shorthand(segment: str) -> str:
    for pattern, replacement in _SHORTHAND:
        segment = pattern.sub(replacement, segment)
    return segment


def _convert(block_text: str) -> str:
    lines = _split_lines(block_text)
    if not lines:
        raise _NotUnderstood
    if any(_UNSUPPORTED_RE.search(line) for line in lines) or any(map(_has_unit_without_number, lines)):
        raise _NotUnderstood

    header_date = "без даты"
    title = ""
    first = _DATE_HEADER_RE.match(lines[0]) or _WEEKDAY_FIRST_RE.match(lines[0])
    weekday_only = None if first else _WEEKDAY_ONLY_RE.match(lines[0])
    if first:
        weekday = (first.group("weekday") or "").lower()
        weekday = _WEEKDAY_NAMES.get(weekday, weekday)
        header_date = first.group("date") + (f" ({weekday})" if weekday else "")
    header = first or weekday_only
    if header:
        rest = _expand_shorthand(header.group("rest").strip())
        lines = lines[1:]
        if rest and header.groupdict().get("sep") == "-" and not re.search(r"\d", rest):
            # "12.10 (пн) — Восстановление": words after a dash name the workout,
            # even when they are a step role ("Восстановление", "Ускорения").
            title = rest
        elif rest:
            lines.insert(0, rest)

    if not title and lines and _is_title(lines[0]):
        title = lines.pop(0)
    elif not title and lines:
        colon_title = _COLON_TITLE_RE.match(lines[0])
        if colon_title and not _role_only(colon_title.group("title")) and not re.match(
            r"^(?:сбу|итого|всего|другое)$", colon_title.group("title").strip(), re.IGNORECASE
        ):
            title = colon_title.group("title").strip()
            lines[0] = colon_title.group("rest").strip()

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
    _check_role_order(body)
    header = f"==== ТРЕНИРОВКА ==== {header_date}" + (f" — {title}" if title else "")
    return "\n".join([header, *meta, "", *body]) + "\n"


_UNIT_WORD_RE = re.compile(
    r"(?<![а-яa-z])(?:километр(?!ов[аоуыейи]|овк)\w*|км|метр(?!ов[аоуыейи]|овк)\w*|минут(?!к|ок)\w*|мин|"
    r"секунд\w*|сек|час(?:а|ов)?)(?![а-яa-z])",
    re.IGNORECASE,
)


# Rate units name no amount of their own: "уд/мин", "мин/км", "шаг/мин".
_RATE_UNIT_RE = re.compile(r"(?:уд|шаг\w*|мин|сек|км|м)\s*/\s*(?:мин|км|сек)\.?", re.IGNORECASE)


def _has_unit_without_number(line: str) -> bool:
    """"километр заминки", "км разминки", "беги час": a unit whose amount is a word."""
    line = _RATE_UNIT_RE.sub(" ", line)
    for match in _UNIT_WORD_RE.finditer(line):
        before = line[: match.start()].rstrip()
        if not re.search(r"\d(?:[.,]\d+)?\s*$", before) and not before.endswith(("x", "х", "×")):
            return True
    return False


def _check_role_order(body: list[str]) -> None:
    """Warmup must come first and cooldown last; otherwise the text's order is not the run's."""
    roles = [line.split(": ", 1)[1] for line in body if line.startswith("Тип: ")]
    seen_other = False
    for index, role in enumerate(roles):
        if role == "разминка" and seen_other:
            raise _NotUnderstood
        if role != "разминка":
            seen_other = True
        if role == "заминка" and any(r != "заминка" for r in roles[index + 1:]):
            raise _NotUnderstood


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


_CADENCE_RE = re.compile(
    r"(?:каденс\w*|частот\w*(?:\s+шаг\w*)?|cadence|spm)\D{0,12}?(?P<low>\d{2,3})\s*[-–—]\s*(?P<high>\d{2,3})"
    r"|(?P<low2>\d{2,3})\s*[-–—]\s*(?P<high2>\d{2,3})\s*(?:шаг\w*(?:\s*/\s*мин)?|spm)",
    re.IGNORECASE,
)


def _targets(text: str) -> list[tuple[str, str]]:
    """Every target stated in a step line, in reading order.

    A cadence range is recognised by its label ("каденс", "частота шагов",
    "шаг/мин") so it never becomes a heart-rate range. When a line names
    more than one target, all are passed on and the marked parser keeps the
    first with a warning (a Garmin step has one target).
    """
    found: list[tuple[int, str, str]] = []
    cadence = _CADENCE_RE.search(text)
    rest = text
    if cadence:
        low = int(cadence.group("low") or cadence.group("low2"))
        high = int(cadence.group("high") or cadence.group("high2"))
        found.append((cadence.start(), "Частота шагов", f"{low}-{high}"))
        rest = text[: cadence.start()] + " " * (cadence.end() - cadence.start()) + text[cadence.end():]
    pace = _PACE_RANGE_RE.search(rest)
    if pace:
        found.append((pace.start(), "Темп", f"{pace.group(1)}-{pace.group(2)} мин/км"))
    hr = _HR_RANGE_RE.search(rest)
    if hr:
        low, high = int(hr.group(1)), int(hr.group(2))
        if not 40 <= low < high <= 230:
            raise _NotUnderstood
        found.append((hr.start(), "Пульс", f"{low}-{high} уд/мин"))
    else:
        cap = _HR_CAP_RE.search(rest)
        if cap:
            # Upper-only cap: the marked parser encodes it as 60-cap.
            found.append((cap.start(), "Пульс", f"до {cap.group(1)} уд/мин"))
    return [(label, value) for _pos, label, value in sorted(found)]


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
    for label_name, target_value in _targets(text):
        lines.append(f"{label_name}: {target_value}")
    return lines


def _simple_step(line: str, pending_role: str | None) -> list[str]:
    return _step_lines(line, _role_of(line) or pending_role)


def _interval_steps(count: int, rest: str) -> list[str]:
    """``N x work[, recovery]`` or ``N циклов: work + recovery``."""
    parts = re.split(
        r"\s*[,+/]\s*(?=[^\d]*\d)|\s+(?=(?:восстановлени|отдых)\w*\s+\d)", rest, maxsplit=1
    )
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
