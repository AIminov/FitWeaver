"""
Maps FitWeaver YAML domain objects (WorkoutStep) to Garmin Connect
workout-service REST API payload dicts.

Payload spec: docs/GARMIN_PAYLOAD_SPEC.md

Supported step types
--------------------
dist_hr    → distance + HR target
time_hr    → time + HR target
dist_pace  → distance + pace (speed) target
time_pace  → time + pace (speed) target
dist_open  → distance, no target
time_step  → time, no target (recovery / rest)
open_step  → converted to 60 s recovery (lap-button not supported by REST API)
repeat     → RepeatGroupDTO wrapping steps from back_to_offset..current (nesting supported)
sbu_block  → RepeatGroupDTO list (one repeat group per drill, with step notes)
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any

from .plan_domain import PACE_CONSTANT_VALUES, Workout, WorkoutStep
from .sbu_block import DEFAULT_DRILLS as SBU_DEFAULT_DRILLS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — Garmin API IDs
# ---------------------------------------------------------------------------

SPORT_TYPE_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}

STEP_TYPE = {
    "warmup":   {"stepTypeId": 1, "stepTypeKey": "warmup",   "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    "rest":     {"stepTypeId": 5, "stepTypeKey": "rest",     "displayOrder": 5},
    "repeat":   {"stepTypeId": 6, "stepTypeKey": "repeat",   "displayOrder": 6},
}

END_COND_LAP_BUTTON = {
    "conditionTypeId": 1, "conditionTypeKey": "lap.button",
    "displayOrder": 1, "displayable": True,
}
END_COND_TIME = {
    "conditionTypeId": 2, "conditionTypeKey": "time",
    "displayOrder": 2, "displayable": True,
}
END_COND_DISTANCE = {
    "conditionTypeId": 3, "conditionTypeKey": "distance",
    "displayOrder": 3, "displayable": True,
}
END_COND_ITERATIONS = {
    "conditionTypeId": 7, "conditionTypeKey": "iterations",
    "displayOrder": 7, "displayable": False,
}

TARGET_NO  = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target",       "displayOrder": 1}
# id=4 "heart.rate.zone" — accepts raw BPM range via targetValueOne / targetValueTwo
#   (id=6 "heart.rate" is interpreted as pace/speed by Garmin Connect — do NOT use)
TARGET_HR  = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}
# id=7 "speed" — custom m/s range via targetValueOne / targetValueTwo
TARGET_SPD = {"workoutTargetTypeId": 7, "workoutTargetTypeKey": "speed",           "displayOrder": 7}
TARGET_CAD = {"workoutTargetTypeId": 3, "workoutTargetTypeKey": "cadence",        "displayOrder": 3}

# intensity field → Garmin stepTypeKey
_INTENSITY_TO_STEP_TYPE: dict[str, str] = {
    "warmup":   "warmup",
    "cooldown": "cooldown",
    "active":   "interval",
    "recovery": "recovery",
}
_DEFAULT_STEP_TYPE = "interval"

# SBU drill defaults (seconds)
_SBU_RECOVERY_SECS = 90.0
_SBU_DEFAULT_REPS = 2

# open_step fallback
_OPEN_STEP_FALLBACK_SECS = 60.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pace_to_mps(pace_str: str) -> float:
    """Convert "MM:SS" per km to metres per second."""
    pace_str = PACE_CONSTANT_VALUES.get(pace_str, pace_str)
    m, s = pace_str.split(":")
    total = int(m) * 60 + int(s)
    return round(1000.0 / total, 4)


def _km_to_m(km: float | int | str) -> float:
    return float(km) * 1000.0


def _intensity_to_step_key(intensity: str | None) -> str:
    if intensity is None:
        return _DEFAULT_STEP_TYPE
    return _INTENSITY_TO_STEP_TYPE.get(intensity, _DEFAULT_STEP_TYPE)


# ---------------------------------------------------------------------------
# Low-level step builders
# ---------------------------------------------------------------------------

def _executable_step(
    step_order: int,
    step_type_key: str,
    end_condition: dict[str, Any],
    end_condition_value: float,
    target_type: dict[str, Any],
    target_value_one: float | int | None = None,
    target_value_two: float | int | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """
    Build a single ExecutableStepDTO dict.

    target_value_one — lower bound (lower BPM / lower m/s / slower pace)
    target_value_two — upper bound (upper BPM / higher m/s / faster pace)

    description — Garmin Connect "workout step note" shown for the current step.

    Garmin Connect REST API uses targetValueOne / targetValueTwo (not Low/High).
    """
    step: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": step_order,
        "stepType": STEP_TYPE[step_type_key],
        "endCondition": end_condition,
        "endConditionValue": float(end_condition_value),
        "targetType": target_type,
    }
    if target_value_one is not None:
        step["targetValueOne"] = target_value_one
    if target_value_two is not None:
        step["targetValueTwo"] = target_value_two
    if description:
        step["description"] = description
    return step


def _repeat_group(
    step_order: int,
    iterations: int,
    child_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "RepeatGroupDTO",
        "stepOrder": step_order,
        "stepType": STEP_TYPE["repeat"],
        "numberOfIterations": iterations,
        "endCondition": END_COND_ITERATIONS,
        "endConditionValue": float(iterations),
        "smartRepeat": False,
        "workoutSteps": child_steps,
    }


# ---------------------------------------------------------------------------
# Per-step-type mappers
# ---------------------------------------------------------------------------

def _map_dist_hr(step: WorkoutStep, order: int) -> dict[str, Any]:
    return _executable_step(
        step_order=order,
        step_type_key=_intensity_to_step_key(step.intensity),
        end_condition=END_COND_DISTANCE,
        end_condition_value=_km_to_m(step.km),
        target_type=TARGET_HR,
        target_value_one=int(step.hr_low),
        target_value_two=int(step.hr_high),
    )


def _map_time_hr(step: WorkoutStep, order: int) -> dict[str, Any]:
    return _executable_step(
        step_order=order,
        step_type_key=_intensity_to_step_key(step.intensity),
        end_condition=END_COND_TIME,
        end_condition_value=float(step.seconds),
        target_type=TARGET_HR,
        target_value_one=int(step.hr_low),
        target_value_two=int(step.hr_high),
    )


def _map_dist_pace(step: WorkoutStep, order: int) -> dict[str, Any]:
    # pace_fast (faster = higher m/s) → targetValueTwo (upper bound)
    # pace_slow (slower = lower m/s)  → targetValueOne (lower bound)
    return _executable_step(
        step_order=order,
        step_type_key=_intensity_to_step_key(step.intensity),
        end_condition=END_COND_DISTANCE,
        end_condition_value=_km_to_m(step.km),
        target_type=TARGET_SPD,
        target_value_one=_pace_to_mps(str(step.pace_slow)),
        target_value_two=_pace_to_mps(str(step.pace_fast)),
    )


def _map_time_pace(step: WorkoutStep, order: int) -> dict[str, Any]:
    return _executable_step(
        step_order=order,
        step_type_key=_intensity_to_step_key(step.intensity),
        end_condition=END_COND_TIME,
        end_condition_value=float(step.seconds),
        target_type=TARGET_SPD,
        target_value_one=_pace_to_mps(str(step.pace_slow)),
        target_value_two=_pace_to_mps(str(step.pace_fast)),
    )


def _map_cadence(step: WorkoutStep, order: int, *, distance: bool) -> dict[str, Any]:
    return _executable_step(
        step_order=order,
        step_type_key=_intensity_to_step_key(step.intensity),
        end_condition=END_COND_DISTANCE if distance else END_COND_TIME,
        end_condition_value=_km_to_m(step.km) if distance else float(step.seconds),
        target_type=TARGET_CAD,
        target_value_one=int(step.cad_low),
        target_value_two=int(step.cad_high),
    )


def _map_dist_cadence(step: WorkoutStep, order: int) -> dict[str, Any]:
    return _map_cadence(step, order, distance=True)


def _map_time_cadence(step: WorkoutStep, order: int) -> dict[str, Any]:
    return _map_cadence(step, order, distance=False)


def _map_dist_open(step: WorkoutStep, order: int) -> dict[str, Any]:
    return _executable_step(
        step_order=order,
        step_type_key=_intensity_to_step_key(step.intensity),
        end_condition=END_COND_DISTANCE,
        end_condition_value=_km_to_m(step.km),
        target_type=TARGET_NO,
    )


def _map_time_step(step: WorkoutStep, order: int) -> dict[str, Any]:
    return _executable_step(
        step_order=order,
        step_type_key="recovery",
        end_condition=END_COND_TIME,
        end_condition_value=float(step.seconds),
        target_type=TARGET_NO,
    )


def _map_open_step(_step: WorkoutStep, order: int) -> dict[str, Any]:
    """open_step = lap button — not supported by REST API, replaced by 60 s recovery."""
    logger.debug("open_step converted to 60 s recovery (lap button not supported by API)")
    return _executable_step(
        step_order=order,
        step_type_key="recovery",
        end_condition=END_COND_TIME,
        end_condition_value=_OPEN_STEP_FALLBACK_SECS,
        target_type=TARGET_NO,
    )


_SBU_RECOVERY_LABEL = {"ru": "Отдых", "en": "Recovery"}
_SBU_DRILL_FALLBACK = {"ru": "Упражнение", "en": "Drill"}


def _map_sbu_block(step: WorkoutStep, order: int, language: str = "ru") -> list[dict[str, Any]]:
    """
    SBU block → one RepeatGroupDTO per drill.

    Each drill becomes: Repeat reps × [active step with description + recovery].
    Garmin Connect stores the step note as ExecutableStepDTO.description.

    Drill name/seconds/reps come from step.drills; if absent, use the same
    default drill set as the FIT builder.
    """
    recovery_label = _SBU_RECOVERY_LABEL.get(language, "Recovery")
    drill_fallback = _SBU_DRILL_FALLBACK.get(language, "Drill")

    if step.drills:
        drills = [
            {
                "name": drill.name or f"{drill_fallback} {idx}",
                "seconds": drill.seconds or 60,
                "reps": drill.reps or _SBU_DEFAULT_REPS,
            }
            for idx, drill in enumerate(step.drills, start=1)
        ]
    else:
        drills = SBU_DEFAULT_DRILLS

    groups: list[dict[str, Any]] = []
    for offset, drill in enumerate(drills):
        name = str(drill.get("name") or f"{drill_fallback} {offset + 1}")
        seconds = float(drill.get("seconds") or 60)
        reps = int(drill.get("reps") or _SBU_DEFAULT_REPS)

        child_steps = [
            _executable_step(
                1,
                "interval",
                END_COND_TIME,
                seconds,
                TARGET_NO,
                description=name,
            ),
            _executable_step(
                2,
                "recovery",
                END_COND_TIME,
                _SBU_RECOVERY_SECS,
                TARGET_NO,
                description=recovery_label,
            ),
        ]
        groups.append(_repeat_group(order + offset, reps, child_steps))

    return groups


class StepMappingError(ValueError):
    """A workout step cannot be represented in a Garmin payload.

    Raised instead of skipping the step: uploading a workout with a silently
    missing step is worse than failing that workout with a clear reason.
    """


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

_MAPPERS = {
    "dist_hr":   _map_dist_hr,
    "time_hr":   _map_time_hr,
    "dist_pace": _map_dist_pace,
    "time_pace": _map_time_pace,
    "dist_cadence": _map_dist_cadence,
    "time_cadence": _map_time_cadence,
    "dist_open": _map_dist_open,
    "time_step": _map_time_step,
    "open_step": _map_open_step,
}


def _map_single_step(
    step: WorkoutStep,
    order: int,
    index: int,
    language: str = "ru",
) -> list[dict[str, Any]]:
    """Map one non-repeat YAML step; sbu_block expands to several groups."""
    stype = step.step_type
    try:
        if stype == "sbu_block":
            return _map_sbu_block(step, order, language)
        mapper = _MAPPERS.get(stype or "")
        if mapper is None:
            raise StepMappingError(f"steps[{index}]: unsupported step type {stype!r}")
        return [mapper(step, order)]
    except StepMappingError:
        raise
    except Exception as exc:
        raise StepMappingError(f"steps[{index}] ({stype}): {exc}") from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def map_steps(steps: list[WorkoutStep], language: str = "ru") -> list[dict[str, Any]]:
    """
    Convert YAML steps to Garmin workout-service step dicts.

    YAML (like FIT) stores a repeat *after* its body: ``back_to_offset`` is
    the YAML index of the body's first step and ``count`` the total number of
    executions. Garmin wants a tree, so steps are folded with a stack: a
    repeat pops every node that starts at or after ``back_to_offset`` and
    wraps them in one RepeatGroupDTO. An inner repeat has already collapsed
    into a single node by then, so nested groups keep each body exactly once
    (same semantics as the FIT file).

    Raises StepMappingError for unsupported steps and for repeat ranges that
    start inside another group (overlapping, not nested).
    """
    # Each node: (first YAML index, last YAML index, payload dicts it produces).
    nodes: list[tuple[int, int, list[dict[str, Any]]]] = []

    for idx, step in enumerate(steps):
        if step.step_type != "repeat":
            nodes.append((idx, idx, _map_single_step(step, 1, idx, language)))
            continue

        try:
            back_to, count = int(step.back_to_offset), int(step.count)
        except (TypeError, ValueError) as exc:
            raise StepMappingError(f"steps[{idx}]: invalid repeat {exc}") from exc
        if not 0 <= back_to < idx or count < 1:
            raise StepMappingError(
                f"steps[{idx}]: repeat back_to_offset={back_to} count={count} is out of range"
            )

        body: list[dict[str, Any]] = []
        while nodes and nodes[-1][0] >= back_to:
            body = nodes.pop()[2] + body
        if nodes and nodes[-1][1] >= back_to:
            raise StepMappingError(
                f"steps[{idx}]: repeat starting at step {back_to} overlaps an earlier repeat group"
            )
        for child_order, child in enumerate(body, start=1):
            child["stepOrder"] = child_order
        nodes.append((back_to, idx, [_repeat_group(1, count, body)]))

    result = [payload for _start, _end, group in nodes for payload in group]
    for order, payload in enumerate(result, start=1):
        payload["stepOrder"] = order
    return result


def map_workout(workout: Workout, language: str = "ru") -> dict[str, Any]:
    """
    Build a complete Garmin workout-service payload from a Workout domain object.

    Returns a dict ready to pass to client.upload_workout() or
    client.upload_running_workout().
    """
    workout_steps = map_steps(workout.steps, language)

    estimated_secs: float = 0.0
    if workout.estimated_duration_min:
        try:
            estimated_secs = float(workout.estimated_duration_min) * 60.0
        except (TypeError, ValueError):
            pass

    return {
        "workoutName": workout.filename or workout.name or "Workout",
        "estimatedDurationInSecs": int(estimated_secs),
        "description": workout.desc or "",
        "sportType": SPORT_TYPE_RUNNING,
        "author": {},
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": SPORT_TYPE_RUNNING,
                "workoutSteps": workout_steps,
            }
        ],
    }


_WEEKDAY_TOKENS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_FILENAME_DATE_RE = re.compile(r"_(\d{2})-(\d{2})(?:_([A-Za-z]{3}))?(?=_|$)")


def extract_date_from_filename(
    filename: str,
    year: int | None = None,
    today: datetime.date | None = None,
) -> str | None:
    """
    Extract a calendar date from a FitWeaver workout filename.

    Pattern: W{week}_{MM-DD}_{Day}_{...}  e.g. "W11_03-14_Sat_Long_14km"

    Parameters
    ----------
    filename:
        Workout filename (without .fit extension).
    year:
        Explicit year. If None, the year is inferred: among last, this and next
        year, candidates whose weekday matches the ``Day`` token are preferred,
        and the one closest to today wins. A workout from yesterday therefore
        stays in the past (so ``skip_past`` can skip it) instead of moving a
        year ahead.
    today:
        Reference date for the inference (defaults to date.today(); for tests).

    Returns
    -------
    str | None
        ISO date string "YYYY-MM-DD", or None if the pattern is missing or the
        month/day is not a real date (e.g. 02-30, or 02-29 in the given year).
    """
    match = _FILENAME_DATE_RE.search(filename or "")
    if not match:
        return None

    month, day = int(match.group(1)), int(match.group(2))
    weekday_token = (match.group(3) or "").title()
    weekday = _WEEKDAY_TOKENS.index(weekday_token) if weekday_token in _WEEKDAY_TOKENS else None

    if year is not None:
        try:
            return datetime.date(year, month, day).isoformat()
        except ValueError:
            logger.warning("Invalid date %02d-%02d in %r for year %d", month, day, filename, year)
            return None

    inferred = infer_date(month, day, weekday=weekday, today=today)
    if inferred is None:
        logger.warning("Invalid date %02d-%02d in %r", month, day, filename)
        return None
    return inferred.isoformat()


def infer_date(
    month: int,
    day: int,
    weekday: int | None = None,
    today: datetime.date | None = None,
) -> datetime.date | None:
    """Pick the year for a day/month written without one.

    Candidates are last, this and next year; when ``weekday`` (0=Mon) is known,
    years whose date falls on that weekday are preferred. The candidate closest
    to ``today`` wins (ties go to the future). Returns None for impossible
    dates such as 02-30.
    """
    reference = today or datetime.date.today()
    candidates = []
    for delta in (-1, 0, 1):
        try:
            candidates.append(datetime.date(reference.year + delta, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    if weekday is not None:
        candidates = [d for d in candidates if d.weekday() == weekday] or candidates
    return min(candidates, key=lambda d: (abs((d - reference).days), d < reference))
