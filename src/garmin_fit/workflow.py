"""
Workflow orchestration for Garmin FIT generation.

This module contains business workflow logic separate from CLI parsing.
"""

import logging
import subprocess
import sys
import tempfile
from importlib.util import find_spec
from pathlib import Path
from time import perf_counter

from .compare_build_modes import compare_build_modes
from .config import OUTPUT_DIR, PLAN_DIR, ROOT, TEMPLATES_DIR
from .logging_utils import setup_file_logging as _setup_file_logging
from .orchestrator import run_generation_pipeline, select_active_yaml

logger = logging.getLogger(__name__)


def setup_file_logging(run_id=None):
    """Setup file logging for the main get_fit workflow."""
    return _setup_file_logging(prefix="get_fit", run_id=run_id)


def print_header(title):
    print("")
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)
    print("")


def run_step(step_name, script_path=None, args=None, module_name=None, run_id=None):
    """Run one workflow step script and return its code.

    Args:
        step_name: Display name for the step
        script_path: Path to script (fallback if module_name is None)
        args: Optional arguments
        module_name: If set, use 'python -m module_name' invocation
    """
    print_header(f"STEP: {step_name}")
    if module_name:
        cmd = [sys.executable, "-m", module_name]
    else:
        cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)

    run_tag = f"[run_id={run_id}] " if run_id else ""
    logger.info(f"{run_tag}Running: {' '.join(cmd)}")
    logger.info("")

    result = subprocess.run(cmd)
    if result.returncode == 0:
        logger.info("")
        logger.info(f"[OK] {step_name} completed successfully")
    else:
        logger.error("")
        logger.error(f"[FAIL] {step_name} failed with code {result.returncode}")

    return result.returncode


def check_prerequisites():
    """Check that required directories, modules and dependencies exist."""
    print_header("CHECKING PREREQUISITES")
    issues = []

    yaml_plan_files = sorted(PLAN_DIR.glob("*.yaml")) + sorted(PLAN_DIR.glob("*.yml"))
    if yaml_plan_files:
        for plan_file in yaml_plan_files:
            logger.info(f"[OK] YAML training plan found: {plan_file.name}")
    else:
        issues.append(f"No YAML training plan found in {PLAN_DIR} (expected .yaml/.yml)")

    required_modules = [
        "garmin_fit.workout_utils",
        "garmin_fit.state_manager",
        "garmin_fit.build_fits",
        "garmin_fit.check_fit",
    ]
    for module_name in required_modules:
        if find_spec(module_name) is None:
            issues.append(f"Required module missing: {module_name}")
        else:
            logger.info(f"[OK] {module_name} import path found")

    logger.info("")
    logger.info("Checking Python packages...")

    try:
        import fit_tool  # noqa: F401
        logger.info("[OK] fit_tool installed")
    except ImportError:
        issues.append("fit_tool not installed (run: pip install fit_tool)")

    try:
        import garmin_fit_sdk  # noqa: F401
        logger.info("[OK] garmin-fit-sdk installed")
    except ImportError:
        issues.append("garmin-fit-sdk not installed (run: pip install garmin-fit-sdk)")

    if issues:
        logger.error("")
        logger.error("Prerequisites check failed:")
        for issue in issues:
            logger.error(f"  [FAIL] {issue}")
        return False

    logger.info("")
    logger.info("[OK] All prerequisites OK")
    return True


