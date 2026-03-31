"""
Generate workout templates from YAML definitions.

Reads a YAML file with workout definitions and generates Python template
files in Workout_templates/ that can be compiled to FIT files.

Usage:
    python -m garmin_fit.generate_from_yaml
    python -m garmin_fit.generate_from_yaml Plan/marathon_workouts.yaml
"""

import logging
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)

from .config import PLAN_DIR, TEMPLATES_DIR
from .logging_utils import setup_file_logging
from .plan_domain import KNOWN_PACE_CONSTANTS, drill_to_data, plan_from_data
from .plan_processing import repair_plan_data, sanitize_workout_name
from .plan_validator import validate_plan_data

logger = logging.getLogger(__name__)


# ============================================================================
# Pace constant names that can be referenced in YAML
# ============================================================================

# Intensity name → Python code mapping
INTENSITY_MAP = {
    "active": "ACT",
    "warmup": "WU",
    "cooldown": "CD",
    "recovery": "REC",
}


# ============================================================================
# Template code generation
# ============================================================================

TEMPLATE = '''"""
Auto-generated workout template.
"""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

{workout_utils_import_line}

WORKOUT_INFO = {workout_info_literal}


def get_workout_info():
    """Return workout metadata."""
    return dict(WORKOUT_INFO)


def get_workout_steps():
    """Return list of workout steps."""
    return [
{steps_code}
    ]


if __name__ == "__main__":
    from garmin_fit.workout_utils import save_workout
    from garmin_fit.config import OUTPUT_DIR

    info = get_workout_info()
    steps = get_workout_steps()

    output_dir = OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)

    filepath = output_dir / "{safe_filename}.fit"
    save_workout(str(filepath), info["name"], steps)
    print(f"Generated: {{filepath}}")
'''


def _format_pace(value):
    """Format a pace value for Python code (constant name or string literal)."""
    if isinstance(value, str) and value in KNOWN_PACE_CONSTANTS:
        return value  # e.g., EASY_F
    return repr(str(value))  # safe literal, e.g. "5:30"


def _format_intensity(value, default="ACT"):
    """Convert intensity name to Python constant."""
    if value is None:
        return default
    return INTENSITY_MAP.get(value, default)


def _step_value(step, field):
    if isinstance(step, dict):
        return step.get(field)
    if field == "type":
        return getattr(step, "step_type")
    return getattr(step, field)


def _workout_value(workout, field, default=None):
    if isinstance(workout, dict):
        value = workout.get(field, default)
    else:
        value = getattr(workout, field, default)
    return default if value is None else value


def _build_yaml_to_fit_index(steps):
    """
    Build a mapping from YAML step index to FIT runtime step index.

    Needed because sbu_block expands into multiple FIT steps at generation time,
    so YAML step indices and FIT step indices diverge when sbu_block is present.

    Args:
        steps: List of YAML step dicts

    Returns:
        dict: {yaml_step_index: fit_start_index}
    """
    from .sbu_block import sbu_block as _sbu_probe

    mapping = {}
    fit_idx = 0
    for yaml_idx, step in enumerate(steps):
        mapping[yaml_idx] = fit_idx
        step_type = _step_value(step, "type")
        if step_type == "sbu_block":
            drills = _step_value(step, "drills")
            if drills:
                drill_items = [d if isinstance(d, dict) else drill_to_data(d) for d in drills]
                _, fit_idx = _sbu_probe(fit_idx, drills=drill_items)
            else:
                _, fit_idx = _sbu_probe(fit_idx)
        else:
            fit_idx += 1
    return mapping


