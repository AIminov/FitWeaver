import os
from pathlib import Path
import tempfile
import shutil
import uuid
import unittest


ROOT = Path(__file__).resolve().parent.parent
LOCAL_TMP = ROOT / ".tmp_runtime_tests"
LOCAL_TMP.mkdir(parents=True, exist_ok=True)

os.environ["TMP"] = str(LOCAL_TMP)
os.environ["TEMP"] = str(LOCAL_TMP)
tempfile.tempdir = str(LOCAL_TMP)


class _WritableTemporaryDirectory:
    def __init__(self, suffix=None, prefix=None, dir=None, ignore_cleanup_errors=False):
        self._base = Path(dir or LOCAL_TMP)
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


class TempBootstrapTests(unittest.TestCase):
    def test_temp_bootstrap_is_writable(self):
        probe = LOCAL_TMP / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        self.assertEqual(tempfile.gettempdir(), str(LOCAL_TMP))
