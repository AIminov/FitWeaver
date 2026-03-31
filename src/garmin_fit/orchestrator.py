"""
Shared pipeline orchestrator for CLI and Telegram bot.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .archive_manager import archive_current_plan
from .build_fits import build_all_fits
from .build_from_plan import build_all_fits_from_plan
from .check_fit import validate_directory
from .config import OUTPUT_DIR, PLAN_DIR, TEMPLATES_DIR
from .generate_from_yaml import generate_all_templates
from .plan_artifacts import prepare_plan_artifacts, write_build_report

logger = logging.getLogger(__name__)


def select_active_yaml(prefer_latest: bool = True, interactive: bool = False) -> Path:
    """Select active YAML plan from Plan/ directory.

    If multiple files exist and interactive=True, prompts the user to choose.
    Otherwise falls back to the most recently modified file.
    """
    yaml_files = sorted(list(PLAN_DIR.glob("*.yaml")) + list(PLAN_DIR.glob("*.yml")))
    if not yaml_files:
        raise FileNotFoundError(f"No YAML plan found in {PLAN_DIR}")
    if len(yaml_files) == 1:
        return yaml_files[0]

    yaml_files = sorted(yaml_files, key=lambda p: p.stat().st_mtime, reverse=True)

    if not interactive:
        logger.warning(f"Multiple YAML files in Plan/; using latest: {yaml_files[0].name}")
        return yaml_files[0]

    print(f"\nНайдено несколько YAML-файлов в {PLAN_DIR}:")
    for i, path in enumerate(yaml_files, 1):
        print(f"  {i}. {path.name}")
    print()
    while True:
        try:
            choice = input(
                f"Выберите план (1–{len(yaml_files)}), или Enter для последнего [{yaml_files[0].name}]: "
            ).strip()
            if choice == "":
                return yaml_files[0]
            idx = int(choice) - 1
            if 0 <= idx < len(yaml_files):
                return yaml_files[idx]
            print(f"  Введите число от 1 до {len(yaml_files)}")
        except (ValueError, EOFError):
            return yaml_files[0]


def cleanup_runtime_dirs() -> None:
    """Remove FIT outputs and optional debug template exports before a clean run."""
    for file in TEMPLATES_DIR.glob("*.py"):
        file.unlink(missing_ok=True)
    pycache = TEMPLATES_DIR / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)
    for file in OUTPUT_DIR.glob("*.fit"):
        file.unlink(missing_ok=True)


def run_generation_pipeline(
    yaml_path: Path,
    *,
    validate_strict: bool = False,
    cleanup_first: bool = True,
    auto_archive: bool = False,
    archive_owner_tag: Optional[int] = None,
    run_id: Optional[str] = None,
    build_mode: str = "direct",
) -> Dict:
    """
    Run the shared YAML pipeline with direct build by default.

    Returns dict with:
      - success: bool
      - build_mode: str
      - template_export_count: int
      - template_export_total_count: int
      - built_count: int
      - build_total_count: int
      - valid_count: int
      - total_count: int
      - fit_files: List[Path]
      - errors: List[str]
      - archive_path: Optional[Path]
    """
    errors: List[str] = []
    archive_path: Optional[Path] = None
    prepared_artifacts = None
    started_at = datetime.now(timezone.utc)

    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return {
            "success": False,
            "build_mode": build_mode,
            "template_export_count": 0,
            "template_export_total_count": 0,
            "built_count": 0,
            "build_total_count": 0,
            "valid_count": 0,
            "total_count": 0,
            "fit_files": [],
            "artifact_paths": [],
            "repaired_yaml_path": None,
            "build_report_path": None,
            "errors": [f"YAML file not found: {yaml_path}"],
            "archive_path": None,
        }

    if build_mode not in {"direct", "templates"}:
        raise ValueError(f"Unsupported build mode: {build_mode}")

    if cleanup_first:
        cleanup_runtime_dirs()

    prepared_artifacts = prepare_plan_artifacts(yaml_path)

    if build_mode == "templates":
        templates_count, templates_total_count = generate_all_templates(yaml_path)
        if templates_total_count == 0:
            errors.append("Debug template export produced 0 files")
        elif templates_count != templates_total_count:
            errors.append(f"Debug template export incomplete: {templates_count}/{templates_total_count}")

        built_count, build_total_count = build_all_fits()
        if build_total_count == 0:
            errors.append("No template exports available for legacy build")
        elif built_count != build_total_count:
            errors.append(f"Legacy build incomplete: {built_count}/{build_total_count}")
    else:
        templates_count = 0
        templates_total_count = 0
        direct_build_error = None
        try:
            built_count, build_total_count = build_all_fits_from_plan(yaml_path)
        except Exception as exc:
            built_count, build_total_count = 0, 0
            direct_build_error = str(exc)
            errors.append(f"Direct build failed: {exc}")
        if build_total_count == 0 and direct_build_error is None:
            errors.append("No workouts found in YAML for direct build")
        elif built_count != build_total_count:
            errors.append(f"Direct build incomplete: {built_count}/{build_total_count}")

    valid_count, validate_total_count = validate_directory(OUTPUT_DIR, strict=validate_strict)
    if validate_total_count == 0:
        errors.append("Validation found 0 FIT files")
    elif valid_count != validate_total_count:
        errors.append(f"Validation failed: {valid_count}/{validate_total_count}")

    fit_files = sorted(OUTPUT_DIR.glob("*.fit"))
    success = len(errors) == 0
    finished_at = datetime.now(timezone.utc)

    build_report_path = write_build_report(
        prepared_artifacts,
        build_mode=build_mode,
        validate_strict=validate_strict,
        run_id=run_id,
        success=success,
        built_count=built_count,
        build_total_count=build_total_count,
        valid_count=valid_count,
        total_count=validate_total_count,
        fit_files=fit_files,
        errors=errors,
        template_export_count=templates_count,
        template_export_total_count=templates_total_count,
        archive_path=None,
        started_at=started_at,
        finished_at=finished_at,
    )
    artifact_paths = prepared_artifacts.existing_paths()

    if success and auto_archive:
        try:
            archive_path = archive_current_plan(
                run_id=run_id,
                owner_tag=archive_owner_tag,
                plan_paths=[yaml_path],
                artifact_paths=artifact_paths,
            )
        except Exception as exc:
            success = False
            errors.append(f"Auto-archive failed: {exc}")
        finally:
            finished_at = datetime.now(timezone.utc)
            build_report_path = write_build_report(
                prepared_artifacts,
                build_mode=build_mode,
                validate_strict=validate_strict,
                run_id=run_id,
                success=success,
                built_count=built_count,
                build_total_count=build_total_count,
                valid_count=valid_count,
                total_count=validate_total_count,
                fit_files=fit_files,
                errors=errors,
                template_export_count=templates_count,
                template_export_total_count=templates_total_count,
                archive_path=archive_path,
                started_at=started_at,
                finished_at=finished_at,
            )
            if archive_path is not None:
                archived_report_path = archive_path / "artifacts" / build_report_path.name
                if archived_report_path.exists():
                    shutil.copy2(build_report_path, archived_report_path)

    return {
        "success": success,
        "build_mode": build_mode,
        "template_export_count": templates_count,
        "template_export_total_count": templates_total_count,
        "built_count": built_count,
        "build_total_count": build_total_count,
        "valid_count": valid_count,
        "total_count": validate_total_count,
        "fit_files": fit_files,
        "artifact_paths": artifact_paths,
        "repaired_yaml_path": prepared_artifacts.repaired_yaml_path,
        "build_report_path": build_report_path,
        "errors": errors,
        "archive_path": archive_path,
    }
