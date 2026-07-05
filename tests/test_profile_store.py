import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from garmin_fit import profile_store
from garmin_fit.workflow import _resolve_garmin_token_dir


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        # tests/test_000_temp_bootstrap.py replaces tempfile.TemporaryDirectory
        # with a variant that only creates the directory inside __enter__, so
        # this must be entered explicitly rather than just constructed.
        tmp_cm = tempfile.TemporaryDirectory()
        self.tmp_path = Path(tmp_cm.__enter__())
        self.addCleanup(tmp_cm.__exit__, None, None, None)

        self.profiles_root = self.tmp_path / "profiles"
        self.user_profile_path = self.tmp_path / "user_profile.yaml"

        self._patches = [
            patch.object(profile_store, "PROFILES_ROOT", self.profiles_root),
            patch.object(profile_store, "USER_PROFILE", self.user_profile_path),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_email_slug_matches_garmin_token_dir_scheme(self):
        email = "Test@Example.com"
        token_dir = _resolve_garmin_token_dir(email=email)
        self.assertEqual(token_dir.name, f"cli_{profile_store.email_slug(email)}")

    def test_email_slug_is_case_and_whitespace_insensitive(self):
        self.assertEqual(
            profile_store.email_slug("  Amir@Example.com "),
            profile_store.email_slug("amir@example.com"),
        )

    def test_profile_dir_is_created_and_stable(self):
        d1 = profile_store.profile_dir("amir@example.com")
        d2 = profile_store.profile_dir("amir@example.com")
        self.assertTrue(d1.exists())
        self.assertEqual(d1, d2)

    def test_different_emails_get_different_dirs(self):
        d1 = profile_store.profile_dir("amir@example.com")
        d2 = profile_store.profile_dir("friend@example.com")
        self.assertNotEqual(d1, d2)

    def test_save_and_load_session_round_trip(self):
        profile_store.save_session("amir@example.com", {"yaml_path": "Plan/x.yaml", "year": "2026"})
        data = profile_store.load_session("amir@example.com")
        self.assertEqual(data["yaml_path"], "Plan/x.yaml")
        self.assertEqual(data["year"], "2026")
        self.assertEqual(data["email"], "amir@example.com")

    def test_load_session_missing_returns_empty_dict(self):
        self.assertEqual(profile_store.load_session("nobody@example.com"), {})

    def test_list_profiles_reflects_saved_sessions(self):
        profile_store.save_session("amir@example.com", {"yaml_path": "a.yaml"})
        profile_store.save_session("friend@example.com", {"yaml_path": "b.yaml"})
        self.assertEqual(
            sorted(profile_store.list_profiles()),
            sorted(["amir@example.com", "friend@example.com"]),
        )

    def test_list_profiles_empty_when_no_profiles_root(self):
        self.assertEqual(profile_store.list_profiles(), [])

    def test_activate_user_profile_copies_personal_yaml_into_global_slot(self):
        email = "amir@example.com"
        personal_path = profile_store.user_profile_yaml_path(email)
        personal_path.write_text("max_hr: 190\nresting_hr: 48\n", encoding="utf-8")

        profile_store.activate_user_profile(email)

        self.assertTrue(self.user_profile_path.exists())
        self.assertEqual(self.user_profile_path.read_text(encoding="utf-8"),
                         "max_hr: 190\nresting_hr: 48\n")

    def test_activate_user_profile_is_noop_when_no_personal_yaml_exists(self):
        profile_store.activate_user_profile("amir@example.com")
        self.assertFalse(self.user_profile_path.exists())


if __name__ == "__main__":
    unittest.main()
