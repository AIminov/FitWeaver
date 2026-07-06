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

    def test_has_user_profile_false_until_written(self):
        email = "amir@example.com"
        self.assertFalse(profile_store.has_user_profile(email))
        profile_store.write_user_profile(email, max_hr=190, resting_hr=48)
        self.assertTrue(profile_store.has_user_profile(email))

    def test_compute_hr_zones_covers_full_range_without_gaps(self):
        zones = profile_store.compute_hr_zones(200)
        self.assertEqual(zones["zone1"]["low"], 100)
        self.assertEqual(zones["zone5"]["high"], 200)
        # each zone's high should match the next zone's low (no gaps/overlaps)
        names = ["zone1", "zone2", "zone3", "zone4", "zone5"]
        for a, b in zip(names, names[1:]):
            self.assertEqual(zones[a]["high"], zones[b]["low"])

    def test_write_user_profile_produces_loadable_yaml(self):
        import yaml
        email = "amir@example.com"
        profile_store.write_user_profile(email, max_hr=190, resting_hr=48)
        data = yaml.safe_load(profile_store.user_profile_yaml_path(email).read_text(encoding="utf-8"))
        self.assertEqual(data["max_hr"], 190)
        self.assertEqual(data["resting_hr"], 48)
        self.assertIn("zone1", data["hr_zones"])
        self.assertIn("zone5", data["hr_zones"])

    def test_mark_user_profile_skipped_counts_as_present_but_has_no_zones(self):
        import yaml
        email = "amir@example.com"
        profile_store.mark_user_profile_skipped(email)
        self.assertTrue(profile_store.has_user_profile(email))
        data = yaml.safe_load(profile_store.user_profile_yaml_path(email).read_text(encoding="utf-8"))
        self.assertIsNone(data)  # comment-only file -> None, treated as "no personal zones"

    def test_migrate_legacy_user_profile_copies_existing_global_file(self):
        email = "amir@example.com"
        self.user_profile_path.write_text("max_hr: 190\nresting_hr: 48\n", encoding="utf-8")

        migrated = profile_store.migrate_legacy_user_profile(email)

        self.assertTrue(migrated)
        self.assertEqual(
            profile_store.user_profile_yaml_path(email).read_text(encoding="utf-8"),
            "max_hr: 190\nresting_hr: 48\n",
        )

    def test_migrate_legacy_user_profile_consumes_the_legacy_file(self):
        # Regression: activate_user_profile() rewrites the global slot with
        # whichever profile is active, so a second brand-new profile must
        # NOT see the first profile's synced-back data as "legacy" to steal.
        email_a = "amir@example.com"
        email_b = "friend@example.com"
        self.user_profile_path.write_text("max_hr: 190\nresting_hr: 48\n", encoding="utf-8")

        self.assertTrue(profile_store.migrate_legacy_user_profile(email_a))
        self.assertFalse(self.user_profile_path.exists())  # legacy file consumed

        profile_store.activate_user_profile(email_a)  # re-populates the global slot
        self.assertTrue(self.user_profile_path.exists())

        migrated_b = profile_store.migrate_legacy_user_profile(email_b)
        self.assertFalse(migrated_b, "friend must not inherit amir's re-synced global file")
        self.assertFalse(profile_store.has_user_profile(email_b))

    def test_migrate_legacy_user_profile_noop_when_no_legacy_file(self):
        self.assertFalse(profile_store.migrate_legacy_user_profile("amir@example.com"))
        self.assertFalse(profile_store.has_user_profile("amir@example.com"))

    def test_migrate_legacy_user_profile_does_not_overwrite_existing_profile_data(self):
        email = "amir@example.com"
        profile_store.write_user_profile(email, max_hr=175, resting_hr=55)
        self.user_profile_path.write_text("max_hr: 190\nresting_hr: 48\n", encoding="utf-8")

        migrated = profile_store.migrate_legacy_user_profile(email)

        self.assertFalse(migrated)
        import yaml
        data = yaml.safe_load(profile_store.user_profile_yaml_path(email).read_text(encoding="utf-8"))
        self.assertEqual(data["max_hr"], 175)  # the profile's own data, not the legacy file

    # ── Personal workout-builder templates ──────────────────────────────────
    def test_list_user_templates_empty_when_none_saved(self):
        self.assertEqual(profile_store.list_user_templates("amir@example.com"), {})

    def test_save_and_list_user_template_round_trip(self):
        email = "amir@example.com"
        steps = [{"type": "dist_open", "km": 5.0, "intensity": "active"}]

        profile_store.save_user_template(email, "Мой лёгкий бег", steps)

        templates = profile_store.list_user_templates(email)
        self.assertEqual(templates["Мой лёгкий бег"], steps)

    def test_save_user_template_overwrites_same_name(self):
        email = "amir@example.com"
        profile_store.save_user_template(email, "T1", [{"type": "dist_open", "km": 1.0}])
        profile_store.save_user_template(email, "T1", [{"type": "dist_open", "km": 2.0}])

        templates = profile_store.list_user_templates(email)
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates["T1"][0]["km"], 2.0)

    def test_delete_user_template(self):
        email = "amir@example.com"
        profile_store.save_user_template(email, "T1", [{"type": "dist_open", "km": 1.0}])
        profile_store.save_user_template(email, "T2", [{"type": "dist_open", "km": 2.0}])

        profile_store.delete_user_template(email, "T1")

        templates = profile_store.list_user_templates(email)
        self.assertEqual(list(templates.keys()), ["T2"])

    def test_delete_user_template_missing_name_is_a_noop(self):
        email = "amir@example.com"
        profile_store.save_user_template(email, "T1", [{"type": "dist_open", "km": 1.0}])

        profile_store.delete_user_template(email, "does_not_exist")

        self.assertEqual(list(profile_store.list_user_templates(email).keys()), ["T1"])

    def test_templates_are_isolated_per_profile(self):
        profile_store.save_user_template("amir@example.com", "T1", [{"type": "dist_open", "km": 1.0}])
        self.assertEqual(profile_store.list_user_templates("friend@example.com"), {})


if __name__ == "__main__":
    unittest.main()
