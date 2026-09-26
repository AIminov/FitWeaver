from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def configure_console_encoding() -> None:
    """Never crash on Cyrillic output.

    Redirected stdout (a file or pipe, e.g. the packaged exe run by a script)
    defaults to the Windows ANSI code page, where printing Russian text raised
    UnicodeEncodeError. Redirected streams switch to UTF-8; interactive
    consoles keep their encoding but replace characters they cannot show.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # None (windowed exe) or a GUI capture stream
            continue
        try:
            if stream.isatty():
                reconfigure(errors="replace")
            else:
                reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def configure_logging() -> None:
    configure_console_encoding()
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
