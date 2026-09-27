"""Crash-safe file writes for user-owned files (plans, profiles, session)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Write ``text`` so that ``path`` holds either the old or the new content.

    The data goes to a temporary file in the same directory, is flushed to
    disk, then replaces the target in one step (os.replace). A crash or a
    failing write mid-way can no longer leave a truncated plan or profile.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def prune_directory(directory: str | Path, pattern: str, keep: int) -> int:
    """Delete all but the ``keep`` most recently modified files matching ``pattern``.

    For app-owned caches only (LLM segment cache, plan staging DBs). Returns
    the number of files removed; errors on individual files are ignored.
    """
    folder = Path(directory)
    if not folder.is_dir():
        return 0
    files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for stale in files[keep:]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            pass
    return removed
