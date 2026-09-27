"""
Garmin Connect Calendar exporter.

Uploads FitWeaver workouts to Garmin Connect and optionally schedules
them to specific calendar dates — no USB cable required.

After publishing, workouts appear on the watch automatically on the
next Garmin Connect sync.

Usage (local CLI):
    from garmin_fit.garmin_auth_manager import GarminAuthManager, prompt_mfa_with_timeout
    from garmin_fit.garmin_calendar_export import GarminCalendarExporter

    manager = GarminAuthManager.from_env(
        prompt_mfa=prompt_mfa_with_timeout
    )
    client = manager.connect()

    exporter = GarminCalendarExporter(client)
    results = exporter.upload_plan(plan, schedule=True)

Usage (dry run):
    results = exporter.upload_plan(plan, schedule=True, dry_run=True)

Payload spec: docs/GARMIN_PAYLOAD_SPEC.md
"""

from __future__ import annotations

import datetime
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .garmin_step_mapper import StepMappingError, extract_date_from_filename, map_workout
from .plan_domain import Workout, WorkoutPlan

logger = logging.getLogger(__name__)

# Delays to respect Garmin rate limits
_UPLOAD_DELAY_SECS = 1.2   # between individual workouts within a week
_WEEK_PAUSE_SECS   = 3.0   # extra pause between calendar weeks


def _week_label(filename: str | None) -> str:
    """Extract week label ('W18') from filename, or 'W??' if not found."""
    if filename:
        m = re.match(r"(W\d+)_", filename)
        if m:
            return m.group(1)
    return "W??"


def _parse_date(date_str: str | None) -> datetime.date | None:
    """Parse 'YYYY-MM-DD' string to date, return None on failure."""
    if not date_str:
        return None
    try:
        return datetime.date.fromisoformat(date_str)
    except ValueError:
        return None


