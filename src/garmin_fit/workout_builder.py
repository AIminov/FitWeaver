"""Pure-Python support for the GUI's visual (no-LLM) workout builder.

No Tkinter, no SQLite here — this module only knows about plan_domain
dataclasses, so it's independently testable and reusable (e.g. a future CLI
"scaffold a workout" command could import TEMPLATES too).

compute_repeat_step() intentionally duplicates none of PlanStore's SQL, but
does mirror its *validation rules* for a repeat range (see
PlanStore.add_repeat_over_range in plan_store.py) so the GUI's pre-commit
draft preview and the final committed result can never disagree about
whether a given back_to_offset is valid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .plan_domain import Drill, Workout, WorkoutPlan, WorkoutStep, plan_to_data
from .plan_validator import validate_plan_data
from .sbu_block import DEFAULT_DRILLS


def compute_repeat_step(
    steps: list[WorkoutStep], start_position: int, end_position: int, count: int
) -> WorkoutStep:
    """Given an in-memory draft step list and a selected range, return the
    repeat WorkoutStep to insert after end_position. The caller never
    computes or stores back_to_offset itself -- it's always start_position.
    """
    n = len(steps)
    if not (0 <= start_position <= end_position < n):
        raise ValueError(f"invalid range [{start_position}, {end_position}] for {n} step(s)")
    if count <= 0:
        raise ValueError("count must be positive")

    for pos, step in enumerate(steps):
        if step.step_type != "repeat":
            continue
        if start_position <= pos <= end_position:
            raise ValueError(
                "selected range contains an existing repeat step; "
                "nested repeats are not supported"
            )
        try:
            offset = int(step.back_to_offset)
        except (TypeError, ValueError):
            offset = None
        if offset is not None and start_position <= offset <= end_position:
            raise ValueError(
                "selected range overlaps an existing repeat group's start; "
                "nested/overlapping repeats are not supported"
            )

    return WorkoutStep(step_type="repeat", back_to_offset=start_position, count=count)


def validate_draft(filename: str, name: str, steps: list[WorkoutStep]) -> tuple[list[str], list[str]]:
    """Validate a draft before it's ever written to PlanStore, reusing the
    one existing validator rather than a second implementation."""
    workout = Workout(
        filename=filename, name=name or filename, desc="", type_code="mixed",
        steps=list(steps),
    )
    data = plan_to_data(WorkoutPlan(workouts=[workout]))
    return validate_plan_data(data, enforce_filename_name_match=False)


@dataclass(frozen=True)
class BlockDef:
    """Palette entry: one button -> one default WorkoutStep + the fields
    the generic editor form should show for it. Adding a new block type is
    adding an entry here, not writing new widget code."""

    key: str
    label: str
    step_type: str
    intensity: str | None
    fields: tuple[str, ...]
    field_labels: dict[str, str] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)

    def make(self) -> WorkoutStep:
        step = WorkoutStep(step_type=self.step_type, intensity=self.intensity, **self.defaults)
        if self.step_type == "sbu_block":
            step.drills = [Drill(name=d["name"], seconds=d.get("seconds", 60), reps=d.get("reps", 2))
                           for d in DEFAULT_DRILLS]
        return step


BLOCK_DEFS: dict[str, BlockDef] = {
    "warmup": BlockDef(
        key="warmup", label="Разминка", step_type="dist_open", intensity="warmup",
        fields=("km",), field_labels={"km": "Расстояние (км)"},
        defaults={"km": 2.0},
    ),
    "active_km": BlockDef(
        key="active_km", label="Активный км", step_type="dist_hr", intensity="active",
        fields=("km", "hr_low", "hr_high"),
        field_labels={"km": "Расстояние (км)", "hr_low": "Пульс от", "hr_high": "Пульс до"},
        defaults={"km": 0.8, "hr_low": 150, "hr_high": 165},
    ),
    "active_min": BlockDef(
        key="active_min", label="Активный мин", step_type="time_hr", intensity="active",
        fields=("seconds", "hr_low", "hr_high"),
        field_labels={"seconds": "Длительность (сек)", "hr_low": "Пульс от", "hr_high": "Пульс до"},
        defaults={"seconds": 300, "hr_low": 150, "hr_high": 165},
    ),
    "recovery": BlockDef(
        key="recovery", label="Восстановление", step_type="dist_open", intensity="recovery",
        fields=("km",), field_labels={"km": "Расстояние (км)"},
        defaults={"km": 0.4},
    ),
    "cooldown": BlockDef(
        key="cooldown", label="Заминка", step_type="dist_open", intensity="cooldown",
        fields=("km",), field_labels={"km": "Расстояние (км)"},
        defaults={"km": 1.0},
    ),
    "sbu": BlockDef(
        key="sbu", label="СБУ", step_type="sbu_block", intensity=None,
        fields=(), field_labels={}, defaults={},
    ),
}


def template_intervals() -> list[WorkoutStep]:
    return [
        WorkoutStep(step_type="dist_open", intensity="warmup", km=2.0),
        WorkoutStep(step_type="dist_hr", intensity="active", km=0.8, hr_low=160, hr_high=170),
        WorkoutStep(step_type="dist_hr", intensity="recovery", km=0.4, hr_low=130, hr_high=145),
        WorkoutStep(step_type="repeat", back_to_offset=1, count=6),
        WorkoutStep(step_type="dist_hr", intensity="cooldown", km=1.0, hr_low=130, hr_high=145),
    ]


def template_tempo() -> list[WorkoutStep]:
    return [
        WorkoutStep(step_type="dist_open", intensity="warmup", km=2.0),
        WorkoutStep(step_type="dist_pace", intensity="active", km=5.0,
                    pace_fast="4:50", pace_slow="5:00"),
        WorkoutStep(step_type="dist_open", intensity="cooldown", km=1.0),
    ]


def template_long_with_pickup() -> list[WorkoutStep]:
    return [
        WorkoutStep(step_type="dist_hr", intensity="active", km=12.0, hr_low=125, hr_high=140),
        WorkoutStep(step_type="dist_pace", intensity="active", km=2.0,
                    pace_fast="5:00", pace_slow="5:10"),
    ]


TEMPLATES: dict[str, tuple[str, Callable[[], list[WorkoutStep]]]] = {
    "intervals": ("Интервалы", template_intervals),
    "tempo": ("Темповый бег", template_tempo),
    "long_with_pickup": ("Длинный с ускорением", template_long_with_pickup),
}
