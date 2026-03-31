"""Helpers for preparing a dedicated runtime root for mutable project data."""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

from .config import PROJECT_ROOT


logger = logging.getLogger(__name__)

MUTABLE_DIRECTORIES = [
    "Plan",
    "Output_fit",
    "Archive",
    "Build_artifacts",
    "Logs",
    "Workout_templates",
]

MUTABLE_FILES = [
    "state.json",
    "user_profile.yaml",
    "bot_config.yaml",
]


def resolve_runtime_root(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def init_runtime_root(runtime_root: Path) -> list[Path]:
    """Create the mutable runtime directory structure."""
    runtime_root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for name in MUTABLE_DIRECTORIES:
        directory = runtime_root / name
        directory.mkdir(parents=True, exist_ok=True)
        created.append(directory)
    return created


def _copy_tree_contents(source: Path, destination: Path, *, overwrite: bool) -> tuple[int, int]:
    copied = 0
    skipped = 0
    destination.mkdir(parents=True, exist_ok=True)

    for source_path in source.rglob("*"):
        relative = source_path.relative_to(source)
        destination_path = destination / relative
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue
        if destination_path.exists() and not overwrite:
            skipped += 1
            continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        copied += 1

    return copied, skipped


def copy_runtime_data(runtime_root: Path, *, overwrite: bool = False) -> dict[str, int]:
    """Copy mutable data from the project root into a dedicated runtime root."""
    init_runtime_root(runtime_root)
    copied = 0
    skipped = 0

    for directory_name in MUTABLE_DIRECTORIES:
        source_dir = PROJECT_ROOT / directory_name
        if not source_dir.exists() or not source_dir.is_dir():
            continue
        dir_copied, dir_skipped = _copy_tree_contents(
            source_dir,
            runtime_root / directory_name,
            overwrite=overwrite,
        )
        copied += dir_copied
        skipped += dir_skipped

    for file_name in MUTABLE_FILES:
        source_file = PROJECT_ROOT / file_name
        destination_file = runtime_root / file_name
        if not source_file.exists() or not source_file.is_file():
            continue
        if destination_file.exists() and not overwrite:
            skipped += 1
            continue
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
        copied += 1

    return {"copied": copied, "skipped": skipped}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a dedicated runtime root for mutable Garmin FIT project data."
    )
    parser.add_argument(
        "--runtime-root",
        default="runtime",
        help="Target runtime root path. Relative paths are resolved from the project root.",
    )
    parser.add_argument(
        "--copy-existing",
        action="store_true",
        help="Copy mutable data from the current project root into the runtime root.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite files already present in the runtime root when copying.",
    )
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args()

    runtime_root = resolve_runtime_root(args.runtime_root)
    created = init_runtime_root(runtime_root)

    logger.info(f"Runtime root: {runtime_root}")
    logger.info(f"Created/verified {len(created)} mutable directories")

    if args.copy_existing:
        summary = copy_runtime_data(runtime_root, overwrite=args.overwrite)
        logger.info(f"Copied files: {summary['copied']}")
        logger.info(f"Skipped existing files: {summary['skipped']}")

    logger.info("")
    logger.info("To use this runtime root for commands in the current shell:")
    logger.info(f"  $env:GARMIN_FIT_RUNTIME_DIR='{runtime_root}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
