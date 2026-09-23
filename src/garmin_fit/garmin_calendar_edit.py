"""Safe replacement of one Garmin calendar occurrence."""

from __future__ import annotations

from datetime import date as parse_date
from typing import Any

from .garmin_step_mapper import map_workout
from .plan_domain import Workout


def replace_scheduled_workout(
    client: Any,
    workout: Workout,
    *,
    old_schedule_id: str,
    date: str,
) -> str:
    """Upload and schedule the edited copy, then remove the old calendar occurrence.

    The old workout template remains in the Garmin library. If replacement fails,
    the newly created calendar occurrence and template are rolled back when possible.
    """
    payload = map_workout(workout)
    uploaded_id: str | None = None
    scheduled_id: str | None = None
    schedule_created = False
    response = client.upload_workout(payload)
    uploaded_id = str(response.get("workoutId") or response.get("id") or "")
    if not uploaded_id:
        raise RuntimeError("Garmin загрузил тренировку без workoutId")
    try:
        scheduled = client.schedule_workout(uploaded_id, date)
        schedule_created = True
        scheduled_id = str(
            scheduled.get("workoutScheduleId") or scheduled.get("scheduledWorkoutId") or ""
        ) if isinstance(scheduled, dict) else ""
        if not scheduled_id:
            month = parse_date.fromisoformat(date)
            from .garmin_calendar_view import normalize_scheduled_workouts

            get_scheduled = getattr(client, "get_scheduled_workouts", None)
            if callable(get_scheduled):
                events = normalize_scheduled_workouts(
                    get_scheduled(month.year, month.month))
            else:
                events = []
            scheduled_id = next((
                event["schedule_id"] for event in events
                if event.get("workout_id") == uploaded_id and event.get("date") == date
                and event.get("schedule_id")
            ), "")
            if not scheduled_id:
                raise RuntimeError("Garmin не вернул ID нового назначения")
        client.unschedule_workout(old_schedule_id)
    except Exception as exc:
        rollback_errors: list[str] = []
        if schedule_created and not scheduled_id:
            rollback_errors.append(
                "не удалось определить ID нового назначения; проверьте календарь Garmin вручную"
            )
        if scheduled_id:
            try:
                client.unschedule_workout(scheduled_id)
            except Exception as rollback_exc:  # retain both API failures for recovery
                rollback_errors.append(f"снятие новой записи: {rollback_exc}")
        try:
            client.delete_workout(uploaded_id)
        except Exception as rollback_exc:
            rollback_errors.append(f"удаление новой тренировки: {rollback_exc}")
        suffix = f" Откат завершился не полностью: {'; '.join(rollback_errors)}" if rollback_errors else ""
        raise RuntimeError(f"Не удалось заменить тренировку Garmin: {exc}.{suffix}") from exc
    return uploaded_id
