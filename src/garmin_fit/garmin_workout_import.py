"""Convert a Garmin Connect workout DTO into the editable FitWeaver model."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .plan_domain import Workout, WorkoutStep


def _pace(seconds_per_km: float) -> str:
    seconds = max(1, round(seconds_per_km))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _step_type(item: Mapping[str, Any]) -> str:
    value = item.get("type") or "ExecutableStepDTO"
    return str(value).removesuffix("DTO")


def _key(item: Mapping[str, Any], field: str) -> str:
    value = item.get(field)
    if isinstance(value, Mapping):
        key_name = {
            "endCondition": "conditionTypeKey",
            "targetType": "workoutTargetTypeKey",
            "stepType": "stepTypeKey",
        }.get(field, field + "Key")
        return str(value.get(key_name) or "").casefold()
    return ""


def _intensity(item: Mapping[str, Any]) -> str:
    kind = _key(item, "stepType")
    return {"warmup": "warmup", "cooldown": "cooldown", "recovery": "recovery"}.get(
        kind, "active"
    )


def _convert_step(item: Mapping[str, Any]) -> WorkoutStep:
    condition = _key(item, "endCondition")
    value = float(item.get("endConditionValue") or 0)
    if condition in {"distance", "distance_overall"}:
        duration_kind = "dist"
        km = value / 1000.0
    elif condition in {"time", "time_duration"}:
        duration_kind = "time"
    else:
        raise ValueError(f"Неподдерживаемое условие шага Garmin: {condition or 'не указано'}")

    target = _key(item, "targetType")
    low = float(item.get("targetValueOne") or 0)
    high = float(item.get("targetValueTwo") or 0)
    base: dict[str, Any] = {"intensity": _intensity(item)}
    if duration_kind == "dist":
        base["km"] = round(km, 3)
    else:
        base["seconds"] = round(value)

    if target == "heart.rate.zone":
        base.update(step_type=f"{duration_kind}_hr", hr_low=round(low), hr_high=round(high))
    elif target in {"speed", "pace.zone"}:
        if low <= 0 or high <= 0:
            raise ValueError(f"У цели Garmin «{target}» отсутствует диапазон темпа")
        # Garmin's pace.zone commonly stores the faster (higher m/s) bound in
        # targetValueOne and the slower bound in targetValueTwo. Normalize both
        # pace.zone and speed responses so edits retain the same pace interval.
        slower_speed, faster_speed = sorted((low, high))
        pace_fast = _pace(1000.0 / faster_speed)
        pace_slow = _pace(1000.0 / slower_speed)
        if duration_kind == "dist":
            base.update(step_type="dist_pace", pace_fast=pace_fast, pace_slow=pace_slow)
        else:
            base.update(step_type="time_pace", pace_fast=pace_fast, pace_slow=pace_slow)
    elif target == "cadence":
        base.update(step_type=f"{duration_kind}_cadence", cad_low=round(low), cad_high=round(high))
    elif target in {"", "no.target"}:
        base["step_type"] = "dist_open" if duration_kind == "dist" else "time_step"
    else:
        raise ValueError(f"Тип цели Garmin «{target}» пока нельзя редактировать")
    return WorkoutStep(**base)


def _append_items(items: list[Any], steps: list[WorkoutStep]) -> None:
    """Flatten Garmin steps; a RepeatGroup becomes its body plus a repeat row.

    Nested groups (e.g. 3 sets of 4 x 400 m) flatten recursively: each repeat
    row points back to the YAML index of its own body's first step, which is
    the same encoding the FIT builder and the Garmin mapper use.
    """
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("В тренировке Garmin есть неизвестный формат шага")
        kind = _step_type(item)
        if kind == "RepeatGroup":
            children = item.get("workoutSteps")
            if not isinstance(children, list) or not children:
                raise ValueError("Повтор Garmin пустой или повреждён")
            count = int(item.get("numberOfIterations") or item.get("endConditionValue") or 0)
            if count < 1:
                raise ValueError("У повтора Garmin неверно указано число повторений")
            anchor = len(steps)
            _append_items(children, steps)
            if count > 1:
                steps.append(WorkoutStep(step_type="repeat", back_to_offset=anchor, count=count))
        elif kind == "ExecutableStep":
            steps.append(_convert_step(item))
        else:
            raise ValueError(f"Тип блока Garmin «{kind}» пока нельзя редактировать")


def workout_from_garmin(payload: Mapping[str, Any], *, date: str) -> Workout:
    """Import supported Garmin steps; fail closed rather than silently dropping data."""
    segments = payload.get("workoutSegments")
    if not isinstance(segments, list):
        raise ValueError("Garmin не вернул структуру шагов тренировки")

    steps: list[WorkoutStep] = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            continue
        segment_steps = segment.get("workoutSteps")
        if not isinstance(segment_steps, list):
            continue
        _append_items(segment_steps, steps)

    if not steps:
        raise ValueError("В Garmin-тренировке нет поддерживаемых шагов")
    name = str(payload.get("workoutName") or payload.get("name") or "Тренировка Garmin")
    filename_name = re.sub(r"[^\w.-]+", "_", name, flags=re.UNICODE).strip("_.") or "Workout"
    return Workout(
        filename=f"Garmin_{date}_{filename_name}",
        name=name,
        desc=str(payload.get("description") or ""),
        type_code="mixed",
        steps=steps,
    )
