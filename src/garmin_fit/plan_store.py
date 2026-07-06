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

    def _insert_drill(self, step_id: int, position: int, drill: Drill) -> int:
        cur = self._conn.execute(
            "INSERT INTO drills (step_id, position, name, seconds, reps, extra_json) "
            "VALUES (?,?,?,?,?,?)",
            (step_id, position, drill.name, _dump_scalar(drill.seconds),
             _dump_scalar(drill.reps), json.dumps(drill.extra)),
        )
        return cur.lastrowid

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

    def find_workout_id_by_filename(self, filename: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM workouts WHERE filename = ?", (filename,)
        ).fetchone()
        return row[0] if row else None

    def _renumber_workouts(self) -> None:
        ids = [row[0] for row in
               self._conn.execute("SELECT id FROM workouts ORDER BY position").fetchall()]
        for position, wid in enumerate(ids):
            self._conn.execute("UPDATE workouts SET position = ? WHERE id = ?", (position, wid))
        self._conn.commit()

    # ── Step-level mutations (visual workout builder) ─────────────────────────
    # back_to_offset is always a plain 0-based index into a workout's own
    # steps list (see plan_domain.STEP_REQUIRED_FIELDS["repeat"] and
    # workout_utils.build_yaml_to_fit_index, which does the FIT-index/sbu
    # translation only at build time). All bookkeeping below is therefore
    # pure list-index arithmetic against this workout's steps, nothing more.
    @staticmethod
    def _offset_of(back_to_offset) -> int | None:
        try:
            return int(back_to_offset)
        except (TypeError, ValueError):
            return None

    def _shift_repeat_offsets(self, workout_id: int, insert_at: int, delta: int) -> None:
        """Shift back_to_offset by delta for every repeat step in this workout
        whose back_to_offset >= insert_at. delta=+1 on insert, -1 on delete."""
        rows = self._conn.execute(
            "SELECT id, back_to_offset FROM steps WHERE workout_id = ? AND step_type = 'repeat'",
            (workout_id,),
        ).fetchall()
        for step_id, back_to_offset in rows:
            offset = self._offset_of(back_to_offset)
            if offset is not None and offset >= insert_at:
                self._conn.execute(
                    "UPDATE steps SET back_to_offset = ? WHERE id = ?",
                    (str(offset + delta), step_id),
                )

    def insert_step(self, workout_id: int, position: int, step: WorkoutStep) -> int:
        """Insert a step at `position`, shifting later steps' positions and
        any existing repeat steps' back_to_offset by +1."""
        rows = self._conn.execute(
            "SELECT id, position FROM steps WHERE workout_id = ? AND position >= ?",
            (workout_id, position),
        ).fetchall()
        for step_id, pos in rows:
            self._conn.execute("UPDATE steps SET position = ? WHERE id = ?", (pos + 1, step_id))
        self._shift_repeat_offsets(workout_id, position, +1)
        new_step_id = self._insert_step(workout_id, position, step)
        self._conn.commit()
        self._write_through()
        return new_step_id

    def delete_step(self, step_id: int) -> None:
        """Delete a step, shifting later positions and repeat offsets left.

        Rejects (ValueError, no write) rather than silently corrupting data
        when the deleted step is itself the anchor of an existing repeat
        group, or when shifting would leave a repeat step's back_to_offset
        pointing at or past its own (new) position.
        """
        row = self._conn.execute(
            "SELECT workout_id, position FROM steps WHERE id = ?", (step_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"step id {step_id} not found")
        workout_id, deleted_position = row

        all_steps = self._conn.execute(
            "SELECT id, position, step_type, back_to_offset FROM steps "
            "WHERE workout_id = ? ORDER BY position",
            (workout_id,),
        ).fetchall()

        for other_id, _pos, step_type, back_to_offset in all_steps:
            if other_id == step_id or step_type != "repeat":
                continue
            if self._offset_of(back_to_offset) == deleted_position:
                raise ValueError(
                    f"Cannot delete step at position {deleted_position}: it is "
                    f"the start of a repeat group (repeat step id {other_id}). "
                    "Remove or edit that repeat block first."
                )

        # Compute the full post-delete state before writing anything, so an
        # invalid resulting repeat offset aborts with zero partial writes.
        updates = []
        for other_id, pos, step_type, back_to_offset in all_steps:
            if other_id == step_id:
                continue
            new_position = pos - 1 if pos > deleted_position else pos
            new_offset_str = back_to_offset
            if step_type == "repeat":
                offset = self._offset_of(back_to_offset)
                if offset is not None and offset > deleted_position:
                    offset -= 1
                    new_offset_str = str(offset)
                if offset is not None and offset >= new_position:
                    raise ValueError(
                        f"Deleting step at position {deleted_position} would make "
                        f"repeat step {other_id}'s back_to_offset invalid."
                    )
            updates.append((other_id, new_position, new_offset_str))

        self._conn.execute("DELETE FROM steps WHERE id = ?", (step_id,))
        for other_id, new_position, new_offset_str in updates:
            self._conn.execute(
                "UPDATE steps SET position = ?, back_to_offset = ? WHERE id = ?",
                (new_position, new_offset_str, other_id),
            )
        self._conn.commit()
        self._write_through()

    def move_step(self, step_id: int, new_position: int) -> None:
        """Reorder a step within its workout.

        v1 scope: rejected whenever the workout contains ANY repeat step,
        since moving a step into/out of an existing repeat group's range is
        ambiguous without guessing user intent. The visual builder only
        needs free reordering during its pre-commit draft phase (plain
        Python list operations, never touching PlanStore), so this stricter
        guard is never actually hit by the current GUI flow.
        """
        row = self._conn.execute(
            "SELECT workout_id FROM steps WHERE id = ?", (step_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"step id {step_id} not found")
        workout_id = row[0]
        has_repeat = self._conn.execute(
            "SELECT 1 FROM steps WHERE workout_id = ? AND step_type = 'repeat' LIMIT 1",
            (workout_id,),
        ).fetchone()
        if has_repeat:
            raise ValueError(
                "Cannot reorder steps in a workout that already has a repeat "
                "block. Reorder before adding a Repeat block, or remove the "
                "repeat block first."
            )
        ids = [r[0] for r in self._conn.execute(
            "SELECT id FROM steps WHERE workout_id = ? ORDER BY position", (workout_id,)
        ).fetchall()]
        ids.remove(step_id)
        new_position = max(0, min(new_position, len(ids)))
        ids.insert(new_position, step_id)
        for position, sid in enumerate(ids):
            self._conn.execute("UPDATE steps SET position = ? WHERE id = ?", (position, sid))
        self._conn.commit()
        self._write_through()

    def add_repeat_over_range(
        self, workout_id: int, start_position: int, end_position: int, count: int
    ) -> int:
        """Insert a repeat step covering [start_position, end_position],
        computing back_to_offset internally so callers only ever pass the
        positions they already have on screen -- never the offset itself."""
        steps = self._conn.execute(
            "SELECT id, position, step_type, back_to_offset FROM steps "
            "WHERE workout_id = ? ORDER BY position",
            (workout_id,),
        ).fetchall()
        n = len(steps)
        if not (0 <= start_position <= end_position < n):
            raise ValueError(f"invalid range [{start_position}, {end_position}] for {n} step(s)")
        if count <= 0:
            raise ValueError("count must be positive")

        for _id, pos, step_type, back_to_offset in steps:
            if step_type != "repeat":
                continue
            if start_position <= pos <= end_position:
                raise ValueError(
                    "selected range contains an existing repeat step; "
                    "nested repeats are not supported"
                )
            offset = self._offset_of(back_to_offset)
            if offset is not None and start_position <= offset <= end_position:
                raise ValueError(
                    "selected range overlaps an existing repeat group's start; "
                    "nested/overlapping repeats are not supported"
                )

        new_step = WorkoutStep(step_type="repeat", back_to_offset=start_position, count=count)
        return self.insert_step(workout_id, end_position + 1, new_step)

    def add_drill(self, step_id: int, drill: Drill, position: int | None = None) -> int:
        """Insert a drill into an sbu_block step's drill list. Drills never
        participate in back_to_offset math (an sbu_block is one YAML step
        regardless of drill count)."""
        if position is None:
            max_pos = self._conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM drills WHERE step_id = ?", (step_id,)
            ).fetchone()[0]
            position = max_pos + 1
        else:
            self._conn.execute(
                "UPDATE drills SET position = position + 1 WHERE step_id = ? AND position >= ?",
                (step_id, position),
            )
        drill_id = self._insert_drill(step_id, position, drill)
        self._conn.commit()
        self._write_through()
        return drill_id

    def delete_drill(self, drill_id: int) -> None:
        row = self._conn.execute("SELECT step_id FROM drills WHERE id = ?", (drill_id,)).fetchone()
        if row is None:
            raise ValueError(f"drill id {drill_id} not found")
        step_id = row[0]
        self._conn.execute("DELETE FROM drills WHERE id = ?", (drill_id,))
        self._renumber_drills(step_id)
        self._conn.commit()
        self._write_through()

    def move_drill(self, drill_id: int, new_position: int) -> None:
        row = self._conn.execute("SELECT step_id FROM drills WHERE id = ?", (drill_id,)).fetchone()
        if row is None:
            raise ValueError(f"drill id {drill_id} not found")
        step_id = row[0]
        ids = [r[0] for r in self._conn.execute(
            "SELECT id FROM drills WHERE step_id = ? ORDER BY position", (step_id,)
        ).fetchall()]
        ids.remove(drill_id)
        new_position = max(0, min(new_position, len(ids)))
        ids.insert(new_position, drill_id)
        for position, did in enumerate(ids):
            self._conn.execute("UPDATE drills SET position = ? WHERE id = ?", (position, did))
        self._conn.commit()
        self._write_through()

    def _renumber_drills(self, step_id: int) -> None:
        ids = [r[0] for r in self._conn.execute(
            "SELECT id FROM drills WHERE step_id = ? ORDER BY position", (step_id,)
        ).fetchall()]
        for position, did in enumerate(ids):
            self._conn.execute("UPDATE drills SET position = ? WHERE id = ?", (position, did))

    # ── Whole-workout creation (visual workout builder) ───────────────────────
    def add_workout(
        self, filename, name, desc="", type_code="",
        distance_km=None, estimated_duration_min=None,
        steps=None, position=None,
    ) -> int:
        """Append (or insert) a brand-new workout, e.g. one built in the
        visual builder tab."""
        if position is None:
            position = self._conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM workouts"
            ).fetchone()[0]
        else:
            self._conn.execute(
                "UPDATE workouts SET position = position + 1 WHERE position >= ?", (position,)
            )
        workout = Workout(
            filename=filename, name=name, desc=desc, type_code=type_code,
            distance_km=distance_km, estimated_duration_min=estimated_duration_min,
            steps=list(steps or []), extra={},
        )
        workout_id = self._insert_workout(position, workout)
        self._conn.commit()
        self._write_through()
        return workout_id
