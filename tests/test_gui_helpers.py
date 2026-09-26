"""GUI guards that need no display: secrets handling and Russian plural forms."""

from pathlib import Path

GUI_SOURCE = Path(__file__).resolve().parents[1] / "fitweaver_gui.py"


def test_gui_runs_cli_in_process_and_redacts_logged_args():
    source = GUI_SOURCE.read_text(encoding="utf-8")
    assert "subprocess.Popen(\n                    cmd" not in source
    assert "garmin-fit-cli.exe" not in source
    assert "redact_args(run_args)" in source


def test_russian_plural_forms():
    import sys

    sys.path.insert(0, str(GUI_SOURCE.parent))
    import fitweaver_gui

    assert [fitweaver_gui.ru_workouts(n) for n in (1, 3, 5, 11, 21, 22, 112)] == [
        "1 тренировка", "3 тренировки", "5 тренировок", "11 тренировок",
        "21 тренировка", "22 тренировки", "112 тренировок",
    ]
