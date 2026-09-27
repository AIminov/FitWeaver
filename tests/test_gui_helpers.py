"""GUI guards that need no display: secrets handling."""

from pathlib import Path

GUI_SOURCE = Path(__file__).resolve().parents[1] / "fitweaver_gui.py"


def test_gui_runs_cli_in_process_and_redacts_logged_args():
    source = GUI_SOURCE.read_text(encoding="utf-8")
    assert "subprocess.Popen(\n                    cmd" not in source
    assert "garmin-fit-cli.exe" not in source
    assert "redact_args(run_args)" in source

