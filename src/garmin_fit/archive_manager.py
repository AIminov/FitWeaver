"""
Archive management for completed training plans.

Moves completed workouts and plans to archive, keeping main directories clean.
"""

import shutil
from datetime import datetime
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

from .config import (
    ARTIFACTS_DIR,
    PLAN_DIR,
    PLAN_DONE_DIR,
    TEMPLATES_DIR,
    OUTPUT_DIR,
    ARCHIVE_DIR,
)
from .generate_from_yaml import generate_all_templates
from .plan_artifacts import get_plan_artifact_paths


def _pick_active_plan_stem():
    """Pick active plan stem, preferring latest YAML, then latest Markdown."""
    yaml_plan_files = sorted(
        list(PLAN_DIR.glob("*.yaml")) + list(PLAN_DIR.glob("*.yml")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    md_plan_files = sorted(PLAN_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

    if yaml_plan_files:
        return yaml_plan_files[0].stem
    if md_plan_files:
        return md_plan_files[0].stem
    return "plan"


def _normalize_tag(value):
    if value is None:
        return None
    normalized = re.sub(r"[^\w.-]+", "_", str(value).strip())
    return normalized.strip("._") or None


def _make_unique_archive_name(base_name):
    """Avoid collisions if multiple archives are created within one second."""
    candidate = base_name
    suffix = 2
    while (ARCHIVE_DIR / candidate).exists():
        candidate = f"{base_name}_v{suffix}"
        suffix += 1
    return candidate


def _make_unique_file_destination(directory: Path, filename: str) -> Path:
    """Return a non-colliding file path in directory."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    version = 2
    while True:
        next_candidate = directory / f"{stem}_v{version}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        version += 1


def _collect_plan_files(plan_paths=None):
    plan_files = []
    if plan_paths:
        for raw_path in plan_paths:
            plan_path = Path(raw_path)
            if plan_path.exists() and plan_path.is_file() and plan_path.suffix.lower() in (".md", ".yaml", ".yml"):
                plan_files.append(plan_path)
        # Also collect sibling .md files for any yaml explicitly provided
        existing_names = {f.name for f in plan_files}
        for plan_file in list(plan_files):
            if plan_file.suffix.lower() in (".yaml", ".yml"):
                sibling_md = plan_file.parent / f"{plan_file.stem}.md"
                if sibling_md.exists() and sibling_md.name not in existing_names:
                    plan_files.append(sibling_md)
                    existing_names.add(sibling_md.name)
        return plan_files

    # Collect from Plan/ directory
    for item in PLAN_DIR.iterdir():
        if item.is_file() and item.suffix.lower() in (".md", ".yaml", ".yml"):
            plan_files.append(item)

    # Also collect related .md files from plan_done if only .yaml was found in Plan/
    # This ensures we archive both .md and .yaml for the same plan
    yaml_stems = {f.stem for f in plan_files if f.suffix.lower() in (".yaml", ".yml")}
    if yaml_stems and PLAN_DONE_DIR.exists():
        for yaml_stem in yaml_stems:
            # Look for matching .md file in plan_done subdirectories
            for subdir in PLAN_DONE_DIR.iterdir():
                if subdir.is_dir():
                    md_file = subdir / f"{yaml_stem}.md"
                    if md_file.exists() and md_file.is_file():
                        # Add if not already included
                        if not any(f.name == md_file.name for f in plan_files):
                            plan_files.append(md_file)
                        break

    return plan_files


def _pick_yaml_plan_file(plan_files):
    yaml_files = [path for path in plan_files if path.suffix.lower() in (".yaml", ".yml")]
    if not yaml_files:
        return None
    return sorted(yaml_files, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def _collect_artifact_files(plan_files, artifact_paths=None):
    artifacts: list[Path] = []
    seen: set[Path] = set()

    for raw_path in artifact_paths or []:
        artifact_path = Path(raw_path)
        if artifact_path.exists() and artifact_path.is_file() and artifact_path not in seen:
            artifacts.append(artifact_path)
            seen.add(artifact_path)

    for plan_file in plan_files:
        if plan_file.suffix.lower() not in (".yaml", ".yml"):
            continue
        for artifact_path in get_plan_artifact_paths(plan_file, artifacts_dir=ARTIFACTS_DIR):
            if artifact_path.exists() and artifact_path.is_file() and artifact_path not in seen:
                artifacts.append(artifact_path)
                seen.add(artifact_path)

    return artifacts


def _export_templates_to_archive(archive_path: Path, yaml_plan_path: Path | None) -> tuple[int, str]:
    if yaml_plan_path is None:
        return 0, "none"

    templates_archive = archive_path / "workout_templates"
    templates_archive.mkdir(exist_ok=True)
    generated, total = generate_all_templates(
        yaml_plan_path,
        output_dir=templates_archive,
        cleanup_output=True,
    )
    if total > 0 and generated == total:
        logger.info(f"Exported {generated} debug templates from YAML for archive")
        return generated, "exported_from_yaml"

    if templates_archive.exists():
        shutil.rmtree(templates_archive, ignore_errors=True)
    logger.warning("Template export from YAML failed; archive will continue without debug templates")
    return 0, "none"


def get_archive_name(plan_name=None, owner_tag=None):
    """
    Generate archive directory name.

    Args:
        plan_name: Optional plan name (default: from active plan file)

    Returns:
        str: Archive name like "marathon_training_plan_07022026"
    """
    if plan_name is None:
        plan_name = _pick_active_plan_stem()
    plan_name = _normalize_tag(plan_name) or "plan"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [plan_name, timestamp]

    normalized_owner = _normalize_tag(owner_tag)
    if normalized_owner:
        parts.append(f"u{normalized_owner}")

    return _make_unique_archive_name("_".join(parts))


def archive_current_plan(
    archive_name=None,
    keep_plan=False,
    run_id=None,
    owner_tag=None,
    plan_paths=None,
    artifact_paths=None,
):
    """
    Archive the current plan, FIT files, and optional debug template exports.

    Args:
        archive_name: Optional custom archive name
        keep_plan: If True, copy plan to archive but keep in Plan/
        plan_paths: Optional iterable of specific plan file paths to archive/move
        artifact_paths: Optional iterable of additional build artifact paths

    Returns:
        Path: Path to created archive directory
    """
    if archive_name is None:
        # Derive plan name from explicitly provided plan_paths (most accurate),
        # or fall back to auto-detection from Plan/ directory.
        derived_plan_name = None
        if plan_paths:
            primary = next(
                (
                    Path(p)
                    for p in plan_paths
                    if Path(p).suffix.lower() in (".yaml", ".yml")
                ),
                None,
            )
            if primary is None:
                primary = next((Path(p) for p in plan_paths), None)
            if primary is not None:
                derived_plan_name = primary.stem
        archive_name = get_archive_name(plan_name=derived_plan_name, owner_tag=owner_tag)

    archive_path = ARCHIVE_DIR / archive_name
    archive_path.mkdir(parents=True, exist_ok=True)

    logger.info(f"Creating archive: {archive_name}")
    logger.info(f"Archive location: {archive_path}")

    # Collect plan files early so we can optionally export debug templates from YAML.
    plan_files = _collect_plan_files(plan_paths=plan_paths)
    artifact_files = _collect_artifact_files(plan_files, artifact_paths=artifact_paths)
    yaml_plan_path = _pick_yaml_plan_file(plan_files)

    # Archive workspace debug template exports (excluding __pycache__)
    templates = [f for f in TEMPLATES_DIR.glob("*.py")]
    templates_source = "workspace"
    templates_count = 0
    if templates:
        templates_archive = archive_path / "workout_templates"
        templates_archive.mkdir(exist_ok=True)

        for template in templates:
            dest = templates_archive / template.name
            shutil.copy2(template, dest)
            if not dest.exists() or dest.stat().st_size != template.stat().st_size:
                raise IOError(f"Failed to archive template: {template.name}")
            template.unlink()

        templates_count = len(templates)
        logger.info(f"Archived {templates_count} workspace debug templates")
    else:
        templates_count, templates_source = _export_templates_to_archive(archive_path, yaml_plan_path)
        if templates_count == 0:
            logger.warning("No debug templates to archive")

    # Clean __pycache__ in Workout_templates
    pycache_dir = TEMPLATES_DIR / "__pycache__"
    if pycache_dir.exists():
        shutil.rmtree(pycache_dir)
        logger.info("Cleaned __pycache__ in Workout_templates/")

    # Archive FIT files
    fits = list(OUTPUT_DIR.glob("*.fit"))
    if fits:
        fits_archive = archive_path / "output_fit"
        fits_archive.mkdir(exist_ok=True)

        for fit in fits:
            dest = fits_archive / fit.name
            shutil.copy2(fit, dest)
            if not dest.exists() or dest.stat().st_size != fit.stat().st_size:
                raise IOError(f"Failed to archive FIT file: {fit.name}")
            fit.unlink()

        logger.info(f"Archived {len(fits)} FIT files")
    else:
        logger.warning("No FIT files to archive")

    # Archive build artifacts
    artifact_count = 0
    if artifact_files:
        artifacts_archive = archive_path / "artifacts"
        artifacts_archive.mkdir(exist_ok=True)
        for artifact in artifact_files:
            dest = artifacts_archive / artifact.name
            shutil.copy2(artifact, dest)
            if not dest.exists() or dest.stat().st_size != artifact.stat().st_size:
                raise IOError(f"Failed to archive build artifact: {artifact.name}")
        artifact_count = len(artifact_files)
        logger.info(f"Archived {artifact_count} build artifact(s)")

    # Archive and move plan files (clean Plan/ directory except plan_done/)
    if plan_files:
        PLAN_DONE_DIR.mkdir(exist_ok=True)

        # Create plan_done subdirectory with same naming as archive
        plan_done_subdir = PLAN_DONE_DIR / archive_name
        plan_done_subdir.mkdir(exist_ok=True)

        for plan_file in plan_files:
            # Copy to archive
            shutil.copy2(plan_file, archive_path / plan_file.name)

            if keep_plan:
                logger.info(f"Copied plan to archive (keeping original): {plan_file.name}")
            else:
                # Move to plan_done/{archive_name}/
                dest = plan_done_subdir / plan_file.name
                shutil.move(str(plan_file), str(dest))
                logger.info(f"Moved plan to plan_done/{archive_name}: {plan_file.name}")

    # Create archive info file
    info_file = archive_path / "archive_info.txt"
    with open(info_file, 'w') as f:
        f.write(f"Archive created: {datetime.now().isoformat()}\n")
        f.write(f"Archive name: {archive_name}\n")
        if run_id:
            f.write(f"Run ID: {run_id}\n")
        if owner_tag is not None:
            f.write(f"Owner tag: {owner_tag}\n")
        f.write(f"Templates archived: {templates_count}\n")
        f.write(f"Templates source: {templates_source}\n")
        f.write(f"FIT files archived: {len(fits)}\n")
        f.write(f"Build artifacts archived: {artifact_count}\n")
        f.write(f"Plan files: {len(plan_files)}\n")
        f.write(f"Plan kept in Plan/: {keep_plan}\n")

    logger.info(f"Archive created successfully: {archive_path}")
    return archive_path


def restore_from_archive(archive_name):
    """
    Restore debug template exports, build artifacts, and FIT files from archive.

    Args:
        archive_name: Name of archive to restore

    Returns:
        bool: True if successful
    """
    archive_path = ARCHIVE_DIR / archive_name

    if not archive_path.exists():
        logger.error(f"Archive not found: {archive_name}")
        return False

    logger.info(f"Restoring from archive: {archive_name}")

    # Restore debug template exports
    templates_archive = archive_path / "workout_templates"
    if templates_archive.exists():
        TEMPLATES_DIR.mkdir(exist_ok=True)
        templates = list(templates_archive.glob("*.py"))

        for template in templates:
            dest = TEMPLATES_DIR / template.name
            if dest.exists():
                logger.warning(f"Overwriting existing template: {template.name}")
            shutil.copy2(template, dest)

        logger.info(f"Restored {len(templates)} debug templates")

    # Restore FIT files
    fits_archive = archive_path / "output_fit"
    if fits_archive.exists():
        OUTPUT_DIR.mkdir(exist_ok=True)
        fits = list(fits_archive.glob("*.fit"))

        for fit in fits:
            dest = OUTPUT_DIR / fit.name
            if dest.exists():
                logger.warning(f"Overwriting existing FIT file: {fit.name}")
            shutil.copy2(fit, dest)

        logger.info(f"Restored {len(fits)} FIT files")

    # Restore build artifacts
    artifacts_archive = archive_path / "artifacts"
    if artifacts_archive.exists():
        ARTIFACTS_DIR.mkdir(exist_ok=True)
        artifacts = list(artifacts_archive.iterdir())

        for artifact in artifacts:
            if not artifact.is_file():
                continue
            dest = ARTIFACTS_DIR / artifact.name
            if dest.exists():
                logger.warning(f"Overwriting existing build artifact: {artifact.name}")
            shutil.copy2(artifact, dest)

        logger.info(f"Restored {len([a for a in artifacts if a.is_file()])} build artifacts")

    # Restore plan files (copy, don't move)
    plan_files = (
        list(archive_path.glob("*.md"))
        + list(archive_path.glob("*.yaml"))
        + list(archive_path.glob("*.yml"))
    )
    if plan_files:
        PLAN_DIR.mkdir(exist_ok=True)
        for plan_file in plan_files:
            dest = PLAN_DIR / plan_file.name
            shutil.copy2(plan_file, dest)
            logger.info(f"Restored plan: {plan_file.name}")

    logger.info("Restore completed successfully")
    return True


def list_archives():
    """List all available archives."""
    if not ARCHIVE_DIR.exists():
        logger.info("No archives found")
        return []

    archives = sorted(ARCHIVE_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
    archives = [a for a in archives if a.is_dir()]

    return archives


def print_archives():
    """Print all archives with details."""
    archives = list_archives()

    if not archives:
        print("No archives found.")
        return

    print(f"\nAvailable archives ({len(archives)}):\n")
    print(f"{'Name':<40} {'Created':<20} {'Debug Tpl':<12} {'FIT Files'}")
    print("-" * 90)

    for archive in archives:
        info_file = archive / "archive_info.txt"
        templates_count = len(list((archive / "workout_templates").glob("*.py"))) if (archive / "workout_templates").exists() else 0
        fits_count = len(list((archive / "output_fit").glob("*.fit"))) if (archive / "output_fit").exists() else 0

        created = ""
        if info_file.exists():
            with open(info_file) as f:
                for line in f:
                    if line.startswith("Archive created:"):
                        created = line.split(":", 1)[1].strip()[:19]
                        break

        print(f"{archive.name:<40} {created:<20} {templates_count:<12} {fits_count}")


if __name__ == "__main__":
    import sys
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description="Manage workout archives")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Archive command
    archive_parser = subparsers.add_parser("archive", help="Archive current plan")
    archive_parser.add_argument("--name", help="Custom archive name")
    archive_parser.add_argument("--keep-plan", action="store_true", help="Keep plan in Plan/ directory")
    archive_parser.add_argument("--run-id", help="Run identifier for traceability")
    archive_parser.add_argument("--owner-tag", help="Optional owner/user tag for archive naming")

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore from archive")
    restore_parser.add_argument("archive_name", help="Archive name to restore")

    # List command
    subparsers.add_parser("list", help="List all archives")

    args = parser.parse_args()

    if args.command == "archive":
        archive_path = archive_current_plan(args.name, args.keep_plan, args.run_id, args.owner_tag)
        print(f"\n[OK] Archived to: {archive_path}")

    elif args.command == "restore":
        if restore_from_archive(args.archive_name):
            print(f"\n[OK] Restored from: {args.archive_name}")
        else:
            print(f"\n[FAIL] Failed to restore from: {args.archive_name}")
            sys.exit(1)

    elif args.command == "list":
        print_archives()

    else:
        parser.print_help()
