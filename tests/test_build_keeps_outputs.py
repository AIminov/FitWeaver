"""After a successful build the plan and FIT files stay where the user needs them.

The post-build archive is a snapshot: copies go to Archive/, while the plan
(possibly opened from any folder in the GUI) and Output_fit/*.fit remain.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import garmin_fit.archive_manager as archive_manager
import garmin_fit.build_from_plan as build_from_plan
import garmin_fit.orchestrator as orch
import garmin_fit.plan_artifacts as plan_artifacts
import garmin_fit.state_manager as state_manager

FIXTURE = Path(__file__).parent / "fixtures" / "direct_pipeline_basic.yaml"


class BuildKeepsOutputsTests(unittest.TestCase):
    def test_auto_archive_is_a_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("Output_fit", "Archive", "Plan", "Build_artifacts", "elsewhere"):
                (root / name).mkdir()
            plan = root / "elsewhere" / "my_plan.yaml"
            shutil.copy(FIXTURE, plan)
            out = root / "Output_fit"
            original_build = build_from_plan.build_fit_from_workout

            patches = [
                patch.object(orch, "OUTPUT_DIR", out),
                patch.object(build_from_plan, "OUTPUT_DIR", out),
                patch.object(build_from_plan, "build_fit_from_workout",
                             lambda w, s, t: original_build(w, s, t, output_dir=out)),
                patch.object(archive_manager, "OUTPUT_DIR", out),
                patch.object(archive_manager, "ARCHIVE_DIR", root / "Archive"),
                patch.object(archive_manager, "PLAN_DIR", root / "Plan"),
                patch.object(archive_manager, "PLAN_DONE_DIR", root / "Plan" / "plan_done"),
                patch.object(archive_manager, "ARTIFACTS_DIR", root / "Build_artifacts"),
                patch.object(plan_artifacts, "ARTIFACTS_DIR", root / "Build_artifacts"),
                patch.object(state_manager, "STATE_FILE", root / "state.json"),
                patch.object(state_manager, "LOCK_FILE", root / "state.lock"),
            ]
            for p in patches:
                p.start()
            try:
                result = orch.run_generation_pipeline(plan, cleanup_first=True, auto_archive=True)
            finally:
                for p in reversed(patches):
                    p.stop()

            self.assertTrue(result["success"], result["errors"])
            self.assertTrue(plan.exists(), "plan must stay where the user keeps it")
            self.assertEqual(len(list(out.glob("*.fit"))), 2, "FIT files must stay in Output_fit")
            archived = result["archive_path"]
            self.assertEqual(len(list((archived / "output_fit").glob("*.fit"))), 2)
            self.assertTrue((archived / "my_plan.yaml").exists())


if __name__ == "__main__":
    unittest.main()
