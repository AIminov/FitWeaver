"""Shared logging utilities for Garmin FIT generation scripts."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .config import LOGS_DIR


def setup_file_logging(prefix: str = "workflow", run_id: str | None = None):
    """Setup file logging to Logs/YYYYMMDD/ directory.

    Idempotent within a single process: if a FileHandler already exists on the
    root logger, returns its path without adding a second handler (which would
    cause every log line to be written twice).
    """
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.FileHandler):
            return Path(h.baseFilename)

    date_dir = LOGS_DIR / datetime.now().strftime("%Y%m%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    suffix = f"_{run_id}" if run_id else ""
    log_file = date_dir / f"{prefix}_{datetime.now().strftime('%H%M%S')}{suffix}.log"

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    root.addHandler(file_handler)
    return log_file
