import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml

from garmin_fit.plan_domain import plan_from_data, plan_to_data
from garmin_fit.plan_processing import repair_plan_data
from garmin_fit.plan_store import PlanStore
from garmin_fit.plan_validator import validate_plan_data

RAW_PLAN = {
    "workouts": [
        {
            "filename": "W15_04-14_Tue_Intervals_6x800m",
            "name": "W15_04-14_Tue_Intervals_6x800m",
            "desc": "Classic intervals test fixture",
            "type_code": "intervals",
            "distance_km": 10.4,
            "estimated_duration_min": 55,
            "custom_note": "workout-level extra field",
            "steps": [
                {"type": "dist_pace", "km": 2.0, "pace_fast": "5:45",
                 "pace_slow": "6:00", "intensity": "warmup"},
                {"type": "dist_hr", "km": 0.8, "hr_low": 160, "hr_high": 170,
                 "intensity": "active", "coach_tag": "hard"},
                {"type": "dist_open", "km": 0.4, "intensity": "recovery"},
                {"type": "repeat", "back_to_offset": 1, "count": 6},
                {"type": "dist_pace", "km": 1.0, "pace_fast": "5:45",
                 "pace_slow": "6:00", "intensity": "cooldown"},
            ],
        },
        {
            "filename": "W15_04-16_Thu_SBU_Drills",
            "name": "W15_04-16_Thu_SBU_Drills",
            "desc": "SBU test fixture",
            "type_code": "mixed",
            "distance_km": 3.0,
            "estimated_duration_min": 30,
            "steps": [
                {"type": "sbu_block", "drills": [
                    {"name": "High Knees", "seconds": 20, "reps": 2, "drill_extra": "x"},
                    {"name": "Bounds", "seconds": 20, "reps": 2},
                ]},
            ],
        },
    ],
}


