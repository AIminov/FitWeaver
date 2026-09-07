"""Test-session bootstrap.

Redirects the temp directory used by the suite before pytest's own tmp_path
factory reads it. This lives in conftest.py rather than in a test module so it
also applies when a single test file is run directly -- previously the
redirection sat in test_000_temp_bootstrap.py and only took effect when the
whole directory was collected, so `pytest tests/test_x.py` still landed in the
machine's system temp and inherited whatever was broken there.

The chosen root is deliberately *outside* the repository. The repo lives under
OneDrive on the maintainer's machine, and a temp root inside it means every
scratch directory the suite creates is queued for cloud sync -- slow, noisy, and
an occasional source of PermissionError when sync holds a lock mid-run.
"""

import os
import shutil
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _usable(path: Path) -> bool:
    """True when we can create path and write a file inside it."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".probe_{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _pick_temp_root() -> Path:
    """Temp root for the suite, most-preferred first.

    1. FITWEAVER_TEST_TMP, when set -- lets CI or a developer place it anywhere.
    2. A named directory under the system temp -- outside the repo, so nothing
       the suite writes is synced to OneDrive.
    3. The repo-local directory -- last resort for a machine whose system temp
       is unwritable, which is the case this bootstrap originally existed for.
    """
    override = os.environ.get("FITWEAVER_TEST_TMP")
    if override:
        candidate = Path(override)
        if _usable(candidate):
            return candidate

    system = Path(tempfile.gettempdir()) / "fitweaver_test_tmp"
    if _usable(system):
        return system

    return ROOT / ".tmp_runtime_tests"


TEST_TMP = _pick_temp_root()
TEST_TMP.mkdir(parents=True, exist_ok=True)

os.environ["TMP"] = str(TEST_TMP)
os.environ["TEMP"] = str(TEST_TMP)
tempfile.tempdir = str(TEST_TMP)


class _WritableTemporaryDirectory:
    """tempfile.TemporaryDirectory whose cleanup never raises on Windows.

    The stdlib version fails when a test leaves a read-only file behind, which
    aborts the test that owns the directory instead of the one that wrote the
    file.
    """

    def __init__(self, suffix=None, prefix=None, dir=None, ignore_cleanup_errors=False):
        self._base = Path(dir or TEST_TMP)
        self._prefix = prefix or "tmp"
        self._suffix = suffix or ""
        self.name = ""
        self._ignore_cleanup_errors = ignore_cleanup_errors

    def __enter__(self):
        while True:
            candidate = self._base / f"{self._prefix}{uuid.uuid4().hex}{self._suffix}"
            try:
                candidate.mkdir(parents=True, exist_ok=False)
                self.name = str(candidate)
                return self.name
            except FileExistsError:
                continue

    def __exit__(self, exc_type, exc, tb):
        self.cleanup()

    def cleanup(self):
        if not self.name:
            return
        shutil.rmtree(self.name, ignore_errors=self._ignore_cleanup_errors)


tempfile.TemporaryDirectory = _WritableTemporaryDirectory