def workflow_doctor(
    *,
    llm_check: bool = False,
    llm_api: str = "openai",
    llm_url: str = "http://127.0.0.1:1234/v1",
    llm_model: str = "qwen/qwen3.5-9b",
    llm_openai_mode: str = "completions",
    llm_timeout_sec: int = 120,
) -> int:
    """Run quick environment diagnostics without building FIT files."""
    print_header("DOCTOR")
    issues = []

    logger.info(f"Python executable: {sys.executable}")
    logger.info(f"Python version: {sys.version.split()[0]}")

    if not check_prerequisites():
        issues.append("prerequisites check failed")

    # TEMP write test (common Windows blocker for tests and pip)
    temp_dir = Path(tempfile.gettempdir())
    logger.info(f"Temp directory: {temp_dir}")
    try:
        probe = temp_dir / ".garmin8_write_probe.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        logger.info("[OK] temp directory is writable")
    except Exception as exc:
        issues.append(f"temp directory is not writable: {exc}")
        logger.error(f"[FAIL] temp directory is not writable: {exc}")

    # Vendored SDK availability check
    local_sdk = ROOT / "sdk" / "py" / "garmin_fit_sdk" / "__init__.py"
    if local_sdk.exists():
        logger.info("[OK] vendored sdk/py package found")
    else:
        issues.append("vendored sdk/py package not found")
        logger.error("[FAIL] vendored sdk/py package not found")

    if llm_check:
        logger.info("")
        logger.info("LLM doctor check:")
        logger.info(
            f"  api={llm_api} url={llm_url} model={llm_model} mode={llm_openai_mode} timeout={llm_timeout_sec}s"
        )
        try:
            from .llm.client import UnifiedLLMClient

            client = UnifiedLLMClient(
                model=llm_model,
                base_url=llm_url,
                api_type=llm_api,
                openai_mode=llm_openai_mode,
                request_timeout_sec=llm_timeout_sec,
            )
            if not client.check_connection():
                raise RuntimeError("connection check failed")

            smoke_input = "Легкий кросс\nПульс до 140\n6 км\n"
            started = perf_counter()
            draft = client.generate_yaml_draft(smoke_input, max_retries=1)
            elapsed = perf_counter() - started

            if draft.validation_errors or not draft.yaml_text:
                details = "; ".join(draft.validation_errors[:3]) or "empty YAML"
                raise RuntimeError(details)

            logger.info(f"[OK] LLM smoke generation passed in {elapsed:.1f}s")
        except Exception as exc:
            issues.append(f"LLM doctor check failed: {exc}")
            logger.error(f"[FAIL] LLM doctor check failed: {exc}")

    if issues:
        logger.error("")
        logger.error("Doctor found issues:")
        for issue in issues:
            logger.error(f"  - {issue}")
        return 1

    logger.info("")
    logger.info("[OK] Doctor checks passed")
    return 0


def count_workspace_template_exports():
    return len(list(TEMPLATES_DIR.glob("*.py")))


def check_outputs():
    if not OUTPUT_DIR.exists():
        return 0
    return len(list(OUTPUT_DIR.glob("*.fit")))


def workflow_full(validate_strict=False, run_id=None, plan_path=None):
    print_header("GARMIN FIT WORKOUT GENERATOR")
    print("Complete workflow: YAML -> direct FIT build -> validation")
    print("")

    if not check_prerequisites():
        return 1

    try:
        if plan_path:
            yaml_path = Path(plan_path)
            if not yaml_path.exists():
                logger.error(f"YAML plan not found: {yaml_path}")
                return 1
        else:
            yaml_path = select_active_yaml(prefer_latest=True, interactive=True)
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    logger.info(f"Using YAML plan: {yaml_path.name}")
    logger.info(f"Validation mode: {'strict' if validate_strict else 'soft'}")
    logger.info("")
    logger.info("Pipeline steps:")
    logger.info("  1) Validate YAML (SDK rules)")
    logger.info("  2) Build FIT files (direct builder)")
    logger.info("  3) Validate FIT files")
    logger.info("  4) Auto-archive on success")
    logger.info("")
    result = run_generation_pipeline(
        yaml_path,
        validate_strict=validate_strict,
        cleanup_first=True,
        auto_archive=True,
        run_id=run_id,
    )

    if not result["success"]:
        logger.error("Workflow failed:")
        for err in result["errors"]:
            logger.error(f"  - {err}")
        return 1

    print_header("WORKFLOW SUMMARY")
    workout_count = result["build_total_count"]
    output_count = len(result["fit_files"])

    logger.info(f"Build path: {result.get('build_mode', 'direct')}")
    logger.info(f"Planned workouts: {workout_count}")
    logger.info(f"Generated FIT files: {output_count}")
    if result.get("repaired_yaml_path"):
        logger.info(f"Repaired YAML: {result['repaired_yaml_path']}")
    if result.get("build_report_path"):
        logger.info(f"Build report: {result['build_report_path']}")

    if workout_count == output_count and output_count > 0:
        logger.info("")
        logger.info("SUCCESS! All workouts generated.")
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Copy FIT files from Output_fit/ to your Garmin watch:")
        logger.info("   GARMIN/NewFiles/")
        logger.info("2. Unplug watch and wait 1-2 minutes for import")
        logger.info("3. Check: Run -> Training -> Workouts")
        logger.info("")
        if result.get("archive_path"):
            logger.info(f"[OK] Auto-archive completed: {result['archive_path']}")
        return 0
    elif output_count > 0:
        logger.warning("")
        logger.warning(f"WARNING: Generated {output_count}/{workout_count} workouts")
        logger.warning("Some workouts may have failed. Check logs.")
        return 1
    else:
        logger.error("")
        logger.error("ERROR: No FIT files generated")
        return 1


