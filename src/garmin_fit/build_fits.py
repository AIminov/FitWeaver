"""
Build FIT workout files from templates.

Reads workout template Python files, executes them to get workout steps,
and generates FIT files with unique file_id values.
"""

import importlib.util
import logging
import subprocess
import sys

from .config import FITCSV_JAR, LOGS_DIR, OUTPUT_DIR, TEMPLATES_DIR
from .logging_utils import setup_file_logging as _setup_logging
from .state_manager import fit_timestamp_to_unix_ms, get_next_serial_timestamp, print_state
from .workout_utils import save_workout

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

OUTPUT_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


def setup_file_logging(run_id=None):
    """Setup file logging for build_fits."""
    return _setup_logging(prefix="build_fits", run_id=run_id)


def load_template(template_path):
    """
    Dynamically load a template Python file.

    Args:
        template_path: Path to template .py file

    Returns:
        module: Loaded Python module
    """
    module_name = f"template_{template_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, template_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for template: {template_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_fit_from_template(template_path, serial_number, timestamp):
    """
    Build a FIT file from a template.

    Args:
        template_path: Path to template file
        serial_number: Unique serial number for file_id
        timestamp: Unique timestamp for file_id

    Returns:
        Path: Path to generated FIT file, or None if failed
    """
    try:
        logger.info(f"Processing: {template_path.name}")

        # Load template
        module = load_template(template_path)

        # Get workout info and steps
        info = module.get_workout_info()
        steps = module.get_workout_steps()

        logger.debug(f"  Name: {info['name']}")
        logger.debug(f"  Steps: {len(steps)}")

        # Generate output filename
        output_filename = template_path.stem + ".fit"
        output_path = OUTPUT_DIR / output_filename

        # Save FIT file with unique file_id
        save_workout(
            str(output_path),
            info["name"],
            steps,
            serial_number=serial_number,
            time_created_ms=fit_timestamp_to_unix_ms(timestamp)
        )

        logger.info(f"  [OK] Generated: {output_filename}")
        logger.debug(f"    serial={serial_number}, timestamp={timestamp}")

        return output_path

    except Exception as e:
        logger.error(f"  [FAIL] Failed to process {template_path.name}: {e}", exc_info=True)
        return None


def verify_fit_with_csv_tool(fit_path):
    """
    Verify FIT file using FitCSVTool.jar (optional extra validation).

    Args:
        fit_path: Path to FIT file

    Returns:
        bool: True if valid, False otherwise
    """
    if FITCSV_JAR is None:
        logger.debug("FitCSVTool.jar not found, skipping CSV verification")
        return True

    try:
        tmp_csv = fit_path.with_suffix(".csv")

        # Convert FIT to CSV
        result = subprocess.run(
            ["java", "-jar", str(FITCSV_JAR), "-b", str(fit_path), str(tmp_csv)],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            # Clean up CSV
            if tmp_csv.exists():
                tmp_csv.unlink()
            return True
        else:
            logger.warning(f"FitCSVTool validation failed for {fit_path.name}")
            logger.debug(f"STDERR: {result.stderr}")
            return False

    except Exception as e:
        logger.debug(f"CSV verification error: {e}")
        return True  # Don't fail if verification tool has issues


def build_all_fits(verify_with_csv=False):
    """
    Build FIT files from all templates.

    Args:
        verify_with_csv: If True, verify each FIT with FitCSVTool.jar

    Returns:
        tuple: (success_count, total_count)
    """
    logger.info("=" * 70)
    logger.info("BUILDING FIT FILES FROM TEMPLATES")
    logger.info("=" * 70)

    # Find all template files (exclude __init__.py and _-prefixed files)
    templates = sorted(
        f for f in TEMPLATES_DIR.glob("*.py")
        if not f.name.startswith("_")
    )

    if not templates:
        logger.error("No template files found in Workout_templates/")
        logger.info("Run python -m garmin_fit.legacy_cli templates first or create templates manually")
        return 0, 0

    logger.info(f"Found {len(templates)} template(s)")

    # Get unique serial numbers and timestamps
    logger.info("Allocating unique file_id values...")
    serial_timestamp_pairs = get_next_serial_timestamp(len(templates))

    if len(templates) != len(serial_timestamp_pairs):
        logger.error(
            f"Template/serial count mismatch: {len(templates)} templates vs "
            f"{len(serial_timestamp_pairs)} serial pairs"
        )
        return 0, len(templates)

    logger.info(f"Serial number range: {serial_timestamp_pairs[0][0]} - {serial_timestamp_pairs[-1][0]}")
    logger.info("")

    # Build each FIT file
    success_count = 0
    generated_files = []

    for template_path, (serial, timestamp) in zip(templates, serial_timestamp_pairs):
        fit_path = build_fit_from_template(template_path, serial, timestamp)

        if fit_path:
            generated_files.append(fit_path)

            if verify_with_csv:
                if verify_fit_with_csv_tool(fit_path):
                    logger.debug("    CSV verification: OK")
                    success_count += 1
                else:
                    logger.warning("    CSV verification: FAILED")
            else:
                success_count += 1

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"BUILD COMPLETE: {success_count}/{len(templates)} successful")
    logger.info("=" * 70)

    if success_count > 0:
        logger.info(f"\nOutput directory: {OUTPUT_DIR}")
        logger.info(f"Generated {success_count} FIT file(s)")

    return success_count, len(templates)


if __name__ == "__main__":
    run_id = None
    if "--run-id" in sys.argv:
        idx = sys.argv.index("--run-id")
        if idx + 1 < len(sys.argv):
            run_id = sys.argv[idx + 1]
        del sys.argv[idx:idx + 2]

    log_file = setup_file_logging(run_id=run_id)

    try:
        # Check for verification flag
        verify = "--verify" in sys.argv or "--csv" in sys.argv

        if verify:
            logger.info("CSV verification enabled")

        success, total = build_all_fits(verify_with_csv=verify)

        if success == total and total > 0:
            logger.info("\n[OK] All workouts built successfully!")
            print_state()
            sys.exit(0)
        elif success > 0:
            logger.warning(f"\n⚠ {total - success} workout(s) failed")
            sys.exit(1)
        else:
            logger.error("\n[FAIL] Build failed")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\n\nBuild cancelled by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Build error: {e}", exc_info=True)
        sys.exit(1)