def _date_in_range(
    date_str: str | None,
    from_date: datetime.date | None,
    to_date: datetime.date | None,
    skip_past: bool,
) -> tuple[bool, str]:
    """
    Return (should_upload, reason_if_skipped).
    ``skip_past=True`` means dates strictly before today are skipped.
    """
    today = datetime.date.today()
    d = _parse_date(date_str)

    if d is None:
        if date_str is not None:
            # date_str was provided but failed to parse — log so it's not silent
            logger.warning(
                "Could not parse date %r — workout included without date filtering", date_str
            )
        # No (valid) date: always include, upload without scheduling
        return True, ""
    if skip_past and d < today:
        return False, f"past date {date_str} (before {today})"
    if from_date and d < from_date:
        return False, f"before --from-date {from_date}"
    if to_date and d > to_date:
        return False, f"after --to-date {to_date}"
    return True, ""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class WorkoutUploadResult:
    filename: str
    workout_id: str | None = None
    date: str | None = None
    scheduled: bool = False
    dry_run: bool = False
    error: str | None = None
    # Set when the same workout name is already scheduled on that date.
    skipped_duplicate: bool = False
    replaced_duplicate: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class PlanUploadResult:
    results: list[WorkoutUploadResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def uploaded(self) -> int:
        return sum(1 for r in self.results if r.ok and not r.dry_run and not r.skipped_duplicate)

    @property
    def skipped_duplicates(self) -> int:
        return sum(1 for r in self.results if r.skipped_duplicate)

    @property
    def replaced_duplicates(self) -> int:
        return sum(1 for r in self.results if r.ok and r.replaced_duplicate)

    @property
    def scheduled(self) -> int:
        return sum(1 for r in self.results if r.scheduled)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    def summary(self) -> str:
        if any(r.dry_run for r in self.results):
            return (
                f"[DRY RUN] Would upload {self.total} workout(s), "
                f"schedule {sum(1 for r in self.results if r.date)} with dates"
            )
        summary = (
            f"Uploaded {self.uploaded}/{self.total} workouts, "
            f"scheduled {self.scheduled}, failed {self.failed}"
        )
        if self.skipped_duplicates:
            summary += f", skipped {self.skipped_duplicates} already scheduled"
        if self.replaced_duplicates:
            summary += f", replaced {self.replaced_duplicates} already scheduled"
        return summary


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------

class GarminCalendarExporter:
    """
    Upload FitWeaver Workout / WorkoutPlan objects to Garmin Connect Calendar.

    Parameters
    ----------
    client:
        Authenticated garminconnect.Garmin client (from GarminAuthManager.connect()).
    upload_delay:
        Seconds to sleep between uploads. Default 1.2 s (rate-limit safe).
    """

    def __init__(self, client: Any, upload_delay: float = _UPLOAD_DELAY_SECS, language: str = "ru") -> None:
        self._client = client
        self._delay = upload_delay
        self._language = language

    # ------------------------------------------------------------------
    # Single workout
    # ------------------------------------------------------------------

    def upload_workout(self, workout: Workout) -> str:
        """
        Upload a single planned workout to Garmin Connect.

        Returns
        -------
        str
            The assigned workout_id from Garmin Connect.
        """
        payload = map_workout(workout, self._language)
        logger.debug("Uploading workout %r ...", workout.filename)
        response = self._client.upload_workout(payload)
        workout_id = self._extract_workout_id(response)
        logger.info("Uploaded %r -> workout_id=%s", workout.filename, workout_id)
        return workout_id

    def schedule_workout(self, workout_id: str, date: str) -> None:
        """
        Schedule an uploaded workout on a calendar date.

        Parameters
        ----------
        workout_id:
            ID returned by upload_workout().
        date:
            ISO date string "YYYY-MM-DD".
        """
        self._client.schedule_workout(workout_id, date)
        logger.info("Scheduled workout_id=%s on %s", workout_id, date)

    def upload_and_schedule(
        self,
        workout: Workout,
        date: str | None = None,
        dry_run: bool = False,
    ) -> WorkoutUploadResult:
        """
        Upload a workout and optionally schedule it.

        Parameters
        ----------
        workout:
            Workout domain object.
        date:
            ISO date "YYYY-MM-DD". Auto-detected from filename if None.
        dry_run:
            If True, build payload but make no API calls.

        Returns
        -------
        WorkoutUploadResult
        """
        resolved_date = date or extract_date_from_filename(workout.filename or "")
        result = WorkoutUploadResult(
            filename=workout.filename or workout.name or "unknown",
            date=resolved_date,
            dry_run=dry_run,
        )

        if dry_run:
            try:
                payload = map_workout(workout, self._language)
            except StepMappingError as exc:
                result.error = str(exc)
                logger.error("Cannot build payload for %r: %s", result.filename, exc)
                return result
            step_count = len(
                payload.get("workoutSegments", [{}])[0].get("workoutSteps", [])
            )
            logger.info(
                "[DRY RUN] %r -> %d top-level steps, date=%s",
                result.filename, step_count, resolved_date,
            )
            return result

        try:
            workout_id = self.upload_workout(workout)
            result.workout_id = workout_id

            if resolved_date:
                self.schedule_workout(workout_id, resolved_date)
                result.scheduled = True

        except Exception as exc:
            result.error = str(exc)
            logger.error("Failed to upload %r: %s", result.filename, exc)

        return result

    # ------------------------------------------------------------------
    # Full plan
    # ------------------------------------------------------------------

    def upload_plan(
        self,
        plan: WorkoutPlan,
        schedule: bool = True,
        dry_run: bool = False,
        year: int | None = None,
        week_pause: float = _WEEK_PAUSE_SECS,
        skip_past: bool = False,
        from_date: str | None = None,
        to_date: str | None = None,
        skip_duplicates: bool = True,
        replace_duplicates: bool = False,
    ) -> PlanUploadResult:
        """
        Upload all workouts in a plan to Garmin Connect Calendar.

        Workouts are grouped by calendar week (W01, W02, ...).
        Within a week the delay is ``self._delay`` (1.2 s).
        Between weeks an extra ``week_pause`` (default 3 s) is added.

        Parameters
        ----------
        plan:
            WorkoutPlan domain object (from plan_domain.plan_from_data).
        schedule:
            Whether to schedule each workout to its calendar date.
        dry_run:
            Build payloads but make no API calls.
        year:
            Override year for date extraction. If None, auto-detected.
        week_pause:
            Extra seconds to sleep between calendar weeks (default 3.0).
        skip_past:
            Skip workouts whose date is strictly before today.
        from_date:
            Only upload workouts on or after this date ('YYYY-MM-DD').
        to_date:
            Only upload workouts on or before this date ('YYYY-MM-DD').
        skip_duplicates:
            Before a live scheduled upload, read the Garmin calendar for the
            affected months and skip workouts whose name is already scheduled
            on the same date, so re-running an upload does not create copies.
        replace_duplicates:
            Replace one exact same-name calendar occurrence on the same date.
            If the calendar cannot be read or the match is ambiguous, fail that
            workout without uploading anything.
        """
        if skip_duplicates and replace_duplicates:
            raise ValueError("Choose either skip_duplicates or replace_duplicates")
        if replace_duplicates and not schedule:
            raise ValueError("replace_duplicates requires calendar scheduling")
        plan_result = PlanUploadResult()

        from_d = _parse_date(from_date)
        to_d = _parse_date(to_date)

        # ------------------------------------------------------------------ pre-filter
        included: list[Workout] = []
        skipped = 0
        for w in plan.workouts:
            raw_date = extract_date_from_filename(w.filename or "", year=year)
            ok, reason = _date_in_range(raw_date, from_d, to_d, skip_past)
            if ok:
                included.append(w)
            else:
                logger.debug("Skipping %r: %s", w.filename, reason)
                skipped += 1

        if skipped:
            logger.info("Skipped %d workout(s) by date filter (%d remaining).",
                        skipped, len(included))

        total = len(included)
        if total == 0:
            logger.info("No workouts to upload after date filtering.")
            return plan_result

        # ------------------------------------------------------------------ group by week
        weeks: dict[str, list[Workout]] = {}
        for w in included:
            weeks.setdefault(_week_label(w.filename), []).append(w)

        n_weeks = len(weeks)
        logger.info(
            "Starting %s upload: %d workouts across %d week(s) ...",
            "dry-run" if dry_run else "live", total, n_weeks,
        )

        existing: dict[tuple[str, str], list[dict[str, str]]] = {}
        unreadable_months: set[tuple[int, int]] = set()
        if (skip_duplicates or replace_duplicates) and schedule and not dry_run:
            dates = [extract_date_from_filename(w.filename or "", year=year) for w in included]
            existing, unreadable_months = self._scheduled_events_by_date(d for d in dates if d)

        uploaded_total = 0
        processed: set[tuple[str, str]] = set()
        for week_idx, (label, week_workouts) in enumerate(weeks.items()):
            logger.info(
                "--- %s (%d workout(s)) ---", label, len(week_workouts),
            )

            for j, workout in enumerate(week_workouts):
                uploaded_total += 1
                logger.info(
                    "[%d/%d] Processing %r ...", uploaded_total, total, workout.filename,
                )

                date: str | None = None
                if schedule:
                    date = extract_date_from_filename(workout.filename or "", year=year)
                    if date is None:
                        if replace_duplicates:
                            plan_result.results.append(WorkoutUploadResult(
                                filename=workout.filename or workout.name or "",
                                error="Для замены назначения нужна дата в имени тренировки",
                            ))
                            continue
                        logger.warning(
                            "Could not extract date from %r — uploading without scheduling",
                            workout.filename,
                        )

                name = workout.filename or workout.name or ""
                key = (date, name) if date else None
                if key and replace_duplicates and (int(date[:4]), int(date[5:7])) in unreadable_months:
                    error = f"Не удалось прочитать календарь Garmin за {date[:7]}; замена отменена"
                    plan_result.results.append(WorkoutUploadResult(filename=name, date=date, error=error))
                    continue
                if key and key in processed and (skip_duplicates or replace_duplicates):
                    plan_result.results.append(WorkoutUploadResult(
                        filename=name, date=date, skipped_duplicate=True))
                    continue
                if key and skip_duplicates and key in existing:
                    logger.info("Skipping %r: already scheduled on %s", name, date)
                    plan_result.results.append(WorkoutUploadResult(
                        filename=name, date=date, skipped_duplicate=True))
                    continue

                if key and replace_duplicates and key in existing:
                    matches = existing[key]
                    if len(matches) != 1 or not matches[0].get("schedule_id"):
                        error = "Нельзя однозначно определить старое назначение в календаре Garmin"
                        plan_result.results.append(WorkoutUploadResult(
                            filename=name, date=date, error=error))
                        continue
                    from .garmin_calendar_edit import replace_scheduled_workout

                    try:
                        new_id = replace_scheduled_workout(
                            self._client, workout,
                            old_schedule_id=matches[0]["schedule_id"], date=date,
                        )
                        result = WorkoutUploadResult(
                            filename=name, workout_id=new_id, date=date,
                            scheduled=True, replaced_duplicate=True,
                        )
                        logger.info("Replaced %r on %s with workout_id=%s", name, date, new_id)
                    except Exception as exc:
                        result = WorkoutUploadResult(filename=name, date=date, error=str(exc))
                        logger.error("Could not replace %r on %s: %s", name, date, exc)
                    plan_result.results.append(result)
                    if result.ok:
                        processed.add(key)
                    if j < len(week_workouts) - 1:
                        time.sleep(self._delay)
                    continue

                result = self.upload_and_schedule(workout, date=date, dry_run=dry_run)
                plan_result.results.append(result)
                if key and result.ok:
                    processed.add(key)

                # delay between workouts within a week (skip after last in week)
                if not dry_run and j < len(week_workouts) - 1:
                    time.sleep(self._delay)

            # longer pause between weeks (skip after last week)
            if not dry_run and week_idx < n_weeks - 1:
                logger.info(
                    "Week %s done — pausing %.1f s before next week ...",
                    label, week_pause,
                )
                time.sleep(week_pause)

        logger.info(plan_result.summary())
        return plan_result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _scheduled_names_by_date(self, dates) -> set[tuple[str, str]]:
        """(date, workout name) pairs already on the Garmin calendar for these dates.

        Best effort: if the calendar cannot be read, duplicates are not
        detected and the upload proceeds (with a warning).
        """
        events, _unreadable = self._scheduled_events_by_date(dates)
        return set(events)

    def _scheduled_events_by_date(
        self, dates
    ) -> tuple[dict[tuple[str, str], list[dict[str, str]]], set[tuple[int, int]]]:
        """Calendar occurrences keyed by (date, name), plus unreadable months."""
        from .garmin_calendar_view import normalize_scheduled_workouts

        months = sorted({(int(d[:4]), int(d[5:7])) for d in dates})
        existing: dict[tuple[str, str], list[dict[str, str]]] = {}
        unreadable: set[tuple[int, int]] = set()
        get_month = getattr(self._client, "get_scheduled_workouts", None)
        if not callable(get_month):
            logger.warning("Garmin client cannot read the calendar; duplicate lookup unavailable")
            return {}, set(months)
        for year_, month in months:
            try:
                events = normalize_scheduled_workouts(get_month(year_, month))
            except Exception as exc:
                logger.warning("Could not read Garmin calendar %04d-%02d (%s); duplicate lookup unavailable",
                               year_, month, exc)
                unreadable.add((year_, month))
                continue
            for event in events:
                existing.setdefault((event["date"], event["name"]), []).append(event)
        return existing, unreadable

    @staticmethod
    def _extract_workout_id(response: Any) -> str:
        """Extract workout_id string from garminconnect upload response."""
        if isinstance(response, dict):
            # garminconnect returns {"workoutId": ..., ...} or {"detailedStepId": ...}
            for key in ("workoutId", "workout_id", "id"):
                if key in response:
                    return str(response[key])
        # Fallback: stringify whatever came back
        return str(response)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def publish_plan_to_garmin(
    plan: WorkoutPlan,
    *,
    email: str | None = None,
    password: str | None = None,
    token_dir: str | None = None,
    schedule: bool = True,
    dry_run: bool = False,
    year: int | None = None,
    prompt_mfa: Any = None,
) -> PlanUploadResult:
    """
    One-shot: authenticate + upload + schedule a full plan.

    Credentials fall back to GARMIN_EMAIL / GARMIN_PASSWORD env vars.

    Example
    -------
    from garmin_fit.garmin_calendar_export import publish_plan_to_garmin
    from garmin_fit.plan_domain import plan_from_data
    import yaml, pathlib

    data = yaml.safe_load(pathlib.Path("Plan/plan.yaml").read_text())
    plan = plan_from_data(data)
    result = publish_plan_to_garmin(plan, dry_run=True)
    print(result.summary())
    """
    from pathlib import Path

    from .garmin_auth_manager import GarminAuthManager, prompt_mfa_with_timeout

    mfa_cb = prompt_mfa or prompt_mfa_with_timeout
    token_path = Path(token_dir) if token_dir else None
    manager = GarminAuthManager(
        email=email,
        password=password,
        token_dir=token_path,
        prompt_mfa=mfa_cb,
    )
    client = manager.connect()
    if client == "needs_mfa":
        raise RuntimeError(
            "MFA required but no prompt_mfa provided. "
            "Pass prompt_mfa=lambda: input('MFA: ') or handle interactively."
        )

    exporter = GarminCalendarExporter(client)
    return exporter.upload_plan(plan, schedule=schedule, dry_run=dry_run, year=year)