def workflow_compare_build_modes(validate_strict=False, run_id=None, plan_path=None):
    print_header("COMPARE DIRECT VS LEGACY BUILD")
    print("Diagnostic workflow: YAML -> direct FIT vs templates FIT")
    print("")

    if not check_prerequisites():
        return 1

    try:
        if plan_path:
            yaml_path = Path(plan_path)
            if not yaml_path.exists():
                logger.error(f"YAML plan not found: {yaml_path}")
                return 1
        else:
            yaml_path = select_active_yaml(prefer_latest=True, interactive=True)
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    logger.info(f"Using YAML plan: {yaml_path.name}")
    logger.info(f"Validation mode: {'strict' if validate_strict else 'soft'}")
    result = compare_build_modes(
        yaml_path,
        validate_strict=validate_strict,
        run_id=run_id,
    )

    print_header("COMPARE SUMMARY")
    logger.info(f"Compare report: {result['compare_report_path']}")
    logger.info(
        "Direct build: "
        f"{result['direct']['built_count']}/{result['direct']['build_total_count']} built, "
        f"{result['direct']['valid_count']}/{result['direct']['total_count']} valid"
    )
    logger.info(
        "Legacy templates build: "
        f"{result['templates']['built_count']}/{result['templates']['build_total_count']} built, "
        f"{result['templates']['valid_count']}/{result['templates']['total_count']} valid, "
        f"{result['templates']['template_export_count']} template export(s)"
    )

    if result["matches"]:
        logger.info("")
        logger.info("[OK] Direct and legacy build outputs match")
        return 0

    logger.error("")
    logger.error("Comparison found mismatches:")
    for mismatch in result["mismatches"]:
        if mismatch["type"] == "fit_content_mismatch":
            logger.error(f"  - fit content mismatch: {mismatch['fit_file']}")
        elif mismatch["type"] == "count_mismatch":
            logger.error(
                "  - "
                f"{mismatch['field']}: direct={mismatch['direct']} "
                f"templates={mismatch['templates']}"
            )
        elif mismatch["type"] == "fit_file_set_mismatch":
            logger.error(
                "  - fit file set mismatch: "
                f"direct_only={mismatch['direct_only']} "
                f"templates_only={mismatch['templates_only']}"
            )
        elif mismatch["type"] == "mode_failure":
            logger.error(f"  - {mismatch['mode']} failed: {mismatch['errors']}")
        else:
            logger.error(f"  - {mismatch}")
    return 1


def workflow_validate_only(validate_strict=False, run_id=None):
    print_header("VALIDATE FIT FILES")
    output_count = check_outputs()
    if output_count == 0:
        logger.error("No FIT files found in Output_fit/")
        logger.info("Run without --validate-only to generate files first")
        return 1
    validate_args = ["--strict", str(OUTPUT_DIR)] if validate_strict else [str(OUTPUT_DIR)]
    return run_step("Validate FIT Files", module_name="garmin_fit.check_fit", args=validate_args, run_id=run_id)


def workflow_build_only(validate_strict=False, run_id=None):
    print_header("LEGACY BUILD FROM TEMPLATE EXPORTS")
    template_export_count = count_workspace_template_exports()
    if template_export_count == 0:
        logger.error("No template exports found in Workout_templates/. Run --templates-only first.")
        return 1

    logger.info(f"Found {template_export_count} template export(s)")
    build_args = ["--run-id", run_id] if run_id else None
    ret = run_step("Legacy Build FIT Files", module_name="garmin_fit.build_fits", args=build_args, run_id=run_id)
    if ret == 0:
        validate_args = ["--strict", str(OUTPUT_DIR)] if validate_strict else [str(OUTPUT_DIR)]
        validate_ret = run_step("Validate FIT Files", module_name="garmin_fit.check_fit", args=validate_args, run_id=run_id)
        if validate_ret != 0:
            return validate_ret
    return ret


def workflow_templates_only(run_id=None, plan_path=None):
    print_header("EXPORT DEBUG TEMPLATES")
    template_args = []
    if run_id:
        template_args.extend(["--run-id", run_id])
    if plan_path:
        yaml_path = Path(plan_path)
        if not yaml_path.exists():
            logger.error(f"YAML plan not found: {yaml_path}")
            return 1
        template_args.append(str(yaml_path))
    if not template_args:
        template_args = None
    return run_step("Export Debug Templates", module_name="garmin_fit.generate_from_yaml", args=template_args, run_id=run_id)


