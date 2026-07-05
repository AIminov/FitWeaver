"""SQLite staging layer for the desktop GUI.

YAML remains the canonical format understood by every other consumer (CLI,
Telegram bot, Garmin upload, build pipeline). This store is an internal GUI
convenience layer only — every mutation immediately re-exports to the YAML
file it was loaded from, so nothing outside the GUI needs to know it exists.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from .plan_domain import Drill, Workout, WorkoutPlan, WorkoutStep, plan_from_data, plan_to_data
from .plan_processing import repair_plan_data
from .plan_validator import validate_plan_data

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY,
    position INTEGER NOT NULL,
    filename TEXT, name TEXT, desc TEXT, type_code TEXT,
    distance_km TEXT, estimated_duration_min TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS steps (
    id INTEGER PRIMARY KEY,
    workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    step_type TEXT, intensity TEXT,
    km TEXT, seconds TEXT, pace_fast TEXT, pace_slow TEXT,
    hr_low TEXT, hr_high TEXT, back_to_offset TEXT, count TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS drills (
    id INTEGER PRIMARY KEY,
    step_id INTEGER NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT, seconds TEXT, reps TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}'
);
"""


def _dump_scalar(value: Any) -> str | None:
    return None if value is None else str(value)


def _load_int(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _load_float(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return value


class PlanStore:
    """SQLite-backed working copy of a WorkoutPlan.

    Scalar step/workout values (km, seconds, hr_low, pace_fast, ...) are stored
    as TEXT rather than a numeric column type. These dataclass fields are typed
    `Any` on purpose — pace_fast/pace_slow can hold a plain string ("5:45") or a
    symbolic constant (KNOWN_PACE_CONSTANTS, e.g. "EASY_F") — and downstream
    Pydantic validation in plan_schema.py already coerces int/float where
    needed. TEXT avoids SQLite's numeric type affinity silently mangling a
    pace-constant string.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._yaml_path: Path | None = None

    @classmethod
    def open(cls, db_path: Path) -> "PlanStore":
        conn = sqlite3.connect(str(db_path))
        conn.executescript(_SCHEMA)
        conn.commit()
        return cls(conn)

    def close(self) -> None:
        self._conn.close()

    # ── YAML <-> DB ──────────────────────────────────────────────────────────
    def load_from_yaml(self, yaml_path: Path) -> list[str]:
        """Full reload: parse YAML, repair, wipe DB, insert. Returns repair notes."""
        yaml_path = Path(yaml_path)
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        repaired_data, notes = repair_plan_data(data)
        plan = plan_from_data(repaired_data)
        self._replace_plan(plan)
        self._yaml_path = yaml_path
        return notes

    def export_to_yaml(self, yaml_path: Path) -> None:
        data = plan_to_data(self.get_plan())
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    def _write_through(self) -> None:
        if self._yaml_path is not None:
            self.export_to_yaml(self._yaml_path)

    def get_plan(self) -> WorkoutPlan:
        cur = self._conn.execute(
            "SELECT id, filename, name, desc, type_code, distance_km, "
            "estimated_duration_min, extra_json FROM workouts ORDER BY position"
        )
        workouts = []
        for wo_id, filename, name, desc, type_code, distance_km, duration, extra_json in cur.fetchall():
            workouts.append(Workout(
                filename=filename, name=name, desc=desc, type_code=type_code,
                distance_km=_load_float(distance_km),
                estimated_duration_min=_load_int(duration),
                steps=self._get_steps(wo_id), extra=json.loads(extra_json or "{}"),
            ))
        return WorkoutPlan(workouts=workouts)

    def _get_steps(self, workout_id: int) -> list[WorkoutStep]:
        cur = self._conn.execute(
            "SELECT id, step_type, intensity, km, seconds, pace_fast, pace_slow, "
            "hr_low, hr_high, back_to_offset, count, extra_json "
            "FROM steps WHERE workout_id = ? ORDER BY position",
            (workout_id,),
        )
        steps = []
        for (step_id, step_type, intensity, km, seconds, pace_fast, pace_slow,
             hr_low, hr_high, back_to_offset, count, extra_json) in cur.fetchall():
            drills = self._get_drills(step_id)
            steps.append(WorkoutStep(
                step_type=step_type, intensity=intensity,
                km=_load_float(km), seconds=_load_int(seconds),
                pace_fast=pace_fast, pace_slow=pace_slow,
                hr_low=_load_int(hr_low), hr_high=_load_int(hr_high),
                back_to_offset=_load_int(back_to_offset), count=_load_int(count),
                drills=drills or None, extra=json.loads(extra_json or "{}"),
            ))
        return steps

    def _get_drills(self, step_id: int) -> list[Drill]:
        cur = self._conn.execute(
            "SELECT name, seconds, reps, extra_json FROM drills "
            "WHERE step_id = ? ORDER BY position",
            (step_id,),
        )
        return [
            Drill(name=name, seconds=_load_int(seconds), reps=_load_int(reps),
                  extra=json.loads(extra_json or "{}"))
            for name, seconds, reps, extra_json in cur.fetchall()
        ]

    def _replace_plan(self, plan: WorkoutPlan) -> None:
        self._conn.execute("DELETE FROM workouts")
        for position, workout in enumerate(plan.workouts):
            self._insert_workout(position, workout)
        self._conn.commit()

    def _insert_workout(self, position: int, workout: Workout) -> int:
        cur = self._conn.execute(
            "INSERT INTO workouts (position, filename, name, desc, type_code, "
            "distance_km, estimated_duration_min, extra_json) VALUES (?,?,?,?,?,?,?,?)",
            (position, workout.filename, workout.name, workout.desc, workout.type_code,
             _dump_scalar(workout.distance_km), _dump_scalar(workout.estimated_duration_min),
             json.dumps(workout.extra)),
        )
        workout_id = cur.lastrowid
        for s_position, step in enumerate(workout.steps):
            self._insert_step(workout_id, s_position, step)
        return workout_id

    def _insert_step(self, workout_id: int, position: int, step: WorkoutStep) -> int:
        cur = self._conn.execute(
            "INSERT INTO steps (workout_id, position, step_type, intensity, km, seconds, "
            "pace_fast, pace_slow, hr_low, hr_high, back_to_offset, count, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (workout_id, position, step.step_type, step.intensity,
             _dump_scalar(step.km), _dump_scalar(step.seconds),
             _dump_scalar(step.pace_fast), _dump_scalar(step.pace_slow),
             _dump_scalar(step.hr_low), _dump_scalar(step.hr_high),
             _dump_scalar(step.back_to_offset), _dump_scalar(step.count),
             json.dumps(step.extra)),
        )
        step_id = cur.lastrowid
        for d_position, drill in enumerate(step.drills or []):
            self._insert_drill(step_id, d_position, drill)
        return step_id

    def _insert_drill(self, step_id: int, position: int, drill: Drill) -> None:
        self._conn.execute(
            "INSERT INTO drills (step_id, position, name, seconds, reps, extra_json) "
            "VALUES (?,?,?,?,?,?)",
            (step_id, position, drill.name, _dump_scalar(drill.seconds),
             _dump_scalar(drill.reps), json.dumps(drill.extra)),
        )

    # ── Validation (delegates to the one existing implementation) ────────────
    def validate(self) -> tuple[list[str], list[str]]:
        data = plan_to_data(self.get_plan())
        return validate_plan_data(data)

    # ── Mutations — each commits, renumbers positions if needed, and writes
    #    the change straight back to the YAML file it was loaded from ────────
    def move_workout(self, workout_id: int, new_position: int) -> None:
        ids = [row[0] for row in
               self._conn.execute("SELECT id FROM workouts ORDER BY position").fetchall()]
        if workout_id not in ids:
            raise ValueError(f"workout id {workout_id} not found")
        ids.remove(workout_id)
        new_position = max(0, min(new_position, len(ids)))
        ids.insert(new_position, workout_id)
        for position, wid in enumerate(ids):
            self._conn.execute("UPDATE workouts SET position = ? WHERE id = ?", (position, wid))
        self._conn.commit()
        self._write_through()

    def duplicate_workout(self, workout_id: int) -> int:
        row = self._conn.execute(
            "SELECT filename, name, desc, type_code, distance_km, "
            "estimated_duration_min, extra_json FROM workouts WHERE id = ?",
            (workout_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"workout id {workout_id} not found")
        filename, name, desc, type_code, distance_km, duration, extra_json = row
        steps = self._get_steps(workout_id)
        max_position = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) FROM workouts"
        ).fetchone()[0]
        new_workout = Workout(
            filename=filename, name=name, desc=desc, type_code=type_code,
            distance_km=distance_km, estimated_duration_min=duration,
            steps=steps, extra=json.loads(extra_json or "{}"),
        )
        new_id = self._insert_workout(max_position + 1, new_workout)
        self._conn.commit()
        self._write_through()
        return new_id

    def delete_workout(self, workout_id: int) -> None:
        self._conn.execute("DELETE FROM workouts WHERE id = ?", (workout_id,))
        self._conn.commit()
        self._renumber_workouts()
        self._write_through()

    def rename_workout_filename(self, workout_id: int, new_filename: str) -> None:
        self._conn.execute(
            "UPDATE workouts SET filename = ?, name = ? WHERE id = ?",
            (new_filename, new_filename, workout_id),
        )
        self._conn.commit()
        self._write_through()

    def _renumber_workouts(self) -> None:
        ids = [row[0] for row in
               self._conn.execute("SELECT id FROM workouts ORDER BY position").fetchall()]
        for position, wid in enumerate(ids):
            self._conn.execute("UPDATE workouts SET position = ? WHERE id = ?", (position, wid))
        self._conn.commit()
