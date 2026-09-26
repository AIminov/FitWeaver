"""Guards the temp-directory bootstrap performed in conftest.py.

The bootstrap itself moved to conftest.py so that it also applies to
single-file runs; what is left here is the assertion that it took effect.
"""

import tempfile
import unittest

from tests.conftest import ROOT, TEST_TMP


class TempBootstrapTests(unittest.TestCase):
    def test_temp_bootstrap_is_writable(self):
        probe = TEST_TMP / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        self.assertEqual(tempfile.gettempdir(), str(TEST_TMP))

    def test_temp_root_is_outside_the_repository(self):
        """A temp root inside the repo gets swept into OneDrive sync.

        The repo-local path stays available as a documented last resort, so this
        asserts the preference held rather than that the fallback is unreachable.
        """
        if TEST_TMP == ROOT / ".tmp_runtime_tests":
            self.skipTest("system temp unusable; repo-local fallback in use")
        self.assertNotIn(ROOT, TEST_TMP.parents)
