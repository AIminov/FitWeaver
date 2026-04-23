"""
Shared plan domain objects and schema constants.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)

KNOWN_PACE_CONSTANTS = frozenset(
    {
        "EASY_F",
        "EASY_S",
        "AERO_F",
        "AERO_S",
        "LONG_F",
        "LONG_S",
        "TEMPO_F",
        "TEMPO_S",
    }
)

ALLOWED_INTENSITY = frozenset({"active", "warmup", "cooldown", "recovery"})

INTENSITY_DEFAULTS = {
    "dist_open": "active",
    "time_step": "recovery",
    "open_step": "active",
}

INTENSITY_ALIASES = {
    "active": "active",
    "work": "active",
    "main": "active",
    "tempo": "active",
    "hard": "active",
    "warmup": "warmup",
    "warm-up": "warmup",
    "warm_up": "warmup",
    "wu": "warmup",
    "cooldown": "cooldown",
    "cool-down": "cooldown",
    "cool_down": "cooldown",
    "cd": "cooldown",
    "recovery": "recovery",
    "easy": "recovery",
    "rest": "recovery",
    "easy_run": "recovery",
    "razminka": "warmup",
    "zaminka": "cooldown",
}

STEP_TYPE_ALIASES = {
    "distance_hr": "dist_hr",
    "distance_pace": "dist_pace",
    "distance_open": "dist_open",
    "time": "time_step",
    "time_open": "time_step",
    "repeat_step": "repeat",
    "sbu": "sbu_block",
}

STEP_REQUIRED_FIELDS = {
    "dist_hr": {"km", "hr_low", "hr_high"},
    "time_hr": {"seconds", "hr_low", "hr_high"},
    "dist_pace": {"km", "pace_fast", "pace_slow"},
    "time_pace": {"seconds", "pace_fast", "pace_slow"},
    "dist_open": {"km"},
    "time_step": {"seconds"},
    "open_step": set(),
    "repeat": {"back_to_offset", "count"},
    "sbu_block": set(),
}


@dataclass(slots=True)
class Drill:
    name: str | None = None
    seconds: int | None = None
    reps: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkoutStep:
    step_type: str | None = None
    intensity: str | None = None
    km: Any = None
    seconds: Any = None
    pace_fast: Any = None
    pace_slow: Any = None
    hr_low: Any = None
    hr_high: Any = None
    back_to_offset: Any = None
    count: Any = None
    drills: list[Drill] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Workout:
    filename: str | None = None
    name: str | None = None
    desc: str | None = None
    type_code: str | None = None
    distance_km: Any = None
    estimated_duration_min: Any = None
    steps: list[WorkoutStep] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkoutPlan:
    workouts: list[Workout] = field(default_factory=list)


def _extra_fields(data: Mapping[str, Any], known_fields: set[str]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in known_fields}


def drill_from_data(data: Mapping[str, Any]) -> Drill:
    return Drill(
        name=data.get("name"),
        seconds=data.get("seconds"),
        reps=data.get("reps"),
        extra=_extra_fields(data, {"name", "seconds", "reps"}),
    )


def step_from_data(data: Mapping[str, Any]) -> WorkoutStep:
    drills_value = data.get("drills")
    drills: list[Drill] | None = None
    if isinstance(drills_value, list):
        skipped = [item for item in drills_value if not isinstance(item, Mapping)]
        if skipped:
            logger.warning("step_from_data: dropped %d non-mapping drill item(s)", len(skipped))
        drills = [drill_from_data(item) for item in drills_value if isinstance(item, Mapping)]

    return WorkoutStep(
        step_type=data.get("type"),
        intensity=data.get("intensity"),
        km=data.get("km"),
        seconds=data.get("seconds"),
        pace_fast=data.get("pace_fast"),
        pace_slow=data.get("pace_slow"),
        hr_low=data.get("hr_low"),
        hr_high=data.get("hr_high"),
        back_to_offset=data.get("back_to_offset"),
        count=data.get("count"),
        drills=drills,
        extra=_extra_fields(
            data,
            {
                "type",
                "intensity",
                "km",
                "seconds",
                "pace_fast",
                "pace_slow",
                "hr_low",
                "hr_high",
                "back_to_offset",
                "count",
                "drills",
            },
        ),
    )


def workout_from_data(data: Mapping[str, Any]) -> Workout:
    steps_value = data.get("steps")
    steps: list[WorkoutStep] = []
    if isinstance(steps_value, list):
        skipped = [item for item in steps_value if not isinstance(item, Mapping)]
        if skipped:
            logger.warning(
                "workout_from_data '%s': dropped %d non-mapping step(s)",
                data.get("filename", "?"), len(skipped),
            )
        steps = [step_from_data(item) for item in steps_value if isinstance(item, Mapping)]

    return Workout(
        filename=data.get("filename"),
        name=data.get("name"),
        desc=data.get("desc"),
        type_code=data.get("type_code"),
        distance_km=data.get("distance_km"),
        estimated_duration_min=data.get("estimated_duration_min"),
        steps=steps,
        extra=_extra_fields(
            data,
            {
                "filename",
                "name",
                "desc",
                "type_code",
                "distance_km",
                "estimated_duration_min",
                "steps",
            },
        ),
    )


def plan_from_data(data: Mapping[str, Any]) -> WorkoutPlan:
    workouts_value = data.get("workouts")
    if not isinstance(workouts_value, list):
        return WorkoutPlan()

    skipped = [item for item in workouts_value if not isinstance(item, Mapping)]
    if skipped:
        logger.warning("plan_from_data: dropped %d non-mapping workout(s)", len(skipped))
    workouts = [workout_from_data(item) for item in workouts_value if isinstance(item, Mapping)]
    return WorkoutPlan(workouts=workouts)


def drill_to_data(drill: Drill) -> dict[str, Any]:
    data: dict[str, Any] = dict(drill.extra)
    if drill.name is not None:
        data["name"] = drill.name
    if drill.seconds is not None:
        data["seconds"] = drill.seconds
    if drill.reps is not None:
        data["reps"] = drill.reps
    return data


def step_to_data(step: WorkoutStep) -> dict[str, Any]:
    data: dict[str, Any] = dict(step.extra)
    if step.step_type is not None:
        data["type"] = step.step_type
    if step.intensity is not None:
        data["intensity"] = step.intensity
    if step.km is not None:
        data["km"] = step.km
    if step.seconds is not None:
        data["seconds"] = step.seconds
    if step.pace_fast is not None:
        data["pace_fast"] = step.pace_fast
    if step.pace_slow is not None:
        data["pace_slow"] = step.pace_slow
    if step.hr_low is not None:
        data["hr_low"] = step.hr_low
    if step.hr_high is not None:
        data["hr_high"] = step.hr_high
    if step.back_to_offset is not None:
        data["back_to_offset"] = step.back_to_offset
    if step.count is not None:
        data["count"] = step.count
    if step.drills is not None:
        data["drills"] = [drill_to_data(drill) for drill in step.drills]
    return data


def workout_to_data(workout: Workout) -> dict[str, Any]:
    data: dict[str, Any] = dict(workout.extra)
    if workout.filename is not None:
        data["filename"] = workout.filename
    if workout.name is not None:
        data["name"] = workout.name
    if workout.desc is not None:
        data["desc"] = workout.desc
    if workout.type_code is not None:
        data["type_code"] = workout.type_code
    if workout.distance_km is not None:
        data["distance_km"] = workout.distance_km
    if workout.estimated_duration_min is not None:
        data["estimated_duration_min"] = workout.estimated_duration_min
    data["steps"] = [step_to_data(step) for step in workout.steps]
    return data


def plan_to_data(plan: WorkoutPlan) -> dict[str, Any]:
    return {"workouts": [workout_to_data(workout) for workout in plan.workouts]}
