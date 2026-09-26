import unittest
from unittest.mock import Mock

from garmin_fit.garmin_calendar_export import GarminCalendarExporter
from garmin_fit.plan_domain import plan_from_data


def _plan():
    return plan_from_data({"workouts": [
        {"filename": "W40_10-01_Thu_Easy", "name": "W40_10-01_Thu_Easy",
         "steps": [{"type": "dist_open", "km": 5.0}]},
        {"filename": "W40_10-03_Sat_Long", "name": "W40_10-03_Sat_Long",
         "steps": [{"type": "dist_open", "km": 15.0}]},
    ]})


def _client(scheduled):
    client = Mock()
    client.get_scheduled_workouts.return_value = scheduled
    client.upload_workout.return_value = {"workoutId": 42}
    return client


class UploadDedupTests(unittest.TestCase):
    def _upload(self, client, **kwargs):
        exporter = GarminCalendarExporter(client, upload_delay=0)
        return exporter.upload_plan(_plan(), year=2026, week_pause=0, **kwargs)

    def test_already_scheduled_workout_is_skipped(self):
        client = _client([{"date": "2026-10-01", "workoutId": 7, "workoutName": "W40_10-01_Thu_Easy"}])

        result = self._upload(client)

        self.assertEqual(client.upload_workout.call_count, 1)
        self.assertEqual(result.skipped_duplicates, 1)
        self.assertEqual(result.uploaded, 1)
        self.assertIn("skipped 1 already scheduled", result.summary())
        client.get_scheduled_workouts.assert_called_once_with(2026, 10)

    def test_same_name_on_another_date_is_not_a_duplicate(self):
        client = _client([{"date": "2026-10-02", "workoutId": 7, "workoutName": "W40_10-01_Thu_Easy"}])
        self.assertEqual(self._upload(client).skipped_duplicates, 0)
        self.assertEqual(client.upload_workout.call_count, 2)

    def test_allow_duplicates_skips_the_calendar_read(self):
        client = _client([{"date": "2026-10-01", "workoutId": 7, "workoutName": "W40_10-01_Thu_Easy"}])
        result = self._upload(client, skip_duplicates=False)
        client.get_scheduled_workouts.assert_not_called()
        self.assertEqual(result.uploaded, 2)

    def test_unreadable_calendar_does_not_block_upload(self):
        client = _client([])
        client.get_scheduled_workouts.side_effect = RuntimeError("503")
        self.assertEqual(self._upload(client).uploaded, 2)


if __name__ == "__main__":
    unittest.main()
