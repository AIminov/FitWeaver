"""Runtime-aware project configuration for the Garmin FIT package."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def resolve_runtime_root() -> Path:
    """Resolve the mutable runtime root, defaulting to the project root."""
    env_path = os.getenv("GARMIN_FIT_RUNTIME_DIR")
    if not env_path:
        return PROJECT_ROOT

    candidate = Path(env_path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


ROOT = PROJECT_ROOT
RUNTIME_ROOT = resolve_runtime_root()
SCRIPTS_DIR = PROJECT_ROOT / "Scripts"
PLAN_DIR = RUNTIME_ROOT / "Plan"
PLAN_DONE_DIR = PLAN_DIR / "plan_done"
TEMPLATES_DIR = RUNTIME_ROOT / "Workout_templates"
OUTPUT_DIR = RUNTIME_ROOT / "Output_fit"
ARCHIVE_DIR = RUNTIME_ROOT / "Archive"
ARTIFACTS_DIR = RUNTIME_ROOT / "Build_artifacts"
LOGS_DIR = RUNTIME_ROOT / "Logs"
STATE_FILE = RUNTIME_ROOT / "state.json"
USER_PROFILE = RUNTIME_ROOT / "user_profile.yaml"
BOT_CONFIG_FILE = RUNTIME_ROOT / "bot_config.yaml"


def resolve_fitcsv_jar() -> Optional[Path]:
    """Resolve the optional FitCSVTool.jar path."""
    env_path = os.getenv("FITCSV_JAR")
    candidates = []

    if env_path:
        candidates.append(Path(env_path).expanduser())

    candidates.extend(
        [
            PROJECT_ROOT / "FitCSVTool.jar",
            PROJECT_ROOT / "Tools" / "FitCSVTool.jar",
            PROJECT_ROOT / "sdk" / "java" / "FitCSVTool.jar",
        ]
    )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


FITCSV_JAR = resolve_fitcsv_jar()
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
