"""
Runtime bootstrap for resilient temp directory handling on Windows.

Loaded automatically by Python if present on sys.path.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def _is_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write_probe.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _configure_temp_fallback() -> None:
    fallback = Path(__file__).resolve().parent / ".tmp_runtime"
    fallback.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(fallback)
    os.environ["TEMP"] = str(fallback)
    tempfile.tempdir = str(fallback)


_configure_temp_fallback()
