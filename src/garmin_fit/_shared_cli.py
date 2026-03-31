from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def generate_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{ts}_{uuid4().hex[:8]}"
