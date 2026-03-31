import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import Scripts.compare_build_modes as compare_build_modes


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class CompareBuildModesTests(unittest.TestCase):
    def test_compare_build_modes_matches_on_basic_fixture(self):
        fixture_path = FIXTURES_DIR / "direct_pipeline_basic.yaml"

        with tempfile.TemporaryDirectory() as tmp:
            artifacts_dir = Path(tmp) / "Build_artifacts"
            result = compare_build_modes.compare_build_modes(
                fixture_path,
                validate_strict=False,
                artifacts_dir=artifacts_dir,
            )
            self.assertTrue(result["matches"], result["mismatches"])
            self.assertEqual(result["direct"]["build_mode"], "direct")
            self.assertEqual(result["templates"]["build_mode"], "templates")
            self.assertEqual(result["direct"]["built_count"], 2)
            self.assertEqual(result["templates"]["built_count"], 2)
            self.assertEqual(result["direct"]["template_export_count"], 0)
            self.assertEqual(result["templates"]["template_export_count"], 2)
            self.assertEqual(result["mismatches"], [])
            self.assertTrue(result["compare_report_path"].exists())

            report_data = json.loads(result["compare_report_path"].read_text(encoding="utf-8"))
            self.assertTrue(report_data["matches"])
            self.assertEqual(report_data["mismatch_count"], 0)

    @patch("Scripts.compare_build_modes._run_mode_in_temp")
    def test_compare_build_modes_reports_fit_content_mismatch(self, run_mode_mock):
        direct_snapshot = {
            "build_mode": "direct",
            "success": True,
            "built_count": 1,
            "build_total_count": 1,
            "valid_count": 1,
            "total_count": 1,
            "template_export_count": 0,
            "template_export_total_count": 0,
            "fit_files": ["sample.fit"],
            "fit_summaries": {
                "sample.fit": {
                    "valid": True,
                    "workout": {"name": "SAMPLE", "num_valid_steps": 1},
                    "steps": [{"message_index": 0, "duration_type": "time"}],
                }
            },
            "errors": [],
        }
        templates_snapshot = {
            "build_mode": "templates",
            "success": True,
            "built_count": 1,
            "build_total_count": 1,
            "valid_count": 1,
            "total_count": 1,
            "template_export_count": 1,
            "template_export_total_count": 1,
            "fit_files": ["sample.fit"],
            "fit_summaries": {
                "sample.fit": {
                    "valid": True,
                    "workout": {"name": "SAMPLE", "num_valid_steps": 2},
                    "steps": [{"message_index": 0, "duration_type": "time"}],
                }
            },
            "errors": [],
        }
        run_mode_mock.side_effect = [direct_snapshot, templates_snapshot]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            yaml_path = root / "plan.yaml"
            yaml_path.write_text("workouts: []\n", encoding="utf-8")

            result = compare_build_modes.compare_build_modes(
                yaml_path,
                artifacts_dir=root / "Build_artifacts",
            )
            self.assertFalse(result["matches"])
            self.assertEqual(result["mismatch_count"], 1)
            self.assertEqual(result["mismatches"][0]["type"], "fit_content_mismatch")
            self.assertTrue(result["compare_report_path"].exists())


if __name__ == "__main__":
    unittest.main()
