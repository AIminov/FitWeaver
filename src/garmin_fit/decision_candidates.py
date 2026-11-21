"""Experimental, offline rules for focused workout interpretation choices."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    key: str
    meaning: str
    value: str | int


@dataclass(frozen=True)
class Decision:
    candidates: tuple[Candidate, ...] = ()
    preferred: str = "clarify"


_INTERVAL = re.compile(r"\b(\d+)\s*[×хx]\s*\d+(?:[.,]\d+)?\s*(?:км|м)\b")
_CLOCK = re.compile(r"\b\d+:[0-5]\d\b")
_HR = re.compile(r"пульс\s+(не выше|не ниже)\s+(\d+)\b")


def build_decision(text: str) -> Decision:
    """Extract one decision axis. Multiple or unsupported axes require clarification."""
    text = " ".join(text.casefold().split())
    axes = []
    intervals = list(_INTERVAL.finditer(text))
    clocks = _CLOCK.findall(text)
    if len(intervals) == 1 and len(clocks) == 1:
        pace = bool(re.search(r"\bтемп(?:ом)?\b|мин/км", text))
        elapsed = bool(re.search(r"каждый отрезок за|на каждый отрезок", text))
        preferred = ("a" if elapsed else "b") if elapsed != pace else "clarify"
        axes.append(Decision((Candidate("a", "interval_duration", clocks[0]),
                              Candidate("b", "pace_per_km", clocks[0])), preferred))
    heart_rates = _HR.findall(text)
    if len(heart_rates) == 1:
        bound, bpm = heart_rates[0]
        if 30 <= int(bpm) <= 250:
            axes.append(Decision((Candidate("a", "lower_hr_bound", int(bpm)),
                                  Candidate("b", "upper_hr_bound", int(bpm))),
                                 "b" if bound == "не выше" else "a"))
    if len(intervals) == 1 and re.search(r"отдых|трусц|восстановлен", text):
        count = int(intervals[0][1])
        if count > 1 and not clocks:
            between = "только между отрезками" in text
            each = "включая последний" in text
            preferred = ("a" if between else "b") if between != each else "clarify"
            axes.append(Decision((Candidate("a", "recovery_count", count - 1),
                                  Candidate("b", "recovery_count", count)), preferred))
    if re.search(r"\bкруг\w*\b", text) and "отдых" in text and ("отрез" in text or "раза по" in text):
        between = "перед следующим кругом" in text
        each = "после каждого отрезка" in text
        preferred = ("a" if between else "b") if between != each else "clarify"
        axes.append(Decision((Candidate("a", "recovery_scope", "between_rounds"),
                              Candidate("b", "recovery_scope", "after_each_interval")), preferred))
    return axes[0] if len(axes) == 1 else Decision()
