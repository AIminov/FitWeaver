import unittest

from garmin_fit.plan_domain import WorkoutStep
from garmin_fit.workout_builder import (
    BLOCK_DEFS,
    TEMPLATES,
    compute_repeat_step,
    delete_step_from_draft,
    validate_draft,
)


class ComputeRepeatStepTests(unittest.TestCase):
    def setUp(self):
        self.steps = [
            WorkoutStep(step_type="dist_open", intensity="warmup", km=2.0),
            WorkoutStep(step_type="dist_hr", intensity="active", km=0.8, hr_low=160, hr_high=170),
            WorkoutStep(step_type="dist_hr", intensity="recovery", km=0.4, hr_low=130, hr_high=145),
            WorkoutStep(step_type="dist_open", intensity="cooldown", km=1.0),
        ]

    def test_computes_back_to_offset_from_selected_range(self):
        repeat = compute_repeat_step(self.steps, start_position=1, end_position=2, count=6)
        self.assertEqual(repeat.step_type, "repeat")
        self.assertEqual(repeat.back_to_offset, 1)
        self.assertEqual(repeat.count, 6)

    def test_single_step_range(self):
        repeat = compute_repeat_step(self.steps, start_position=1, end_position=1, count=3)
        self.assertEqual(repeat.back_to_offset, 1)
        self.assertEqual(repeat.count, 3)

    def test_rejects_out_of_bounds_range(self):
        with self.assertRaises(ValueError):
            compute_repeat_step(self.steps, start_position=0, end_position=10, count=2)

    def test_rejects_inverted_range(self):
        with self.assertRaises(ValueError):
            compute_repeat_step(self.steps, start_position=3, end_position=1, count=2)

    def test_rejects_non_positive_count(self):
        with self.assertRaises(ValueError):
            compute_repeat_step(self.steps, start_position=1, end_position=2, count=0)

    def test_rejects_range_containing_existing_repeat_step(self):
        steps = self.steps + [WorkoutStep(step_type="repeat", back_to_offset=1, count=4)]
        with self.assertRaises(ValueError):
            compute_repeat_step(steps, start_position=0, end_position=4, count=2)

    def test_rejects_range_overlapping_existing_repeat_group_start(self):
        steps = self.steps + [WorkoutStep(step_type="repeat", back_to_offset=1, count=4)]
        # range [0, 1] doesn't contain the repeat step (position 4) but does
        # contain position 1, which the existing repeat step's back_to_offset
        # points at -- would create an overlapping/ambiguous group.
        with self.assertRaises(ValueError):
            compute_repeat_step(steps, start_position=0, end_position=1, count=2)

    def test_delete_before_repeat_shifts_anchor_left(self):
        steps = self.steps + [WorkoutStep(step_type="repeat", back_to_offset=1, count=4)]
        delete_step_from_draft(steps, 0)
        self.assertEqual(steps[-1].back_to_offset, 0)

    def test_delete_repeat_anchor_is_rejected(self):
        steps = self.steps + [WorkoutStep(step_type="repeat", back_to_offset=1, count=4)]
        with self.assertRaises(ValueError):
            delete_step_from_draft(steps, 1)

    def test_delete_step_after_anchor_keeps_repeat_offset(self):
        steps = self.steps + [WorkoutStep(step_type="repeat", back_to_offset=1, count=4)]
        delete_step_from_draft(steps, 2)
        self.assertEqual(steps[-1].back_to_offset, 1)


class BlockDefsTests(unittest.TestCase):
    def test_every_block_makes_a_step_of_its_declared_type(self):
        for key, block_def in BLOCK_DEFS.items():
            step = block_def.make()
            self.assertEqual(step.step_type, block_def.step_type, key)

    def test_sbu_block_gets_default_drills(self):
        step = BLOCK_DEFS["sbu"].make()
        self.assertTrue(step.drills)
        self.assertTrue(all(d.name for d in step.drills))

    def test_non_sbu_blocks_have_no_drills(self):
        for key, block_def in BLOCK_DEFS.items():
            if key == "sbu":
                continue
            step = block_def.make()
            self.assertIsNone(step.drills, key)


class TemplatesTests(unittest.TestCase):
    def test_every_template_produces_a_valid_draft(self):
        for key, (label, factory) in TEMPLATES.items():
            steps = factory()
            errors, warnings = validate_draft(f"W01_{key}", f"W01_{key}", steps)
            self.assertEqual(errors, [], f"{key} ({label}) should validate cleanly")

    def test_intervals_template_has_correct_back_to_offset(self):
        steps = TEMPLATES["intervals"][1]()
        repeat_step = next(s for s in steps if s.step_type == "repeat")
        self.assertEqual(repeat_step.back_to_offset, 1)


class ValidateDraftTests(unittest.TestCase):
    def test_reports_missing_required_field(self):
        steps = [WorkoutStep(step_type="dist_hr", intensity="active", km=None,
                              hr_low=150, hr_high=160)]
        errors, warnings = validate_draft("W01_test", "W01_test", steps)
        self.assertTrue(errors)

    def test_empty_step_list_is_reported_not_raised(self):
        errors, warnings = validate_draft("W01_test", "W01_test", [])
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
