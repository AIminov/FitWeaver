"""End-to-end GUI smoke under a real Tk mainloop (skipped without a display).

Exercises the flows that broke silently before: marked text compiled without
the LLM, the result shown as marked text and put back into the editor, a CLI
command run in-process (fast, logged) and the Garmin password redacted in the
log. Session, profiles and logs go to a temporary directory; network and
dialogs are stubbed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "marked_plan_example.txt"
FIXTURE = ROOT / "tests" / "fixtures" / "direct_pipeline_basic.yaml"


def _tk_available() -> bool:
    try:
        import tkinter

        root = tkinter.Tk()
        root.destroy()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _tk_available(), reason="no display for Tk")


def test_gui_main_flows(tmp_path):
    sys.path.insert(0, str(ROOT))
    import fitweaver_gui
    from garmin_fit import logging_utils, profile_store

    stubs = [
        patch.object(fitweaver_gui, "SESSION_FILE", tmp_path / ".gui_session.json"),
        patch.object(fitweaver_gui, "PROJECT_ROOT", tmp_path),
        patch.object(profile_store, "PROFILES_ROOT", tmp_path / "profiles"),
        patch.object(logging_utils, "setup_file_logging", lambda *a, **k: None),
        patch("urllib.request.urlopen", side_effect=OSError("offline in tests")),
        patch.object(fitweaver_gui.messagebox, "showwarning", lambda *a, **k: None),
        patch.object(fitweaver_gui.messagebox, "showinfo", lambda *a, **k: None),
        patch.object(fitweaver_gui.messagebox, "askyesno", lambda *a, **k: True),
    ]
    for stub in stubs:
        stub.start()
    try:
        app = fitweaver_gui.App()
        app.withdraw()
        log_lines: list[str] = []
        original_log = app._log

        def capture(text):
            log_lines.append(str(text))
            original_log(text)

        app._log = capture
        results: dict[str, object] = {}
        deadline = time.time() + 60

        def done_lines():
            return [line for line in log_lines if line == "[OK] Готово" or line.startswith("[FAIL] код")]

        def wait_then(check, then):
            def poll():
                if check():
                    then()
                elif time.time() > deadline:
                    results["timeout"] = True
                    app.quit()
                else:
                    app.after(50, poll)
            app.after(50, poll)

        def step_marked():
            app._nb.select(1)
            app._plan_text.delete("1.0", "end")
            app._plan_text.insert("1.0", EXAMPLE.read_text(encoding="utf-8"))
            app._llm_generate()
            wait_then(lambda: "Разобрано без LLM" in app._llm_progress.cget("text")
                      or "❌" in app._llm_progress.cget("text"), step_views)

        def step_views():
            results["status"] = app._llm_progress.cget("text")
            results["yaml"] = app._generated_yaml
            app._toggle_out_view()
            results["text_view"] = app._yaml_out.get("1.0", "end")
            app._toggle_out_view()
            app._generated_to_editor()
            results["editor"] = app._plan_text.get("1.0", "end")
            results["t0"] = time.time()
            app._run(["validate-yaml", "--plan", str(FIXTURE)])
            wait_then(lambda: len(done_lines()) >= 1, step_garmin)

        def step_garmin():
            results["validate_seconds"] = time.time() - results["t0"]
            results["validate_result"] = done_lines()[-1]
            app.pass_var.set("topsecret-password")
            app._run(["garmin-calendar", "--plan", str(FIXTURE), "--dry-run"])
            wait_then(lambda: len(done_lines()) >= 2, finish)

        def finish():
            app.pass_var.set("")
            app.quit()

        app.after(200, step_marked)
        app.mainloop()
        app.destroy()
    finally:
        for stub in reversed(stubs):
            stub.stop()

    assert not results.get("timeout"), results
    assert "Разобрано без LLM — 3 тренировки" in results["status"]
    assert str(results["yaml"]).startswith("workouts:")
    assert str(results["text_view"]).lstrip().startswith("==== ТРЕНИРОВКА")
    assert str(results["editor"]).startswith("==== ТРЕНИРОВКА")
    assert results["validate_result"] == "[OK] Готово"
    assert results["validate_seconds"] < 10  # in-process, no exe start-up
    assert not any("topsecret-password" in line for line in log_lines)
    assert any("--password ***" in line for line in log_lines)