def workflow_archive(run_id=None):
    print_header("ARCHIVE CURRENT PLAN")
    template_export_count = count_workspace_template_exports()
    output_count = check_outputs()
    plan_count = len(sorted(PLAN_DIR.glob("*.yaml")) + sorted(PLAN_DIR.glob("*.yml")) + sorted(PLAN_DIR.glob("*.md")))

    if template_export_count == 0 and output_count == 0 and plan_count == 0:
        logger.error("Nothing to archive (no plans, debug template exports, or FIT files)")
        return 1

    logger.info("Will archive:")
    logger.info(f"  - {plan_count} plan file(s)")
    logger.info(f"  - {template_export_count} workspace debug template export(s)")
    logger.info(f"  - {output_count} FIT files")
    if template_export_count == 0 and plan_count > 0:
        logger.info("  - debug template exports will be derived from YAML if possible")
    logger.info("")

    confirm = input("Continue with archiving? (yes/no): ")
    if confirm.lower() != "yes":
        logger.info("Archive cancelled")
        return 0

    archive_args = ["archive"]
    if run_id:
        archive_args.extend(["--run-id", run_id])
    ret = run_step("Archive Plan", module_name="garmin_fit.archive_manager", args=archive_args, run_id=run_id)
    if ret == 0:
        logger.info("")
        logger.info("[OK] Plan archived successfully")
        logger.info("  Output_fit/ is now clean")
        logger.info("  Workout_templates/ is clean if workspace debug exports existed")
        logger.info("  Plan moved to Plan/plan_done/")
        logger.info("  Archive saved to Archive/")
    return ret


def workflow_list_archives():
    print_header("AVAILABLE ARCHIVES")
    return run_step("List Archives", module_name="garmin_fit.archive_manager", args=["list"])


def workflow_restore(archive_name):
    print_header(f"RESTORE FROM ARCHIVE: {archive_name}")
    logger.info(f"Will restore debug template exports and FIT files from: {archive_name}")
    logger.info("")

    confirm = input("This will overwrite current template exports/FIT files. Continue? (yes/no): ")
    if confirm.lower() != "yes":
        logger.info("Restore cancelled")
        return 0

    ret = run_step("Restore from Archive", module_name="garmin_fit.archive_manager", args=["restore", archive_name])
    if ret == 0:
        logger.info("")
        logger.info("[OK] Restored successfully")
        logger.info(f"  Debug template exports and FIT files restored from: {archive_name}")
    return ret


def workflow_garmin_calendar(
    plan_path=None,
    email=None,
    password=None,
    token_dir=None,
    year=None,
    schedule=True,
    dry_run=False,
):
    """
    Upload a YAML workout plan to Garmin Connect Calendar.

    Authentication falls back to GARMIN_EMAIL / GARMIN_PASSWORD env vars.
    In dry-run mode payloads are built and logged but no API calls are made.
    """
    print_header("GARMIN CONNECT CALENDAR UPLOAD")

    # ------------------------------------------------------------------ deps
    from .garmin_auth_manager import is_available as _garmin_auth_available

    if not _garmin_auth_available():
        print("[FAIL] garmin-auth / garminconnect not installed.")
        print("  Run:  pip install garminconnect garmin-auth")
        return 1

    # ------------------------------------------------------------------ YAML
    try:
        if plan_path:
            yaml_path = Path(plan_path).resolve()
            if not yaml_path.exists():
                print(f"[FAIL] YAML plan not found: {yaml_path}")
                return 1
        else:
            yaml_path = select_active_yaml(prefer_latest=True, interactive=True)
    except FileNotFoundError as e:
        print(f"[FAIL] {e}")
        return 1

    print(f"Plan:         {yaml_path.name}")
    print(f"Schedule:     {schedule}")
    print(f"Year:         {year or 'auto'}")
    print(f"Dry run:      {dry_run}")
    print("")

    import yaml as _yaml

    try:
        plan_data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[FAIL] Failed to read YAML: {exc}")
        return 1

    from .plan_domain import plan_from_data

    plan = plan_from_data(plan_data)
    print(f"Workouts:     {len(plan.workouts)}")

    if not plan.workouts:
        print("[FAIL] No workouts found in plan")
        return 1

    # ------------------------------------------------------------------ auth
    if not dry_run:
        from .garmin_auth_manager import GarminAuthManager

        print("Authenticating with Garmin Connect...")
        try:
            manager = GarminAuthManager(
                email=email,
                password=password,
                token_dir=Path(token_dir) if token_dir else None,
                prompt_mfa=lambda: input("Garmin MFA code: "),
            )
            client = manager.connect()
            if client == "needs_mfa":
                print("[FAIL] MFA required but could not be completed interactively.")
                return 1
        except Exception as exc:
            print(f"[FAIL] Authentication failed: {exc}")
            return 1
        print("[OK] Authenticated")
    else:
        client = None

    # ------------------------------------------------------------------ upload
    from .garmin_calendar_export import GarminCalendarExporter

    exporter = GarminCalendarExporter(client) if client else GarminCalendarExporter.__new__(GarminCalendarExporter)
    if client is None:
        exporter._client = None
        exporter._delay = 1.2

    result = exporter.upload_plan(plan, schedule=schedule, dry_run=dry_run, year=year)

    # ------------------------------------------------------------------ summary
    print_header("UPLOAD SUMMARY")
    print(result.summary())

    if result.failed:
        print(f"[FAIL] {result.failed} workout(s) failed:")
        for r in result.results:
            if not r.ok:
                print(f"  - {r.filename}: {r.error}")
        return 1

    if not dry_run:
        print("[OK] All workouts uploaded to Garmin Connect Calendar")
        print("Sync your watch to see the scheduled workouts.")
    return 0


