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
repeat     → RepeatGroupDTO wrapping steps from back_to_offset..current
sbu_block  → RepeatGroupDTO list (one repeat group per drill, with step notes)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .plan_domain import Workout, WorkoutStep
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


def _map_sbu_block(step: WorkoutStep, order: int) -> list[dict[str, Any]]:
    """
    SBU block → one RepeatGroupDTO per drill.

    Each drill becomes: Repeat reps × [active step with description + recovery].
    Garmin Connect stores the step note as ExecutableStepDTO.description.

    Drill name/seconds/reps come from step.drills; if absent, use the same
    default drill set as the FIT builder.
    """
    if step.drills:
        drills = [
            {
                "name": drill.name or f"Drill {idx}",
                "seconds": drill.seconds or 60,
                "reps": drill.reps or _SBU_DEFAULT_REPS,
            }
            for idx, drill in enumerate(step.drills, start=1)
        ]
    else:
        drills = SBU_DEFAULT_DRILLS

    groups: list[dict[str, Any]] = []
    for offset, drill in enumerate(drills):
        name = str(drill.get("name") or f"Drill {offset + 1}")
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
                description="Recovery",
            ),
        ]
        groups.append(_repeat_group(order + offset, reps, child_steps))

    return groups


# ---------------------------------------------------------------------------
# Repeat step
# ---------------------------------------------------------------------------

def _map_repeat(
    step: WorkoutStep,
    order: int,
    all_steps: list[WorkoutStep],
    current_idx: int,
) -> dict[str, Any]:
    """
    repeat → RepeatGroupDTO.

    back_to_offset is a YAML-level 0-based index.
    We wrap the steps from back_to_offset..current_idx-1.
    """
    back_to = int(step.back_to_offset)
    count = int(step.count)

    # Collect the steps that form the body of the repeat group.
    # These are all steps between back_to_offset and the repeat step itself.
    body_steps_domain = all_steps[back_to:current_idx]

    child_steps: list[dict[str, Any]] = []
    for child_order, child in enumerate(body_steps_domain, start=1):
        mapped = _map_single_step(child, child_order, body_steps_domain, child_order - 1)
        if mapped is not None:
            # Flatten nested repeat groups into the child list
            if isinstance(mapped, list):
                child_steps.extend(mapped)
            else:
                child_steps.append(mapped)

    for child_order, child_step in enumerate(child_steps, start=1):
        child_step["stepOrder"] = child_order

    return _repeat_group(
        step_order=order,
        iterations=count,
        child_steps=child_steps,
    )


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

_MAPPERS = {
    "dist_hr":   _map_dist_hr,
    "time_hr":   _map_time_hr,
    "dist_pace": _map_dist_pace,
    "time_pace": _map_time_pace,
    "dist_open": _map_dist_open,
    "time_step": _map_time_step,
    "open_step": _map_open_step,
    "sbu_block": _map_sbu_block,
}


def _map_single_step(
    step: WorkoutStep,
    order: int,
    all_steps: list[WorkoutStep],
    current_idx: int,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    stype = step.step_type
    if stype == "repeat":
        return _map_repeat(step, order, all_steps, current_idx)
    mapper = _MAPPERS.get(stype or "")
    if mapper is None:
        logger.warning("Unknown step type %r — skipped", stype)
        return None
    try:
        return mapper(step, order)
    except Exception as exc:
        logger.warning("Failed to map step %r (order %d): %s", stype, order, exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def map_steps(steps: list[WorkoutStep]) -> list[dict[str, Any]]:
    """
    Convert a list of WorkoutStep domain objects to a flat list of
    Garmin workout-service step dicts.

    ``repeat`` steps absorb their body into a RepeatGroupDTO.
    Steps consumed by a repeat block are NOT emitted separately.
    """
    # Pre-compute which YAML indices are absorbed into repeat groups.
    # Must be done before the main loop so body steps are skipped even
    # though they appear *before* the repeat step in the list.
    consumed: set[int] = set()
    for idx, step in enumerate(steps):
        if step.step_type == "repeat":
            back_to = int(step.back_to_offset)
            for i in range(back_to, idx):
                consumed.add(i)

    result: list[dict[str, Any]] = []
    for idx, step in enumerate(steps):
        if idx in consumed:
            continue
        if step.step_type == "repeat":
            mapped = _map_repeat(step, len(result) + 1, steps, idx)
            result.append(mapped)
        else:
            mapped_s = _map_single_step(step, len(result) + 1, steps, idx)
            if isinstance(mapped_s, list):
                result.extend(mapped_s)
            elif mapped_s is not None:
                result.append(mapped_s)

    return result


def map_workout(workout: Workout) -> dict[str, Any]:
    """
    Build a complete Garmin workout-service payload from a Workout domain object.

    Returns a dict ready to pass to client.upload_workout() or
    client.upload_running_workout().
    """
    workout_steps = map_steps(workout.steps)

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


def extract_date_from_filename(filename: str, year: int | None = None) -> str | None:
    """
    Extract a calendar date from a FitWeaver workout filename.

    Pattern: W{week}_{MM-DD}_{...}  e.g. "W11_03-14_Sat_Long_14km"

    Parameters
    ----------
    filename:
        Workout filename (without .fit extension).
    year:
        Explicit year. If None, uses current year (or next if date already passed).

    Returns
    -------
    str | None
        ISO date string "YYYY-MM-DD", or None if pattern not found.
    """
    import datetime

    match = re.search(r"_(\d{2})-(\d{2})_", filename)
    if not match:
        return None

    month = int(match.group(1))
    day = int(match.group(2))

    if year is not None:
        return f"{year:04d}-{month:02d}-{day:02d}"

    today = datetime.date.today()
    candidate = datetime.date(today.year, month, day)
    if candidate < today:
        candidate = datetime.date(today.year + 1, month, day)
    return candidate.isoformat()
