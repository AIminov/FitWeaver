import unittest

from garmin_fit.workflow import _select_garmin_workouts_for_delete


class GarminCalendarDeleteTests(unittest.TestCase):
    def test_selects_fitweaver_named_workouts_in_date_range(self):
        workouts = [
            {"workoutId": 1, "workoutName": "W23_06-03_Wed_Easy_8km"},
            {"workoutId": 2, "workoutName": "W24_06-10_Wed_Tempo_10km"},
            {"workoutId": 3, "workoutName": "W25_07-01_Wed_Long_18km"},
            {"workoutId": 4, "workoutName": "Manual Garmin Workout"},
        ]

        selected, skipped = _select_garmin_workouts_for_delete(
            workouts,
            year=2026,
            from_date="2026-06-01",
            to_date="2026-06-30",
        )

        self.assertEqual([item[0]["workoutId"] for item in selected], [1, 2])
        self.assertEqual(len(skipped), 2)

    def test_delete_all_includes_non_fitweaver_names_without_date_filter(self):
        workouts = [
            {"workoutId": 1, "workoutName": "W23_06-03_Wed_Easy_8km"},
            {"workoutId": 2, "workoutName": "Manual Garmin Workout"},
        ]

        selected, skipped = _select_garmin_workouts_for_delete(
            workouts,
            year=2026,
            delete_all=True,
        )

        self.assertEqual([item[0]["workoutId"] for item in selected], [1, 2])
        self.assertEqual(skipped, [])

    def test_delete_all_with_date_filter_skips_unmatched_names(self):
        workouts = [
            {"workoutId": 1, "workoutName": "W23_06-03_Wed_Easy_8km"},
            {"workoutId": 2, "workoutName": "Manual Garmin Workout"},
        ]

        selected, skipped = _select_garmin_workouts_for_delete(
            workouts,
            year=2026,
            from_date="2026-06-01",
            to_date="2026-06-30",
            delete_all=True,
        )

        self.assertEqual([item[0]["workoutId"] for item in selected], [1])
        self.assertEqual(len(skipped), 1)

    def test_rejects_inverted_date_range(self):
        with self.assertRaises(ValueError):
            _select_garmin_workouts_for_delete(
                [{"workoutId": 1, "workoutName": "W23_06-03_Wed_Easy_8km"}],
                year=2026,
                from_date="2026-07-01",
                to_date="2026-06-01",
            )
