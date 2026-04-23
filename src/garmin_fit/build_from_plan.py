"""
Build FIT workout files directly from YAML/domain objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from .config import LOGS_DIR, OUTPUT_DIR
from .logging_utils import setup_file_logging as _setup_logging
from .plan_domain import Drill, Workout, WorkoutPlan, drill_to_data, plan_from_data
from .plan_processing import repair_plan_data, sanitize_workout_name
from .plan_validator import validate_plan_data
from .sbu_block import sbu_block
from .state_manager import fit_timestamp_to_unix_ms, get_next_serial_timestamp
from .workout_utils import (
    ACT,
    CD,
    REC,
    WU,
    build_yaml_to_fit_index,
    dist_hr,
    dist_open,
    dist_pace,
    open_step,
    repeat_step,
    save_workout,
    time_hr,
    time_pace,
    time_step,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

INTENSITY_MAP = {
    "active": ACT,
    "warmup": WU,
    "cooldown": CD,
    "recovery": REC,
}


@dataclass(slots=True)
class PlanBuildInput:
    plan: WorkoutPlan
    repairs: list[str]
    warnings: list[str]


def setup_file_logging(run_id=None):
    """Setup file logging for direct YAML builder."""
    return _setup_logging(prefix="build_from_plan", run_id=run_id)


def load_plan_build_input(yaml_path: Path) -> PlanBuildInput:
    """Load, repair, validate, and convert YAML into domain objects."""
    yaml_path = Path(yaml_path)
    with open(yaml_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if data is None:
        raise ValueError("YAML file is empty")

    repaired_data, repairs = repair_plan_data(data)
    errors, warnings = validate_plan_data(repaired_data, enforce_filename_name_match=True)
    if errors:
        joined = "\n".join(f"- {error}" for error in errors[:20])
        raise ValueError(f"YAML validation failed:\n{joined}")

    plan = plan_from_data(repaired_data)
    if not plan.workouts:
        raise ValueError("No workouts found in YAML file")

    return PlanBuildInput(plan=plan, repairs=repairs, warnings=warnings)


def build_workout_steps(workout: Workout):
    """Build FIT workout steps directly from a workout domain object."""
    steps = []
    idx = 0
    yaml_to_fit = build_yaml_to_fit_index(workout.steps)

    for step in workout.steps:
        step_type = step.step_type
        intensity = _resolve_intensity(step.intensity)

        if step_type == "dist_pace":
            steps.append(dist_pace(idx, step.km, step.pace_fast, step.pace_slow, intensity))
            idx += 1
        elif step_type == "dist_open":
            steps.append(dist_open(idx, step.km, intensity))
            idx += 1
        elif step_type == "time_pace":
            steps.append(time_pace(idx, step.seconds, step.pace_fast, step.pace_slow, intensity))
            idx += 1
        elif step_type == "time_step":
            steps.append(time_step(idx, step.seconds, intensity))
            idx += 1
        elif step_type == "dist_hr":
            steps.append(dist_hr(idx, step.km, step.hr_low, step.hr_high, intensity))
            idx += 1
        elif step_type == "time_hr":
            steps.append(time_hr(idx, step.seconds, step.hr_low, step.hr_high, intensity))
            idx += 1
        elif step_type == "open_step":
            steps.append(open_step(idx, intensity))
            idx += 1
        elif step_type == "repeat":
            back_to_fit = yaml_to_fit.get(step.back_to_offset, step.back_to_offset)
            steps.append(repeat_step(idx, back_to_fit, step.count))
            idx += 1
        elif step_type == "sbu_block":
            drills = _drills_to_data(step.drills)
            built_steps, next_idx = sbu_block(idx, drills=drills)
            steps.extend(built_steps)
            idx = next_idx
        else:
            raise ValueError(f"Unsupported step type for direct build: {step_type}")

    if not steps:
        raise ValueError(f"Workout '{workout.name}' has no steps")

    return steps


def build_fit_from_workout(
    workout: Workout,
    serial_number: int,
    timestamp: int,
    *,
    output_dir: Path = OUTPUT_DIR,
) -> Path:
    """Build a single FIT file directly from a workout domain object."""
    steps = build_workout_steps(workout)
    output_filename = sanitize_workout_name(workout.filename or workout.name or "workout") + ".fit"
    output_path = output_dir / output_filename

    save_workout(
        str(output_path),
        str(workout.name or workout.filename or output_path.stem),
        steps,
        serial_number=serial_number,
        time_created_ms=fit_timestamp_to_unix_ms(timestamp),
    )
    return output_path


def build_all_fits_from_plan(yaml_path: Path, verify_with_csv: bool = False):
    """
    Build FIT files directly from YAML.

    Returns:
        tuple[int, int]: (success_count, total_count)
    """
    logger.info("=" * 70)
    logger.info("BUILDING FIT FILES DIRECTLY FROM YAML")
    logger.info("=" * 70)

    plan_input = load_plan_build_input(Path(yaml_path))
    for repair in plan_input.repairs:
        logger.info(f"[REPAIR] {repair}")
    for warning in plan_input.warnings:
        logger.warning(f"[WARN] {warning}")

    workouts = plan_input.plan.workouts
    logger.info(f"Found {len(workouts)} workout(s)")
    logger.info("Allocating unique file_id values...")
    serial_timestamp_pairs = get_next_serial_timestamp(len(workouts))
    logger.info(f"Serial number range: {serial_timestamp_pairs[0][0]} - {serial_timestamp_pairs[-1][0]}")
    logger.info("")

    verifier = _load_fit_verifier() if verify_with_csv else None
    success_count = 0
    failed_names: list[str] = []

    for workout, (serial, timestamp) in zip(workouts, serial_timestamp_pairs):
        name = workout.filename or workout.name or "?"
        try:
            fit_path = build_fit_from_workout(workout, serial, timestamp)
            if verifier is None or verifier(fit_path):
                logger.info(f"  [OK] Generated: {fit_path.name}")
                success_count += 1
            else:
                logger.warning(f"  [FAIL] CSV verification failed: {fit_path.name}")
                failed_names.append(name)
        except Exception as exc:
            logger.error(f"  [FAIL] {name}: {exc}", exc_info=True)
            failed_names.append(name)

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"BUILD COMPLETE: {success_count}/{len(workouts)} successful")
    if failed_names:
        logger.warning(f"FAILED ({len(failed_names)}): {', '.join(failed_names)}")
        if success_count > 0:
            logger.warning(
                f"Partial results are in {OUTPUT_DIR} — "
                "remove or overwrite before retrying to avoid duplicates."
            )
    logger.info("=" * 70)

    if success_count > 0:
        logger.info(f"\nOutput directory: {OUTPUT_DIR}")
        logger.info(f"Generated {success_count} FIT file(s)")

    return success_count, len(workouts)


def _resolve_intensity(value: str | None):
    if value is None:
        return ACT
    return INTENSITY_MAP.get(value, ACT)


def _drills_to_data(drills: Iterable[Drill] | None):
    if drills is None:
        return None
    return [drill_to_data(drill) for drill in drills]


def _load_fit_verifier():
    from .build_fits import verify_fit_with_csv_tool
    return verify_fit_with_csv_tool
