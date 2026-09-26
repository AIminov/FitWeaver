"""Run ``garmin_fit.cli`` commands inside the current process with captured output.

The desktop GUI used to start ``garmin-fit-cli.exe`` (or ``python -m
garmin_fit.cli``) for every action. A PyInstaller onefile exe unpacks itself
on each start, so every action — including the automatic YAML check after a
plan is loaded — cost ~4.5 s before any work began. Running the same
``cli.main`` in-process removes that cost and keeps secrets such as the
Garmin password off any command line.

Output from ``print`` (stdout/stderr) and from ``logging`` is forwarded line by
line to ``on_line``. Commands are serialised with a lock because stdout
redirection is process-wide.
"""

from __future__ import annotations

import contextlib
import io
import logging
import threading
from typing import Callable, Sequence

_RUN_LOCK = threading.Lock()

# Loggers whose records must not be echoed back (the GUI logs its own panel
# lines through "garmin_fit.gui"; forwarding them would loop).
_EXCLUDED_LOGGER_PREFIXES = ("garmin_fit.gui",)

SECRET_FLAGS = frozenset({"--password"})


class _LineWriter(io.TextIOBase):
    """File-like object that calls ``on_line`` for every completed line."""

    def __init__(self, on_line: Callable[[str], None]) -> None:
        self._on_line = on_line
        self._buffer = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._on_line(line.rstrip("\r"))
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._on_line(self._buffer)
            self._buffer = ""


class _ForwardHandler(logging.Handler):
    def __init__(self, on_line: Callable[[str], None]) -> None:
        super().__init__(level=logging.INFO)
        self._on_line = on_line
        self.setFormatter(logging.Formatter("%(message)s"))

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(_EXCLUDED_LOGGER_PREFIXES)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            for line in self.format(record).splitlines() or [""]:
                self._on_line(line)
        except Exception:  # never let a display problem break the command
            self.handleError(record)


def redact_args(args: Sequence[str]) -> list[str]:
    """Copy of ``args`` with values of secret flags replaced by ``***``."""
    redacted: list[str] = []
    hide_next = False
    for arg in args:
        if hide_next:
            redacted.append("***")
            hide_next = False
            continue
        redacted.append(arg)
        hide_next = arg in SECRET_FLAGS
    return redacted


def run_cli_captured(args: Sequence[str], on_line: Callable[[str], None]) -> int:
    """Run ``garmin_fit.cli.main(args)`` and return its exit code.

    Never raises: unexpected exceptions are reported through ``on_line`` and
    turned into exit code 1.
    """
    from . import cli

    writer = _LineWriter(on_line)
    handler = _ForwardHandler(on_line)
    root = logging.getLogger()

    with _RUN_LOCK:
        previous_level = root.level
        root.addHandler(handler)
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                try:
                    code = cli.main(list(args))
                except SystemExit as exc:  # argparse usage errors
                    code = exc.code if isinstance(exc.code, int) else 1
                except Exception as exc:
                    on_line(f"[ERR] {type(exc).__name__}: {exc}")
                    code = 1
                finally:
                    writer.flush()
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)
    return int(code or 0)