def generate_step_code(step, idx, yaml_to_fit=None):
    """
    Generate Python code for a single workout step.

    Args:
        step: Dict from YAML step definition
        idx: Step index (FIT runtime index)
        yaml_to_fit: Optional mapping from YAML step index to FIT step index,
                     used to translate back_to_offset in repeat steps when
                     sbu_block expansion shifts FIT indices.

    Returns:
        tuple: (code_string, set_of_imports_needed, next_idx)
    """
    step_type = _step_value(step, "type")
    imports_needed = set()

    if step_type == "dist_pace":
        km = _step_value(step, "km")
        pace_fast = _step_value(step, "pace_fast")
        pace_slow = _step_value(step, "pace_slow")
        pf = _format_pace(pace_fast)
        ps = _format_pace(pace_slow)
        intensity = _step_value(step, "intensity")

        # Collect pace constant imports
        if pace_fast in KNOWN_PACE_CONSTANTS:
            imports_needed.add(pace_fast)
        if pace_slow in KNOWN_PACE_CONSTANTS:
            imports_needed.add(pace_slow)

        imports_needed.add("dist_pace")

        if intensity and intensity != "active":
            int_code = _format_intensity(intensity)
            imports_needed.add(int_code)
            code = f"        dist_pace({idx}, {km}, {pf}, {ps}, {int_code}),"
        else:
            code = f"        dist_pace({idx}, {km}, {pf}, {ps}),"

        return code, imports_needed, idx + 1

    elif step_type == "dist_open":
        km = _step_value(step, "km")
        intensity = _step_value(step, "intensity") or "active"
        int_code = _format_intensity(intensity)
        imports_needed.add("dist_open")
        imports_needed.add(int_code)
        code = f"        dist_open({idx}, {km}, {int_code}),"
        return code, imports_needed, idx + 1

    elif step_type == "time_step":
        seconds = _step_value(step, "seconds")
        intensity = _step_value(step, "intensity") or "recovery"
        int_code = _format_intensity(intensity, "REC")
        imports_needed.add("time_step")
        imports_needed.add(int_code)
        code = f"        time_step({idx}, {seconds}, {int_code}),"
        return code, imports_needed, idx + 1

    elif step_type == "time_pace":
        seconds = _step_value(step, "seconds")
        pace_fast = _step_value(step, "pace_fast")
        pace_slow = _step_value(step, "pace_slow")
        pf = _format_pace(pace_fast)
        ps = _format_pace(pace_slow)
        intensity = _step_value(step, "intensity")

        if pace_fast in KNOWN_PACE_CONSTANTS:
            imports_needed.add(pace_fast)
        if pace_slow in KNOWN_PACE_CONSTANTS:
            imports_needed.add(pace_slow)

        imports_needed.add("time_pace")

        if intensity and intensity != "active":
            int_code = _format_intensity(intensity)
            imports_needed.add(int_code)
            code = f"        time_pace({idx}, {seconds}, {pf}, {ps}, {int_code}),"
        else:
            code = f"        time_pace({idx}, {seconds}, {pf}, {ps}),"

        return code, imports_needed, idx + 1

    elif step_type == "open_step":
        intensity = _step_value(step, "intensity") or "active"
        int_code = _format_intensity(intensity)
        imports_needed.add("open_step")
        if int_code != "ACT":
            imports_needed.add(int_code)
            code = f"        open_step({idx}, {int_code}),"
        else:
            code = f"        open_step({idx}),"
        return code, imports_needed, idx + 1

    elif step_type == "repeat":
        back_to_yaml = _step_value(step, "back_to_offset")
        count = _step_value(step, "count")
        imports_needed.add("repeat_step")
        # Translate YAML step index to FIT runtime index if mapping is available
        if yaml_to_fit is not None and isinstance(back_to_yaml, int) and back_to_yaml in yaml_to_fit:
            back_to_fit = yaml_to_fit[back_to_yaml]
        else:
            back_to_fit = back_to_yaml
        code = f"        repeat_step({idx}, {back_to_fit}, {count}),"
        return code, imports_needed, idx + 1

    elif step_type == "dist_hr":
        km = _step_value(step, "km")
        hr_low = _step_value(step, "hr_low")
        hr_high = _step_value(step, "hr_high")
        intensity = _step_value(step, "intensity")
        imports_needed.add("dist_hr")

        if intensity and intensity != "active":
            int_code = _format_intensity(intensity)
            imports_needed.add(int_code)
            code = f"        dist_hr({idx}, {km}, {hr_low}, {hr_high}, {int_code}),"
        else:
            code = f"        dist_hr({idx}, {km}, {hr_low}, {hr_high}),"

        return code, imports_needed, idx + 1

    elif step_type == "time_hr":
        seconds = _step_value(step, "seconds")
        hr_low = _step_value(step, "hr_low")
        hr_high = _step_value(step, "hr_high")
        intensity = _step_value(step, "intensity")
        imports_needed.add("time_hr")

        if intensity and intensity != "active":
            int_code = _format_intensity(intensity)
            imports_needed.add(int_code)
            code = f"        time_hr({idx}, {seconds}, {hr_low}, {hr_high}, {int_code}),"
        else:
            code = f"        time_hr({idx}, {seconds}, {hr_low}, {hr_high}),"

        return code, imports_needed, idx + 1

    elif step_type == "sbu_block":
        imports_needed.add("__sbu_block__")
        drills = _step_value(step, "drills")

        from .sbu_block import sbu_block as _sbu_probe

        if drills:
            # Custom drills — serialize as Python literal
            drill_items = [drill if isinstance(drill, dict) else drill_to_data(drill) for drill in drills]
            drills_repr = repr(drill_items)
            code = f"        *sbu_block({idx}, drills={drills_repr})[0],  # custom СБУ"
            _, next_idx = _sbu_probe(idx, drills=drill_items)
        else:
            code = f"        *sbu_block({idx})[0],  # СБУ drills block"
            _, next_idx = _sbu_probe(idx)

        return code, imports_needed, next_idx

    else:
        raise ValueError(f"Unknown step type: {step_type}")