class PlanStoreTests(unittest.TestCase):
    def setUp(self):
        # tests/test_000_temp_bootstrap.py replaces tempfile.TemporaryDirectory
        # with a variant that only creates the directory inside __enter__, so
        # this must be entered explicitly rather than just constructed.
        tmp_cm = tempfile.TemporaryDirectory()
        self.tmp_path = Path(tmp_cm.__enter__())
        self.addCleanup(tmp_cm.__exit__, None, None, None)

        self.yaml_path = self.tmp_path / "plan.yaml"
        self.yaml_path.write_text(
            yaml.safe_dump(deepcopy(RAW_PLAN), allow_unicode=True), encoding="utf-8"
        )

        # Reference: what repair_plan_data + plan_from_data produce directly,
        # independent of the store — this is what the store must reproduce.
        repaired_data, _ = repair_plan_data(deepcopy(RAW_PLAN))
        self.expected_plan_data = plan_to_data(plan_from_data(repaired_data))

    def _open_store(self, name="working.workdb"):
        store = PlanStore.open(self.tmp_path / name)
        self.addCleanup(store.close)  # release the sqlite handle before tmpdir cleanup (Windows)
        return store

    def test_load_from_yaml_matches_direct_repair_and_parse(self):
        store = self._open_store()
        store.load_from_yaml(self.yaml_path)

        self.assertEqual(plan_to_data(store.get_plan()), self.expected_plan_data)

    def test_load_from_yaml_returns_repair_notes(self):
        store = self._open_store()
        notes = store.load_from_yaml(self.yaml_path)

        self.assertTrue(any("normalized workout identifier" in n for n in notes))

    def test_back_to_offset_and_step_order_preserved(self):
        store = self._open_store()
        store.load_from_yaml(self.yaml_path)

        steps = store.get_plan().workouts[0].steps
        types = [s.step_type for s in steps]
        self.assertEqual(
            types, ["dist_pace", "dist_hr", "dist_open", "repeat", "dist_pace"]
        )
        repeat_step = steps[3]
        self.assertEqual(repeat_step.back_to_offset, 1)
        self.assertEqual(repeat_step.count, 6)

    def test_extra_fields_survive_round_trip(self):
        store = self._open_store()
        store.load_from_yaml(self.yaml_path)

        plan = store.get_plan()
        self.assertEqual(plan.workouts[0].extra.get("custom_note"), "workout-level extra field")
        self.assertEqual(plan.workouts[0].steps[1].extra.get("coach_tag"), "hard")
        self.assertEqual(
            plan.workouts[1].steps[0].drills[0].extra.get("drill_extra"), "x"
        )

    def test_export_then_reload_is_idempotent(self):
        store_a = self._open_store("a.workdb")
        store_a.load_from_yaml(self.yaml_path)

        export_path = self.tmp_path / "exported.yaml"
        store_a.export_to_yaml(export_path)

        store_b = self._open_store("b.workdb")
        store_b.load_from_yaml(export_path)

        self.assertEqual(plan_to_data(store_a.get_plan()), plan_to_data(store_b.get_plan()))

    def test_write_through_updates_yaml_file_on_mutation(self):
        store = self._open_store()
        store.load_from_yaml(self.yaml_path)
        workout_id = self._workout_ids(store)[0]

        store.rename_workout_filename(workout_id, "W16_04-14_Tue_Intervals_Renamed")

        with open(self.yaml_path, encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        self.assertEqual(on_disk["workouts"][0]["filename"], "W16_04-14_Tue_Intervals_Renamed")
        self.assertEqual(on_disk["workouts"][0]["name"], "W16_04-14_Tue_Intervals_Renamed")

    def test_move_workout_reorders_and_writes_through(self):
        store = self._open_store()
        store.load_from_yaml(self.yaml_path)
        first_id, second_id = self._workout_ids(store)

        store.move_workout(first_id, 1)

        names = [w.filename for w in store.get_plan().workouts]
        self.assertEqual(names[-1], self._filename_for(store, first_id))
        with open(self.yaml_path, encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        self.assertEqual(
            [w["filename"] for w in on_disk["workouts"]],
            [self._filename_for(store, second_id), self._filename_for(store, first_id)],
        )

    def test_duplicate_workout_appends_copy_with_same_steps(self):
        store = self._open_store()
        store.load_from_yaml(self.yaml_path)
        first_id = self._workout_ids(store)[0]

        new_id = store.duplicate_workout(first_id)

        plan = store.get_plan()
        self.assertEqual(len(plan.workouts), 3)
        self.assertNotEqual(new_id, first_id)
        original = next(w for w in plan.workouts if w.filename == self._filename_for(store, first_id))
        duplicated = plan.workouts[-1]
        self.assertEqual(
            [s.step_type for s in duplicated.steps],
            [s.step_type for s in original.steps],
        )

    def test_delete_workout_removes_and_renumbers(self):
        store = self._open_store()
        store.load_from_yaml(self.yaml_path)
        first_id, second_id = self._workout_ids(store)

        store.delete_workout(first_id)

        plan = store.get_plan()
        self.assertEqual(len(plan.workouts), 1)
        self.assertEqual(plan.workouts[0].filename, self._filename_for(store, second_id))
        with open(self.yaml_path, encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        self.assertEqual(len(on_disk["workouts"]), 1)

    def test_validate_delegates_to_plan_validator(self):
        bad_data = deepcopy(RAW_PLAN)
        bad_data["workouts"][0]["steps"][1]["hr_low"] = 200
        bad_data["workouts"][0]["steps"][1]["hr_high"] = 150  # low > high
        bad_yaml_path = self.tmp_path / "bad_plan.yaml"
        bad_yaml_path.write_text(yaml.safe_dump(bad_data, allow_unicode=True), encoding="utf-8")

        store = self._open_store("bad.workdb")
        store.load_from_yaml(bad_yaml_path)

        repaired, _ = repair_plan_data(bad_data)
        direct_errors, direct_warnings = validate_plan_data(plan_to_data(plan_from_data(repaired)))
        store_errors, store_warnings = store.validate()

        self.assertEqual(store_errors, direct_errors)
        self.assertEqual(store_warnings, direct_warnings)
        self.assertTrue(store_errors)  # sanity: the bad fixture actually triggers an error

    # ── helpers ────────────────────────────────────────────────────────────
    def _workout_ids(self, store: PlanStore) -> list[int]:
        cur = store._conn.execute("SELECT id FROM workouts ORDER BY position")
        return [row[0] for row in cur.fetchall()]

    def _filename_for(self, store: PlanStore, workout_id: int) -> str:
        cur = store._conn.execute(
            "SELECT filename FROM workouts WHERE id = ?", (workout_id,)
        )
        return cur.fetchone()[0]


if __name__ == "__main__":
    unittest.main()
