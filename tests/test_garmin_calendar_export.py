import unittest
from unittest.mock import Mock

from garmin_fit.garmin_calendar_export import GarminCalendarExporter
from garmin_fit.plan_domain import Workout, WorkoutPlan, WorkoutStep


def _make_workout(filename="W01_01-06_Mon_Easy_5km"):
    return Workout(
        filename=filename, name=filename, type_code="easy",
        steps=[WorkoutStep(step_type="dist_open", km=5.0, intensity="active")],
    )


class GarminCalendarExportNetworkErrorTests(unittest.TestCase):
    """TODO #10: error paths for garmin_calendar_export are untested."""

    def test_upload_and_schedule_captures_network_error_without_raising(self):
        client = Mock()
        client.upload_workout.side_effect = ConnectionError("Garmin Connect unreachable")
        exporter = GarminCalendarExporter(client, upload_delay=0)

        result = exporter.upload_and_schedule(_make_workout(), dry_run=False)

        self.assertFalse(result.ok)
        self.assertIn("unreachable", result.error)
        self.assertFalse(result.scheduled)
        self.assertIsNone(result.workout_id)
        client.schedule_workout.assert_not_called()

    def test_upload_succeeds_but_schedule_fails_is_captured(self):
        client = Mock()
        client.upload_workout.return_value = {"workoutId": "abc123"}
        client.schedule_workout.side_effect = TimeoutError("request timed out")
        exporter = GarminCalendarExporter(client, upload_delay=0)

        result = exporter.upload_and_schedule(_make_workout(), date="2026-01-06", dry_run=False)

        self.assertFalse(result.ok)
        self.assertEqual(result.workout_id, "abc123")  # upload itself succeeded
        self.assertFalse(result.scheduled)
        self.assertIn("timed out", result.error)

    def test_upload_plan_continues_after_one_workout_fails(self):
        client = Mock()
        # First workout fails, second succeeds
        client.upload_workout.side_effect = [
            ConnectionError("network blip"),
            {"workoutId": "ok-1"},
        ]
        exporter = GarminCalendarExporter(client, upload_delay=0)
        plan = WorkoutPlan(workouts=[
            _make_workout("W01_01-05_Mon_Easy_5km"),
            _make_workout("W01_01-07_Wed_Easy_5km"),
        ])

        result = exporter.upload_plan(plan, schedule=False, dry_run=False, week_pause=0)

        self.assertEqual(result.total, 2)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.uploaded, 1)

    def test_upload_and_schedule_dry_run_makes_no_client_calls(self):
        client = Mock()
        exporter = GarminCalendarExporter(client, upload_delay=0)

        result = exporter.upload_and_schedule(_make_workout(), dry_run=True)

        self.assertTrue(result.ok)
        self.assertTrue(result.dry_run)
        client.upload_workout.assert_not_called()
        client.schedule_workout.assert_not_called()


if __name__ == "__main__":
    unittest.main()