def generate_template(workout):
    """
    Generate a complete Python template file content from a YAML workout definition.

    Args:
        workout: Dict with workout definition from YAML

    Returns:
        tuple: (filename, content)
    """
    raw_filename = _workout_value(workout, "filename")
    filename = sanitize_workout_name(raw_filename)
    name = _workout_value(workout, "name")
    desc = _workout_value(workout, "desc", name)
    type_code = _workout_value(workout, "type_code", "unknown")
    distance_km = _workout_value(workout, "distance_km", 0.0)
    estimated_duration_min = _workout_value(workout, "estimated_duration_min", 0)

    workout_info = {
        "name": str(name),
        "description": str(desc),
        "type": str(type_code),
        "distance_km": distance_km,
        "estimated_duration_min": estimated_duration_min,
    }

    # Generate step code
    all_imports = set()
    step_lines = []
    idx = 0

    steps = _workout_value(workout, "steps", [])
    yaml_to_fit = _build_yaml_to_fit_index(steps)

    for step in steps:
        code, imports_needed, next_idx = generate_step_code(step, idx, yaml_to_fit=yaml_to_fit)
        step_lines.append(code)
        all_imports.update(imports_needed)
        idx = next_idx

    if not step_lines:
        raise ValueError(f"Workout '{name}' has no steps")

    steps_code = "\n".join(step_lines)

    # Build imports string
    # Separate functions and constants
    func_imports = set()
    const_imports = set()
    extra_imports = set()

    for imp in all_imports:
        if imp in KNOWN_PACE_CONSTANTS:
            const_imports.add(imp)
        elif imp in ("WU", "CD", "ACT", "REC"):
            const_imports.add(imp)
        elif imp == "__sbu_block__":
            extra_imports.add("from garmin_fit.sbu_block import sbu_block")
        elif imp == "Intensity":
            const_imports.add("Intensity")
        else:
            func_imports.add(imp)

    # Order imports: functions first, then constants
    import_parts = sorted(func_imports) + sorted(const_imports)
    imports_str = ", ".join(import_parts)
    if imports_str:
        workout_utils_import_line = f"from garmin_fit.workout_utils import {imports_str}"
    else:
        workout_utils_import_line = "# No direct imports from garmin_fit.workout_utils required."

    # Generate template content
    content = TEMPLATE.format(
        workout_utils_import_line=workout_utils_import_line,
        steps_code=steps_code,
        workout_info_literal=repr(workout_info),
        safe_filename=filename,
    )

    # Add extra imports (sbu_block) if needed
    if extra_imports:
        extra_line = "\n".join(extra_imports)
        content = content.replace(
            "def get_workout_info():",
            f"{extra_line}\n\n\ndef get_workout_info():"
        )

    if raw_filename is not None and filename != raw_filename:
        logger.warning(f"Sanitized filename: '{raw_filename}' -> '{filename}'")

    return filename, content


