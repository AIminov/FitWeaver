"""Shared logging utilities for Garmin FIT generation scripts."""

from __future__ import annotations

import logging
from datetime import datetime

from .config import LOGS_DIR


def setup_file_logging(prefix: str = "workflow", run_id: str | None = None):
    """Setup file logging to Logs/YYYYMMDD/ directory."""
    date_dir = LOGS_DIR / datetime.now().strftime("%Y%m%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    suffix = f"_{run_id}" if run_id else ""
    log_file = date_dir / f"{prefix}_{datetime.now().strftime('%H%M%S')}{suffix}.log"

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )

    logging.getLogger().addHandler(file_handler)
    return log_file
