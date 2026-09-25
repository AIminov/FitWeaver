"""Safety checks for targets in the explicitly marked training-text format."""

from __future__ import annotations

import re
from typing import Any

STEP_MARKER = "**** ШАГ ****"
_TARGET_FIELDS = {
    "hr": {"hr_low", "hr_high"},
    "pace": {"pace_fast", "pace_slow"},
    "cadence": {"cad_low", "cad_high"},
}
_ALLOWED_INTENSITIES = {"active", "warmup", "cooldown", "recovery"}
_HR_LABEL = re.compile(r"^\s*(?:пульс|чсс|hr)\s*[:：-]?\s*(.*?)\s*$", re.IGNORECASE)
_PACE_LABEL = re.compile(r"^\s*(?:темп|pace)\s*[:：-]?\s*(.*?)\s*$", re.IGNORECASE)
_CADENCE_LABEL = re.compile(
    r"^\s*(?:частота шагов|каденс|cadence)\s*[:：-]?\s*(.*?)\s*$", re.IGNORECASE
)
_RANGE = re.compile(r"(?P<low>\d{2,3})\s*(?:[-–—]|\bдо\b)\s*(?P<high>\d{2,3})")
_PACE_RANGE = re.compile(
    r"(?P<first>\d{1,2}:\d{2})(?:\s*(?:[-–—]|\bдо\b)\s*(?P<second>\d{1,2}:\d{2}))?"
)
_DISTANCE_VALUE = re.compile(r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>км|km|м|m)\b", re.IGNORECASE)
_DURATION_VALUE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>секунд(?:а|ы)?|сек|s|min|минут(?:а|ы)?|мин|ч|час(?:а|ов)?)\b",
    re.IGNORECASE,
)


def _source_steps(source_text: str) -> list[list[str]]:
    steps: list[list[str]] = []
    current: list[str] | None = None
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if line == STEP_MARKER:
            if current is not None:
                steps.append(current)
            current = []
        elif line.startswith("==== ТРЕНИРОВКА"):
            if current is not None:
                steps.append(current)
                current = None
        elif line.startswith("****"):
            if current is not None:
                steps.append(current)
                current = None
        elif current is not None:
            current.append(line)
    if current is not None:
        steps.append(current)
    return steps


def _pace_seconds(value: str) -> int:
    minutes, seconds = value.split(":", maxsplit=1)
    return int(minutes) * 60 + int(seconds)


def _expected_step_target(
    lines: list[str],
) -> tuple[str | None, tuple[Any, ...] | None, bool]:
    for line in lines:
        match = _HR_LABEL.match(line)
        if match:
            value = match.group(1)
            if re.search(r"\b(?:нет|не задан|нет данных)\b", value, re.IGNORECASE):
                return None, None, False
            zone = re.search(r"(?:\bz\s*|\bзона\s*)[1-5]\b", value, re.IGNORECASE)
            if zone:
                return "hr", None, True
            bounds = _RANGE.search(value)
            if bounds:
                return "hr", (int(bounds.group("low")), int(bounds.group("high"))), True
            # A single cap/value cannot become a Garmin range without guessing.
            return None, None, bool(value)

        match = _PACE_LABEL.match(line)
        if match:
            value = match.group(1)
            pace = _PACE_RANGE.search(value)
            if pace:
                first = _pace_seconds(pace.group("first"))
                second = pace.group("second")
                return "pace", (first, _pace_seconds(second) if second else first), True
            return None, None, bool(value)

        match = _CADENCE_LABEL.match(line)
        if match:
            bounds = _RANGE.search(match.group(1))
            if bounds:
                return "cadence", (int(bounds.group("low")), int(bounds.group("high"))), True
            return None, None, bool(match.group(1))

    return None, None, False


def _source_step_measure(lines: list[str]) -> tuple[str | None, float | int | None]:
    for line in lines:
        distance_line = re.match(r"^\s*(?:дистанция|distance)\s*[:：]\s*(.*)$", line, re.IGNORECASE)
        if distance_line:
            match = _DISTANCE_VALUE.search(distance_line.group(1))
            if not match:
                return None, None
            value = float(match.group("value").replace(",", "."))
            unit = match.group("unit").lower()
            return "km", value if unit in {"км", "km"} else value / 1000

        duration_line = re.match(r"^\s*(?:длительность|duration)\s*[:：]\s*(.*)$", line, re.IGNORECASE)
        if duration_line:
            match = _DURATION_VALUE.search(duration_line.group(1))
            if not match:
                return None, None
            value = float(match.group("value").replace(",", "."))
            unit = match.group("unit").lower()
            if unit in {"сек", "секунд", "секунда", "секунды", "s"}:
                seconds = value
            elif unit in {"ч", "час", "часа", "часов"}:
                seconds = value * 3600
            else:
                seconds = value * 60
            return "seconds", int(seconds) if seconds.is_integer() else seconds

    return None, None