def find_yaml_file():
    """Find the active YAML workout definitions file, prompting user if multiple exist."""
    yaml_files = sorted(PLAN_DIR.glob("*.yaml")) + sorted(PLAN_DIR.glob("*.yml"))
    if not yaml_files:
        raise FileNotFoundError(f"No YAML workout files found in: {PLAN_DIR}")
    if len(yaml_files) == 1:
        return yaml_files[0]

    # Multiple files — ask the user to choose
    yaml_files = sorted(yaml_files, key=lambda p: p.stat().st_mtime, reverse=True)
    print(f"\nНайдено несколько YAML-файлов в {PLAN_DIR}:")
    for i, path in enumerate(yaml_files, 1):
        print(f"  {i}. {path.name}")
    print()
    while True:
        try:
            choice = input(f"Выберите файл (1–{len(yaml_files)}), или Enter для последнего [{yaml_files[0].name}]: ").strip()
            if choice == "":
                return yaml_files[0]
            idx = int(choice) - 1
            if 0 <= idx < len(yaml_files):
                return yaml_files[idx]
            print(f"  Введите число от 1 до {len(yaml_files)}")
        except (ValueError, EOFError):
            return yaml_files[0]


def generate_all_templates(yaml_path=None, *, output_dir=None, cleanup_output=False):
    """
    Generate all workout templates from a YAML file.

    Args:
        yaml_path: Path to YAML file (auto-detected if None)
        output_dir: Target directory for generated templates (defaults to TEMPLATES_DIR)
        cleanup_output: Remove existing `.py` files in output_dir before export

    Returns:
        tuple[int, int]: (generated_count, expected_count)
    """
    if yaml_path is None:
        yaml_path = find_yaml_file()
    else:
        yaml_path = Path(yaml_path)

    if not yaml_path.exists():
        logger.error(f"YAML file not found: {yaml_path}")
        return 0, 0

    logger.info(f"Reading workout definitions from: {yaml_path.name}")

    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if data is None:
        logger.error("YAML file is empty")
        return 0, 0

    data, repairs = repair_plan_data(data)
    for repair in repairs:
        logger.info(f"[REPAIR] {repair}")

    errors, warnings = validate_plan_data(data, enforce_filename_name_match=True)
    for warning in warnings:
        logger.warning(f"[WARN] {warning}")
    if errors:
        for error in errors:
            logger.error(f"[ERROR] {error}")
        logger.error("YAML validation failed. Templates were not generated.")
        return 0, 0

    plan = plan_from_data(data)
    workouts = plan.workouts
    if not workouts:
        logger.error("No workouts found in YAML file")
        return 0, 0

    total_workouts = len(workouts)
    logger.info(f"Found {total_workouts} workout definitions")

    target_dir = Path(output_dir) if output_dir is not None else TEMPLATES_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    if cleanup_output:
        for existing in target_dir.glob("*.py"):
            existing.unlink(missing_ok=True)

    success = 0
    templates_root = target_dir.resolve()
    for workout in workouts:
        try:
            filename, content = generate_template(workout)
            output_path = (target_dir / f"{filename}.py").resolve()
            if output_path.parent != templates_root:
                raise ValueError(f"Unsafe template path detected: {output_path}")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"  [OK] {filename}.py")
            success += 1
        except Exception as e:
            logger.error(f"  [FAIL] {_workout_value(workout, 'filename', '?')}: {e}")

    logger.info("")
    logger.info(f"Generated {success}/{total_workouts} templates in {target_dir}")
    return success, total_workouts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_id = None
    if "--run-id" in sys.argv:
        idx = sys.argv.index("--run-id")
        if idx + 1 < len(sys.argv):
            run_id = sys.argv[idx + 1]
        del sys.argv[idx:idx + 2]

    setup_file_logging(prefix="generate_from_yaml", run_id=run_id)

    yaml_path = None
    if len(sys.argv) > 1:
        yaml_path = sys.argv[1]

    try:
        generated, total = generate_all_templates(yaml_path)
        if total > 0 and generated == total:
            logger.info("\nNext step: python get_fit.py --build-only")
            sys.exit(0)
        else:
            sys.exit(1)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)
