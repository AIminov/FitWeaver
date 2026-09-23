"""Normalize Garmin's monthly calendar response for the desktop view."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

_DATE_KEYS = ("calendarDate", "scheduledDate", "workoutDate", "date")
_SCHEDULE_ID_KEYS = (
    "workoutScheduleId",
    "scheduledWorkoutId",
    "scheduleId",
)
_COLLECTION_KEYS = (
    "scheduledWorkouts",
    "workoutSchedules",
    "calendarItems",
    "calendarEvents",
    "events",
    "items",
    "days",
    "dailySchedules",
    "calendar",
)


def _iso_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _name(item: Mapping[str, Any]) -> str:
    workout = item.get("workout")
    if isinstance(workout, Mapping):
        for key in ("workoutName", "name", "title"):
            if workout.get(key):
                return str(workout[key])
    for key in ("workoutName", "name", "title", "eventName"):
        if item.get(key):
            return str(item[key])
    return "Тренировка Garmin"


def normalize_scheduled_workouts(payload: Any) -> list[dict[str, str]]:
    """Return dated scheduled workouts from Garmin's monthly response.

    The Garmin response is not formally versioned and has appeared as a list,
    a keyed month object, or a wrapper around those structures. Accept the
    documented schedule fields while ignoring unrelated calendar items.
    """
    events: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def visit(value: Any, inherited_date: str | None = None) -> None:
        if isinstance(value, list):
            for entry in value:
                visit(entry, inherited_date)
            return
        if not isinstance(value, Mapping):
            return

        current_date = next(
            (_iso_date(value.get(key)) for key in _DATE_KEYS if _iso_date(value.get(key))),
            inherited_date,
        )
        schedule_id = next(
            (value.get(key) for key in _SCHEDULE_ID_KEYS if value.get(key) is not None),
            None,
        )
        nested_workout = value.get("workout")
        workout_id = value.get("workoutId")
        is_workout = bool(schedule_id or workout_id) or isinstance(nested_workout, Mapping)
        # Some calendar responses identify the schedule row only as `id`.
        # Use it only after the row is known to represent a workout, so an
        # unrelated calendar event ID cannot enable Garmin workout editing.
        if not schedule_id and is_workout:
            schedule_id = value.get("id")

        if current_date and is_workout:
            name = _name(value)
            stable_id = str(schedule_id or workout_id or f"{current_date}:{name}")
            identity = (current_date, stable_id)
            if identity not in seen:
                seen.add(identity)
                event = {
                    "date": current_date,
                    "name": name,
                    "schedule_id": str(schedule_id or ""),
                }
                workout_id = nested_workout.get("workoutId") if isinstance(
                    nested_workout, Mapping) else value.get("workoutId")
                if workout_id is not None:
                    event["workout_id"] = str(workout_id)
                events.append(event)
                return

        for key in _COLLECTION_KEYS:
            if key in value:
                visit(value[key], current_date)

        # Some Garmin responses key each day's entries by ISO date.
        for key, child in value.items():
            keyed_date = _iso_date(key)
            if keyed_date:
                visit(child, keyed_date)

    visit(payload)
    return sorted(events, key=lambda event: (event["date"], event["name"].casefold()))