def _source_step_shape(lines: list[str]) -> str:
    if any(re.match(r"^\s*тип\s*[:：]\s*сбу\b", line, re.IGNORECASE) for line in lines):
        return "sbu_block"
    if any(re.match(r"^\s*дистанция\s*[:：]", line, re.IGNORECASE) for line in lines):
        return "distance"
    if any(re.match(r"^\s*длительность\s*[:：]", line, re.IGNORECASE) for line in lines):
        return "time"
    return "open_step"


def _source_step_intensity(lines: list[str]) -> str | None:
    """Map only explicit, unambiguous marked step labels to Garmin intensity enums."""
    for line in lines:
        match = re.match(r"^\s*тип\s*[:：]\s*(.*?)\s*$", line, re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip().casefold()
        if value in {"разминка", "warmup"}:
            return "warmup"
        if value in {"заминка", "cooldown"}:
            return "cooldown"
        if value in {"восстановление", "recovery"}:
            return "recovery"
        if value in {"работа", "ускорение", "active", "work"}:
            return "active"
        return None
    return None


def _source_workout_shapes(source_text: str) -> list[list[tuple[str, int | None, int | None]]]:
    """Return each marked workout as (step kind or repeat, offset, count) rows."""
    workouts: list[list[tuple[str, int | None, int | None]]] = []
    current_workout: list[tuple[str, int | None, int | None]] | None = None
    current_step: list[str] | None = None
    repeat_start: int | None = None
    repeat_count: int | None = None

    def flush_step() -> None:
        nonlocal current_step
        if current_step is not None and current_workout is not None:
            current_workout.append((_source_step_shape(current_step), None, None))
        current_step = None

    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if line.startswith("==== ТРЕНИРОВКА"):
            flush_step()
            if current_workout is not None:
                workouts.append(current_workout)
            current_workout = []
            repeat_start = None
            repeat_count = None
            continue
        if current_workout is None:
            continue
        repeat_match = re.fullmatch(
            r"\*{4}\s*ПОВТОР:\s*(\d+)\s+РАЗ\s*\*{4}", line, re.IGNORECASE
        )
        if repeat_match:
            flush_step()
            repeat_start = len(current_workout)
            repeat_count = int(repeat_match.group(1))
            continue
        if line == STEP_MARKER:
            flush_step()
            current_step = []
            continue
        if line.startswith("****"):
            flush_step()
            if "КОНЕЦ ПОВТОРА" in line.upper() and repeat_start is not None and repeat_count is not None:
                current_workout.append(("repeat", repeat_start, repeat_count))
                repeat_start = None
                repeat_count = None
            continue
        if current_step is not None:
            current_step.append(line)

    flush_step()
    if current_workout is not None:
        workouts.append(current_workout)
    return workouts


def _generated_step_shape(step: dict[str, Any]) -> str:
    kind = str(step.get("type", ""))
    if kind == "repeat" or kind == "sbu_block" or kind == "open_step":
        return kind
    if kind.startswith("dist_"):
        return "distance"
    if kind.startswith("time_"):
        return "time"
    return kind


def _model_content_steps(steps: list[Any]) -> list[dict[str, Any]]:
    """Flatten optional model-nested repeats and discard Garmin repeat rows."""
    output: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "repeat":
            nested = step.get("steps")
            if isinstance(nested, list):
                output.extend(_model_content_steps(nested))
            continue
        output.append(step)
    return output


def validate_marked_source_model_steps(source_text: str, data: Any) -> list[str]:
    """Validate LLM steps while repeat rows are delegated to the deterministic compiler."""
    if STEP_MARKER not in source_text or not isinstance(data, dict):
        return []
    expected_workouts = _source_workout_shapes(source_text)
    actual_workouts = data.get("workouts")
    if not isinstance(actual_workouts, list):
        return []
    if len(expected_workouts) != len(actual_workouts):
        return [
            "Marked-source step mismatch: source has "
            f"{len(expected_workouts)} workouts, YAML has {len(actual_workouts)}"
        ]

    issues: list[str] = []
    for workout_index, (expected, workout) in enumerate(zip(expected_workouts, actual_workouts), 1):
        expected_steps = [kind for kind, _offset, _count in expected if kind != "repeat"]
        raw_steps = workout.get("steps") if isinstance(workout, dict) else None
        actual_steps = _model_content_steps(raw_steps) if isinstance(raw_steps, list) else []
        actual = [_generated_step_shape(step) for step in actual_steps]
        if actual != expected_steps:
            issues.append(
                f"Marked-source step mismatch in workout {workout_index}: "
                f"expected ordered steps {expected_steps}, got {actual}"
            )
    return issues


def compile_marked_source_repeats(source_text: str, data: Any) -> tuple[list[str], list[str]]:
    """Replace model-produced repeat rows with repeat metadata from explicit source markers."""
    if STEP_MARKER not in source_text or not isinstance(data, dict):
        return [], []
    expected_workouts = _source_workout_shapes(source_text)
    workouts = data.get("workouts")
    if not isinstance(workouts, list) or len(workouts) != len(expected_workouts):
        return [], ["Repeat compiler skipped: marked-source workout count does not match YAML"]

    repairs: list[str] = []
    warnings: list[str] = []
    for workout_index, (expected, workout) in enumerate(zip(expected_workouts, workouts), 1):
        if not isinstance(workout, dict):
            warnings.append(f"Repeat compiler skipped workout {workout_index}: YAML entry is not a mapping")
            continue
        steps = workout.get("steps")
        if not isinstance(steps, list):
            warnings.append(f"Repeat compiler skipped workout {workout_index}: steps is not a list")
            continue
        model_steps = _model_content_steps(steps)
        expected_step_count = sum(kind != "repeat" for kind, _offset, _count in expected)
        if len(model_steps) != expected_step_count:
            warnings.append(
                f"Repeat compiler skipped workout {workout_index}: source has "
                f"{expected_step_count} steps but YAML has {len(model_steps)}"
            )
            continue

        rebuilt_steps: list[dict[str, Any]] = []
        model_index = 0
        for kind, offset, count in expected:
            if kind == "repeat":
                rebuilt_steps.append({
                    "type": "repeat",
                    "back_to_offset": offset,
                    "count": count,
                })
            else:
                rebuilt_steps.append(model_steps[model_index])
                model_index += 1
        if steps != rebuilt_steps:
            workout["steps"] = rebuilt_steps
            repairs.append(
                f"workouts[{workout_index - 1}]: compiled repeat placement/count from explicit source markers"
            )
    return repairs, warnings


def validate_marked_source_structure(source_text: str, data: Any) -> list[str]:
    """Check marked step order and repeat placement without comparing distances."""
    if STEP_MARKER not in source_text or not isinstance(data, dict):
        return []
    expected_workouts = _source_workout_shapes(source_text)
    actual_workouts = data.get("workouts")
    if not isinstance(actual_workouts, list):
        return []
    if len(expected_workouts) != len(actual_workouts):
        return [
            "Marked-source structure mismatch: source has "
            f"{len(expected_workouts)} workouts, YAML has {len(actual_workouts)}"
        ]

    issues: list[str] = []
    for workout_index, (expected, workout) in enumerate(zip(expected_workouts, actual_workouts), 1):
        raw_steps = workout.get("steps") if isinstance(workout, dict) else None
        if not isinstance(raw_steps, list):
            actual: list[tuple[str, int | None, int | None]] = []
        else:
            actual = []
            for step in raw_steps:
                if not isinstance(step, dict):
                    actual.append(("invalid_step", None, None))
                elif step.get("type") == "repeat":
                    back = step.get("back_to_offset")
                    count = step.get("count")
                    actual.append(("repeat", back if isinstance(back, int) else None, count if isinstance(count, int) else None))
                else:
                    actual.append((_generated_step_shape(step), None, None))
        if actual != expected:
            issues.append(
                f"Marked-source structure mismatch in workout {workout_index}: "
                f"expected ordered steps/repeats {expected}, got {actual}; "
                "preserve every step, its order, and repeat placement/count"
            )
    return issues


def _generated_step_target(step: dict[str, Any]) -> tuple[str | None, tuple[Any, ...] | None]:
    step_type = str(step.get("type", ""))
    if step_type.endswith("_hr") or "hr_low" in step or "hr_high" in step:
        if isinstance(step.get("hr_low"), (int, float)) and isinstance(
            step.get("hr_high"), (int, float)
        ):
            return "hr", (int(step["hr_low"]), int(step["hr_high"]))
        return "hr", None
    if step_type.endswith("_pace") or "pace_fast" in step or "pace_slow" in step:
        try:
            fast = _pace_seconds(str(step["pace_fast"]))
            slow = _pace_seconds(str(step["pace_slow"]))
        except (KeyError, ValueError):
            return "pace", None
        return "pace", (fast, slow)
    if step_type.endswith("_cadence") or "cad_low" in step or "cad_high" in step:
        if isinstance(step.get("cad_low"), (int, float)) and isinstance(
            step.get("cad_high"), (int, float)
        ):
            return "cadence", (int(step["cad_low"]), int(step["cad_high"]))
        return "cadence", None
    return None, None


def _target_matches(
    kind: str,
    expected: tuple[Any, ...] | None,
    actual_kind: str | None,
    actual: tuple[Any, ...] | None,
) -> bool:
    if actual_kind != kind:
        return False
    if expected is None:
        return True
    if actual == expected:
        return True
    if kind == "pace" and expected[0] == expected[1] and actual is not None:
        # repair_plan_data widens equal numeric pace bounds by the user's ±10 sec rule.
        return actual == (expected[0] - 10, expected[0] + 10)
    return False


def _target_step_type(measure_kind: str, target_kind: str) -> str:
    duration_prefix = "dist" if measure_kind == "km" else "time"
    suffix = {"hr": "hr", "pace": "pace", "cadence": "cadence"}[target_kind]
    return f"{duration_prefix}_{suffix}"


def _clear_target_fields(step: dict[str, Any]) -> None:
    for fields in _TARGET_FIELDS.values():
        for field in fields:
            step.pop(field, None)


def _remove_target_and_make_open(step: dict[str, Any]) -> str:
    previous = str(step.get("type", ""))
    for fields in _TARGET_FIELDS.values():
        for field in fields:
            step.pop(field, None)

    km = step.get("km")
    seconds = step.get("seconds")
    if isinstance(km, (int, float)) and km > 0:
        step["type"] = "dist_open"
        step.pop("seconds", None)
    elif isinstance(seconds, (int, float)) and seconds > 0:
        step["type"] = "time_step"
        step.pop("km", None)
    else:
        step.pop("km", None)
        step.pop("seconds", None)
        step["type"] = "open_step"
    return previous


def sanitize_marked_source_targets(
    source_text: str,
    data: Any,
) -> tuple[list[str], list[str]]:
    """Remove unsupported per-step targets; return repair notes and review warnings.

    This is intentionally limited to the explicit ``**** ШАГ ****`` format. It
    checks targets within each source step, never against workout-wide metadata.
    """
    if STEP_MARKER not in source_text or not isinstance(data, dict):
        return [], []
    source_steps = _source_steps(source_text)
    workouts = data.get("workouts")
    if not source_steps or not isinstance(workouts, list):
        return [], []

    generated_steps = [
        step
        for workout in workouts
        if isinstance(workout, dict) and isinstance(workout.get("steps"), list)
        for step in workout["steps"]
        if isinstance(step, dict) and step.get("type") != "repeat"
    ]
    if len(generated_steps) != len(source_steps):
        warning = (
            "Marked-source target check skipped: source has "
            f"{len(source_steps)} step markers but YAML has {len(generated_steps)} non-repeat steps"
        )
        return [], [warning]

    repairs: list[str] = []
    warnings: list[str] = []
    for index, (source_step, generated_step) in enumerate(zip(source_steps, generated_steps)):
        source_intensity = _source_step_intensity(source_step)
        generated_intensity = generated_step.get("intensity")
        if source_intensity is not None:
            if generated_intensity != source_intensity:
                generated_step["intensity"] = source_intensity
                repairs.append(
                    f"step {index + 1}: mapped explicit source type to intensity={source_intensity}"
                )
        elif generated_intensity is not None:
            generated_step.pop("intensity", None)
            repairs.append(
                f"step {index + 1}: removed intensity not represented by an explicit Garmin enum"
            )
            warnings.append(
                f"Step {index + 1}: intensity was not an explicit supported value and was omitted"
            )

        expected_kind, expected_value, has_incomplete_target = _expected_step_target(source_step)
        actual_kind, actual_value = _generated_step_target(generated_step)
        measure_kind, measure_value = _source_step_measure(source_step)

        if measure_kind is None:
            if "СБУ" in " ".join(source_step).upper() and generated_step.get("type") == "sbu_block":
                continue
            previous = str(generated_step.get("type", ""))
            _remove_target_and_make_open(generated_step)
            generated_step.pop("km", None)
            generated_step.pop("seconds", None)
            generated_step["type"] = "open_step"
            if previous != "open_step" or actual_kind is not None:
                repairs.append(f"step {index + 1}: converted {previous} to open_step; source has no distance or duration")
            warnings.append(f"Step {index + 1}: source does not specify distance or duration; Garmin step needs user input")
            continue

        value_key = "km" if measure_kind == "km" else "seconds"
        other_key = "seconds" if measure_kind == "km" else "km"
        actual_measure = generated_step.get(value_key)
        close_enough = (
            isinstance(actual_measure, (int, float))
            and abs(float(actual_measure) - float(measure_value)) <= (0.001 if measure_kind == "km" else 1)
        )
        if not close_enough:
            generated_step[value_key] = measure_value
            generated_step.pop(other_key, None)
            repairs.append(
                f"step {index + 1}: restored {value_key}={measure_value} from the marked source"
            )

        if expected_kind is None:
            _clear_target_fields(generated_step)
            open_type = "dist_open" if measure_kind == "km" else "time_step"
            if generated_step.get("type") != open_type or actual_kind is not None:
                previous = str(generated_step.get("type", ""))
                repairs.append(
                    f"step {index + 1}: converted {previous} to {open_type}; source has no complete target"
                )
            generated_step["type"] = open_type
            generated_step[value_key] = measure_value
            generated_step.pop(other_key, None)
            if has_incomplete_target:
                warnings.append(
                    f"Step {index + 1}: source target is incomplete; Garmin target omitted instead of guessing"
                )
            elif actual_kind is not None:
                warnings.append(
                    f"Step {index + 1}: removed an unstated {actual_kind} target; add it to the source if needed"
                )
            continue

        if expected_value is None:
            if actual_kind == expected_kind:
                generated_step["type"] = _target_step_type(measure_kind, expected_kind)
                continue
            _clear_target_fields(generated_step)
            generated_step["type"] = "dist_open" if measure_kind == "km" else "time_step"
            warnings.append(
                f"Step {index + 1}: source names an HR zone but no complete target range was resolved"
            )
            continue

        expected_values = expected_value
        if expected_kind == "pace" and expected_values[0] == expected_values[1]:
            expected_values = (expected_values[0] - 10, expected_values[1] + 10)
        if not _target_matches(expected_kind, expected_values, actual_kind, actual_value):
            repairs.append(
                f"step {index + 1}: restored explicit {expected_kind} target from the marked source"
            )
            warnings.append(
                f"Step {index + 1}: model target differed from the source; restored the explicit source target"
            )
        _clear_target_fields(generated_step)
        generated_step["type"] = _target_step_type(measure_kind, expected_kind)
        if expected_kind == "hr":
            generated_step["hr_low"], generated_step["hr_high"] = expected_values
        elif expected_kind == "pace":
            fast, slow = expected_values
            generated_step["pace_fast"] = f"{fast // 60}:{fast % 60:02d}"
            generated_step["pace_slow"] = f"{slow // 60}:{slow % 60:02d}"
        else:
            generated_step["cad_low"], generated_step["cad_high"] = expected_values

    # Aggregate summaries are optional metadata. Keep them only when the marked
    # source explicitly supplies a workout-level value.
    explicit_distance: float | None = None
    explicit_duration_min: float | None = None
    in_step = False
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if line == STEP_MARKER:
            in_step = True
            continue
        if line.startswith("****"):
            in_step = False
            continue
        if in_step or not re.match(r"^(?:общая дистанция|общая длительность|итого|total)\b", line, re.IGNORECASE):
            continue
        distance_match = _DISTANCE_VALUE.search(line)
        duration_match = _DURATION_VALUE.search(line)
        if distance_match:
            value = float(distance_match.group("value").replace(",", "."))
            unit = distance_match.group("unit").lower()
            explicit_distance = value if unit in {"км", "km"} else value / 1000
        if duration_match:
            value = float(duration_match.group("value").replace(",", "."))
            unit = duration_match.group("unit").lower()
            explicit_duration_min = value / 60 if unit in {"сек", "секунд", "секунда", "секунды", "s"} else value
            if unit in {"ч", "час", "часа", "часов"}:
                explicit_duration_min = value * 60

    for workout_index, workout in enumerate(workouts):
        if not isinstance(workout, dict):
            continue
        for field, expected in (
            ("distance_km", explicit_distance),
            ("estimated_duration_min", explicit_duration_min),
        ):
            if expected is None:
                if workout.get(field) is not None:
                    workout[field] = None
                    repairs.append(f"workouts[{workout_index}]: cleared unstated summary {field}")
            elif workout.get(field) != expected:
                workout[field] = expected
                repairs.append(f"workouts[{workout_index}]: restored explicit summary {field}={expected}")

    return repairs, warnings
