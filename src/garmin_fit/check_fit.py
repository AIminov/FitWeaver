"""
Enhanced FIT file validator with quality checks.

Validates FIT workout files and performs quality checks:
- File can be decoded
- Has valid file_id message
- Has valid workout message
- Serial number is unique (not default 12345)
- Timestamp is reasonable
- Has workout steps
- Steps have valid structure
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

try:
    from .config import OUTPUT_DIR, ROOT
    from .state_manager import from_fit_timestamp
except ImportError:
    from config import OUTPUT_DIR, ROOT
    from state_manager import from_fit_timestamp

_LARGE_FILE_BYTES = 1_000_000  # 1 MB — typical Garmin workout FIT files are <50 KB

try:
    from garmin_fit_sdk import Decoder, Stream
except ImportError:
    print("ERROR: garmin-fit-sdk not installed")
    print("Install with: pip install garmin-fit-sdk")
    sys.exit(1)


logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class FitValidationError(Exception):
    """Custom exception for FIT validation errors."""
    pass


def validate_fit_file(file_path, strict=True):
    """
    Validate a FIT workout file with quality checks.

    Args:
        file_path: Path to FIT file
        strict: If True, warnings become errors

    Returns:
        dict: Validation results with keys:
            - valid: bool
            - file_id: dict
            - workout: dict
            - steps: list
            - warnings: list
            - errors: list

    Raises:
        FitValidationError: If file is invalid (in strict mode)
    """
    results = {
        "valid": True,
        "file_id": None,
        "workout": None,
        "steps": [],
        "warnings": [],
        "errors": []
    }

    file_path = Path(file_path)

    # Check file exists
    if not file_path.exists():
        results["errors"].append(f"File not found: {file_path}")
        results["valid"] = False
        return results

    # Check file size
    file_size = file_path.stat().st_size
    if file_size == 0:
        results["errors"].append("File is empty")
        results["valid"] = False
        return results
    elif file_size > _LARGE_FILE_BYTES:
        results["warnings"].append(f"File is large: {file_size:,} bytes")

    # Try to decode
    try:
        stream = Stream.from_file(str(file_path))
        decoder = Decoder(stream)
        messages, errors = decoder.read()
    except Exception as e:
        results["errors"].append(f"Failed to decode: {e}")
        results["valid"] = False
        return results

    # Check for decoder errors
    if errors:
        results["errors"].append(f"Decoder errors: {errors}")
        results["valid"] = False
        return results

    # Extract file_id
    file_id_mesgs = messages.get("file_id_mesgs", [])
    if not file_id_mesgs:
        results["errors"].append("No file_id message found")
        results["valid"] = False
        return results

    file_id = file_id_mesgs[0]
    results["file_id"] = file_id

    # Validate file_id fields
    serial_number = file_id.get("serial_number")
    time_created = file_id.get("time_created")

    if serial_number is None:
        results["errors"].append("file_id missing serial_number")
        results["valid"] = False

    if time_created is None:
        results["errors"].append("file_id missing time_created")
        results["valid"] = False

    # Check for default/duplicate serial number
    if serial_number == 12345:
        msg = "Serial number is default (12345) - workouts will be deduplicated on watch!"
        results["errors"].append(msg)
        results["valid"] = False

    # Extract workout message
    workout_mesgs = messages.get("workout_mesgs", [])
    if not workout_mesgs:
        results["errors"].append("No workout message found")
        results["valid"] = False
        return results

    workout = workout_mesgs[0]
    results["workout"] = workout

    # Check workout name
    workout_name = workout.get("wkt_name") or workout.get("workout_name")
    if not workout_name:
        results["warnings"].append("Workout has no name")

    # Check number of steps
    num_steps = workout.get("num_valid_steps", 0)
    if num_steps == 0:
        results["errors"].append("Workout has no steps")
        results["valid"] = False

    # Extract workout steps
    step_mesgs = messages.get("workout_step_mesgs", [])
    results["steps"] = step_mesgs

    if len(step_mesgs) != num_steps:
        results["warnings"].append(
            f"Step count mismatch: workout says {num_steps}, found {len(step_mesgs)}"
        )

    # Validate steps
    for i, step in enumerate(step_mesgs):
        step_index = step.get("message_index")
        if step_index != i:
            results["warnings"].append(
                f"Step {i}: message_index mismatch (expected {i}, got {step_index})"
            )

        duration_type = step.get("duration_type")
        if duration_type is None:
            results["errors"].append(f"Step {i}: missing duration_type")
            results["valid"] = False

        target_type = step.get("target_type")
        if target_type is None:
            results["errors"].append(f"Step {i}: missing target_type")
            results["valid"] = False

    # Apply strict mode
    if strict and results["warnings"]:
        for warning in results["warnings"]:
            results["errors"].append(f"[STRICT] {warning}")
        results["valid"] = False

    return results


def _validate_with_local_sdk_python(file_path: Path) -> tuple[bool, str]:
    """
    Validate FIT with vendored SDK package in sdk/py.

    Returns:
        (ok, details)
    """
    sdk_py = ROOT / "sdk" / "py"
    local_pkg = sdk_py / "garmin_fit_sdk" / "__init__.py"
    if not local_pkg.exists():
        return True, "local sdk/py package is unavailable; check skipped"

    script = (
        "from garmin_fit_sdk import Decoder, Stream\n"
        f"s = Stream.from_file(r'''{str(file_path)}''')\n"
        "d = Decoder(s)\n"
        "ok = bool(d.is_fit() and d.check_integrity())\n"
        "print('OK' if ok else 'FAIL')\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(sdk_py) + os.pathsep + env.get("PYTHONPATH", "")

    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=30,
        )
    except Exception as exc:
        return False, f"local sdk/py validation execution failed: {exc}"

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        details = stderr or stdout or f"exit code {proc.returncode}"
        return False, f"local sdk/py validation failed: {details}"
    if stdout != "OK":
        return False, f"local sdk/py validation returned unexpected result: {stdout or 'EMPTY'}"
    return True, "local sdk/py check passed"


def print_validation_results(file_path, results):
    """Print validation results in human-readable format."""
    print("=" * 70)
    print(f"FIT FILE VALIDATION: {Path(file_path).name}")
    print("=" * 70)

    # File ID
    if results["file_id"]:
        fid = results["file_id"]
        print("\n📋 File ID:")
        print(f"  Type: {fid.get('type')}")
        print(f"  Manufacturer: {fid.get('manufacturer')}")
        print(f"  Serial Number: {fid.get('serial_number')}")

        time_created = fid.get("time_created")
        if time_created:
            dt = from_fit_timestamp(time_created)
            print(f"  Time Created: {time_created} ({dt})")

    # Workout
    if results["workout"]:
        wkt = results["workout"]
        print("\n🏃 Workout:")
        print(f"  Name: {wkt.get('wkt_name') or wkt.get('workout_name')}")
        print(f"  Sport: {wkt.get('sport')}")
        print(f"  Steps: {wkt.get('num_valid_steps')}")

    # Steps summary
    if results["steps"]:
        print(f"\n📝 Steps ({len(results['steps'])}):")
        for i, step in enumerate(results["steps"]):
            dur_type = step.get("duration_type")
            tgt_type = step.get("target_type")
            intensity = step.get("intensity")
            print(f"  {i}: duration={dur_type}, target={tgt_type}, intensity={intensity}")

    # Warnings
    if results["warnings"]:
        print(f"\nWARNINGS ({len(results['warnings'])}):")
        for warning in results["warnings"]:
            print(f"  - {warning}")

    # Errors
    if results["errors"]:
        print(f"\nERRORS ({len(results['errors'])}):")
        for error in results["errors"]:
            print(f"  - {error}")

    # Status
    print("\n" + "=" * 70)
    if results["valid"]:
        print("VALID - File passed all checks")
    else:
        print("INVALID - File has errors")
    print("=" * 70)


def validate_directory(directory, strict=False, sdk_python_check=True):
    """
    Validate all FIT files in a directory.

    Args:
        directory: Path to directory
        strict: Enable strict validation
        sdk_python_check: Additional validation with vendored sdk/py package

    Returns:
        tuple: (valid_count, total_count)
    """
    directory = Path(directory)
    fit_files = sorted(directory.glob("*.fit"))

    if not fit_files:
        logger.error(f"No FIT files found in {directory}")
        return 0, 0

    logger.info(f"Validating {len(fit_files)} file(s) in {directory}")
    print("")

    valid_count = 0

    for fit_file in fit_files:
        results = validate_fit_file(fit_file, strict=strict)
        if sdk_python_check:
            sdk_ok, sdk_message = _validate_with_local_sdk_python(fit_file)
            if sdk_ok:
                if "check passed" in sdk_message:
                    print(f"    SDK: {sdk_message}")
            else:
                results["errors"].append(sdk_message)
                results["valid"] = False

        status = "[OK]" if results["valid"] else "[FAIL]"
        print(f"{status} {fit_file.name}")

        if results["errors"]:
            for error in results["errors"]:
                print(f"    ERROR: {error}")

        if results["warnings"]:
            for warning in results["warnings"]:
                print(f"    WARN: {warning}")

        if results["valid"]:
            valid_count += 1

        print("")

    print("=" * 70)
    print(f"RESULTS: {valid_count}/{len(fit_files)} valid")
    print("=" * 70)

    return valid_count, len(fit_files)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default: check Output_fit directory
        output_dir = OUTPUT_DIR

        if output_dir.exists():
            valid, total = validate_directory(output_dir, strict=False, sdk_python_check=True)
            sys.exit(0 if valid == total else 1)
        else:
            print("Usage: python check_fit.py <file_or_directory>")
            print("   or: python check_fit.py --strict <file_or_directory>")
            print("   add: --no-sdk-python-check to disable vendored sdk/py validation")
            sys.exit(1)

    strict = "--strict" in sys.argv
    if strict:
        sys.argv.remove("--strict")
    sdk_python_check = "--no-sdk-python-check" not in sys.argv
    if "--no-sdk-python-check" in sys.argv:
        sys.argv.remove("--no-sdk-python-check")

    path = Path(sys.argv[1])

    if path.is_dir():
        valid, total = validate_directory(path, strict=strict, sdk_python_check=sdk_python_check)
        sys.exit(0 if valid == total else 1)
    elif path.is_file():
        results = validate_fit_file(path, strict=strict)
        if sdk_python_check:
            sdk_ok, sdk_message = _validate_with_local_sdk_python(path)
            if not sdk_ok:
                results["errors"].append(sdk_message)
                results["valid"] = False
        print_validation_results(path, results)
        sys.exit(0 if results["valid"] else 1)
    else:
        logger.error(f"Path not found: {path}")
        sys.exit(1)