def workflow_validate_yaml(plan_path=None):
    """Validate YAML plan by SDK rules.

    Args:
        plan_path: Optional path to specific YAML plan file

    Returns:
        Exit code (0 = success, 1 = validation errors)
    """
    from .plan_validator import group_issues_by_category, parse_and_validate_yaml_text_detailed

    print_header("YAML VALIDATION (SDK RULES)")

    # Select YAML file
    if plan_path:
        yaml_file = Path(plan_path).resolve()
    else:
        yaml_file = select_active_yaml(interactive=True)

    if not yaml_file:
        logger.error("No YAML plan found")
        return 1

    if not yaml_file.exists():
        logger.error(f"YAML file not found: {yaml_file}")
        return 1

    logger.info(f"Validating: {yaml_file.relative_to(ROOT)}")

    # Read YAML
    try:
        with open(yaml_file, 'r', encoding='utf-8') as f:
            yaml_content = f.read()
    except Exception as e:
        logger.error(f"Failed to read YAML file: {e}")
        return 1

    logger.info(f"File size: {len(yaml_content)} bytes")
    logger.info("")

    # Validate
    data, errors, warnings = parse_and_validate_yaml_text_detailed(
        yaml_content,
        enforce_filename_name_match=True
    )

    # Check parsing result
    if data is None:
        logger.error("YAML parsing FAILED")
        if errors:
            logger.error("Parse errors:")
            for issue in errors:
                logger.error(f"  - {issue.message}")
        return 1

    logger.info("[OK] YAML parsing successful")
    workouts = data.get('workouts', [])
    logger.info(f"Found {len(workouts)} workouts")
    logger.info("")

    # Report errors
    has_errors = False
    if errors:
        logger.error("=" * 70)
        logger.error("VALIDATION ERRORS")
        logger.error("=" * 70)
        error_groups = group_issues_by_category(errors)
        for category, messages in sorted(error_groups.items()):
            logger.error(f"[{category}] - {len(messages)} issue(s)")
            for msg in messages[:5]:
                logger.error(f"  - {msg}")
            if len(messages) > 5:
                logger.error(f"  ... and {len(messages) - 5} more")
        logger.error("")
        has_errors = True
    else:
        logger.info("[OK] NO ERRORS found")
        logger.info("")

    # Report warnings
    if warnings:
        logger.warning("=" * 70)
        logger.warning("VALIDATION WARNINGS")
        logger.warning("=" * 70)
        warning_groups = group_issues_by_category(warnings)
        for category, messages in sorted(warning_groups.items()):
            logger.warning(f"[{category}] - {len(messages)} warning(s)")
            for msg in messages[:5]:
                logger.warning(f"  - {msg}")
            if len(messages) > 5:
                logger.warning(f"  ... and {len(messages) - 5} more")
        logger.warning("")
    else:
        logger.info("[OK] NO WARNINGS found")
        logger.info("")

    # Summary
    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total errors:   {len(errors)}")
    logger.info(f"Total warnings: {len(warnings)}")
    logger.info("")

    if has_errors:
        logger.error("[FAILED] YAML validation errors found. Please fix them.")
        return 1
    else:
        logger.info("[SUCCESS] YAML is VALID and ready to use!")
        logger.info("You can now run: python -m garmin_fit.cli run")
        return 0
