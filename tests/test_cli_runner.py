import logging
import tempfile
import unittest
from pathlib import Path

from garmin_fit import workflow
from garmin_fit.cli_runner import redact_args, run_cli_captured

FIXTURES = Path(__file__).parent / "fixtures"


class CliRunnerTests(unittest.TestCase):
    def _run(self, args):
        lines: list[str] = []
        code = run_cli_captured(args, lines.append)
        return code, lines

    def test_valid_plan_runs_in_process_and_captures_output(self):
        code, lines = self._run(["validate-yaml", "--plan", str(FIXTURES / "direct_pipeline_basic.yaml")])
        self.assertEqual(code, 0)
        self.assertTrue(any("YAML VALIDATION" in line for line in lines))

    def test_invalid_plan_returns_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "bad.yaml"
            plan.write_text("workouts:\n  - filename: A\n    name: B\n    steps: []\n", encoding="utf-8")
            code, _lines = self._run(["validate-yaml", "--plan", str(plan)])
        self.assertEqual(code, 1)

    def test_argparse_error_is_an_exit_code_not_an_exception(self):
        code, lines = self._run(["no-such-command"])
        self.assertEqual(code, 2)
        self.assertTrue(any("invalid choice" in line for line in lines))

    def test_gui_logger_records_are_not_echoed(self):
        lines: list[str] = []
        logging.getLogger("garmin_fit.gui").setLevel(logging.INFO)

        def on_line(line):
            lines.append(line)
            logging.getLogger("garmin_fit.gui").info(line)  # what the GUI panel does

        run_cli_captured(["validate-yaml", "--plan", str(FIXTURES / "direct_pipeline_basic.yaml")], on_line)
        self.assertLess(len(lines), 200)

    def test_redact_args_hides_password(self):
        self.assertEqual(
            redact_args(["garmin-calendar", "--password", "s3cret", "--dry-run"]),
            ["garmin-calendar", "--password", "***", "--dry-run"],
        )


class RunStepTests(unittest.TestCase):
    def test_module_step_runs_in_process(self):
        # sys.executable -m would break inside the packaged exe.
        self.assertEqual(workflow.run_step("List Archives", module_name="garmin_fit.archive_manager", args=["list"]), 0)

    def test_module_step_argparse_error_becomes_exit_code(self):
        code = workflow.run_step("Bad", module_name="garmin_fit.archive_manager", args=["bogus"])
        self.assertNotEqual(code, 0)

    def test_confirmation_without_stdin_cancels(self):
        from unittest.mock import patch

        with patch("builtins.input", side_effect=RuntimeError("input(): lost sys.stdin")):
            self.assertFalse(workflow._confirm("Continue? ", assume_yes=False))
        self.assertTrue(workflow._confirm("Continue? ", assume_yes=True))


if __name__ == "__main__":
    unittest.main()
