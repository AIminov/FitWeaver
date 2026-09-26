"""Guard: the GUI must never put the Garmin password on a child command line."""

from pathlib import Path

GUI_SOURCE = Path(__file__).resolve().parents[1] / "fitweaver_gui.py"


def test_gui_does_not_pass_password_as_cli_argument():
    source = GUI_SOURCE.read_text(encoding="utf-8")
    assert '"--password"' not in source
    assert '"GARMIN_PASSWORD"' in source
