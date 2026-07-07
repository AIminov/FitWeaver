from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def generate_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{ts}_{uuid4().hex[:8]}"


def display_path(path: Path, root: Path) -> str:
    """Path for a log message: relative to root when possible, else absolute.

    A YAML plan can live anywhere on disk (e.g. picked via the GUI's file
    browser), not just under root -- Path.relative_to() raises ValueError in
    that case, which must never crash what's purely a cosmetic log line.
    """
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
