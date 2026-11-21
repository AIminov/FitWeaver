"""Validated mutations of a local workout plan."""

import re
from dataclasses import dataclass
from datetime import date

from .plan_domain import WorkoutStep
from .plan_processing import normalize_workout_identifier
from .plan_store import PlanStore
from .workout_builder import validate_draft


@dataclass(frozen=True)
class Reschedule:
    old_name: str
    new_name: str
    old_date: str | None
    new_date: str
    copy: bool


def save_workout(store: PlanStore, filename: str, steps: list[WorkoutStep],
                 *, workout_id: int | None = None) -> None:
    errors, _ = validate_draft(filename, filename, steps)
    if errors:
        raise ValueError("\n".join(errors))
    if workout_id is None:
        store.add_workout(filename=filename, name=filename, steps=steps)
    else:
        store.replace_workout_steps(workout_id, steps, filename=filename)


def _workout_id(store: PlanStore, filename: str) -> int:
    workout_id = store.find_workout_id_by_filename(filename)
    if workout_id is None:
        raise ValueError(f"Тренировка «{filename}» не найдена. Обновите локальный план.")
    return workout_id


def reschedule(store: PlanStore, filename: str, target: str, *, copy: bool) -> Reschedule:
    workout_id = _workout_id(store, filename)
    day = date.fromisoformat(target)
    weekday = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[day.weekday()]
    token = f"_{day:%m-%d}_{weekday}_"
    candidate, count = re.subn(r"_\d{2}-\d{2}_[A-Za-z]+_", token, filename, count=1)
    if not count:
        candidate = f"W00{token}{filename}"
    name = normalize_workout_identifier(candidate, workout_index=0, inferred_year=day.year)
    if copy:
        base = name
        suffix = 1
        while store.find_workout_id_by_filename(name) is not None:
            suffix += 1
            name = f"{base}_copy{'' if suffix == 2 else suffix}"
    change = Reschedule(filename, name, store.get_workout_date(workout_id), day.isoformat(), copy)
    replay_reschedule(store, change, redo=True)
    return change


def replay_reschedule(store: PlanStore, change: Reschedule, *, redo: bool) -> None:
    workout_id = _workout_id(store, change.old_name if redo else change.new_name)
    if change.copy:
        if redo:
            store.duplicate_workout(workout_id, filename=change.new_name, date=change.new_date)
        else:
            store.delete_workout(workout_id)
    else:
        store.rename_workout_filename(
            workout_id, change.new_name if redo else change.old_name,
            date=change.new_date if redo else change.old_date, update_date=True)
