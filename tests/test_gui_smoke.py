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


def test_gui_main_flows(tmp_path):
    sys.path.insert(0, str(ROOT))
    import fitweaver_gui
    from garmin_fit import config, logging_utils, profile_store

    stubs = [
        patch.object(fitweaver_gui, "SESSION_FILE", tmp_path / ".gui_session.json"),
        patch.object(fitweaver_gui, "PROJECT_ROOT", tmp_path),
        patch.object(profile_store, "PROFILES_ROOT", tmp_path / "profiles"),
        patch.object(config, "ARTIFACTS_DIR", tmp_path / "artifacts"),
        patch.object(logging_utils, "setup_file_logging", lambda *a, **k: None),
        patch("urllib.request.urlopen", side_effect=OSError("offline in tests")),
        patch.object(fitweaver_gui.messagebox, "showwarning", lambda *a, **k: None),
        patch.object(fitweaver_gui.messagebox, "showinfo", lambda *a, **k: None),
        patch.object(fitweaver_gui.messagebox, "askyesno", lambda *a, **k: True),
    ]
    for stub in stubs:
        stub.start()
    try:
        try:
            app = fitweaver_gui.App()
        except fitweaver_gui.tk.TclError as exc:
            # No display (Linux CI) or a broken Tcl install on the runner.
            pytest.skip(f"Tk is not usable here: {exc}")
        app.withdraw()
        log_lines: list[str] = []
        original_log = app._log

        def capture(text):
            log_lines.append(str(text))
            original_log(text)

        app._log = capture
        results: dict[str, object] = {}
        deadline = time.time() + 60

        def callback_error(exc_type, value, traceback):
            results["callback_error"] = f"{exc_type.__name__}: {value}"
            app.quit()

        app.report_callback_exception = callback_error
        app.after(60000, app.quit)

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

        plan_copy = tmp_path / "plans" / "plan.yaml"
        plan_copy.parent.mkdir()
        plan_copy.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

        def step_load_plan():
            app.yaml_path.set(str(plan_copy))
            app._reload_yaml()
            results["loaded_workouts"] = len(app.workouts)
            results["sibling_files"] = sorted(p.name for p in plan_copy.parent.iterdir())
            step_marked()

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
            # An editor opened for A must not write into B even when both
            # disposable databases assign workout ID 1.
            app._show_detail(app.workouts[0])
            app._edit_selected_workout()
            second_plan = plan_copy.with_name("second.yaml")
            second_plan.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            app.yaml_path.set(str(second_plan))
            app._reload_yaml()
            before = second_plan.read_bytes()
            app._builder_filename_var.set("must_not_overwrite_second_plan")
            app._builder_save_edit()
            results["editor_isolated"] = second_plan.read_bytes() == before
            results["draft_retained"] = bool(app._builder_steps)
            draft = app._draft_snapshot()
            results["draft_saved"] = app._save_drafts()
            app._active_profile_email = "other@example.test"
            app._restore_drafts()
            results["draft_isolated"] = not any(app._draft_snapshot().values())
            app._active_profile_email = ""
            app._restore_drafts()
            results["draft_restored"] = app._draft_snapshot() == draft
            results["draft_detached"] = app._builder_edit_workout_id is None
            app._builder_clear_action()
            app._builder_history_move()
            results["undo_restores_draft"] = app._draft_snapshot() == draft
            app._builder_history_move(redo=True)
            results["redo_clears_draft"] = not app._builder_steps
            app._builder_history_move()
            app._builder_delete(0)
            results["new_edit_discards_redo"] = not app._builder_redo_stack
            app._builder_clear()
            app._plan_text.delete("1.0", "end")
            app._show_generated("")
            app._save_drafts()
            app._restore_drafts()
            results["draft_cleared"] = not any(app._draft_snapshot().values())
            app.yaml_path.set("")
            results["empty_context_closed_store"] = app._store is None
            app.quit()

        app.after(200, step_load_plan)
        app.mainloop()
        app.destroy()
    finally:
        for stub in reversed(stubs):
            stub.stop()

    assert not results.get("timeout"), results
    assert not results.get("callback_error"), results
    assert results["loaded_workouts"] >= 1
    assert results["sibling_files"] == ["plan.yaml"]  # no *.workdb beside the user's plan
    assert "Разобрано без LLM — 3 тренировки" in results["status"]
    assert str(results["yaml"]).startswith("workouts:")
    assert str(results["text_view"]).lstrip().startswith("==== ТРЕНИРОВКА")
    assert str(results["editor"]).startswith("==== ТРЕНИРОВКА")
    assert results["validate_result"] == "[OK] Готово"
    assert results["validate_seconds"] < 10  # in-process, no exe start-up
    assert results["editor_isolated"]
    assert results["draft_retained"]
    assert results["draft_saved"] and results["draft_isolated"]
    assert results["draft_restored"] and results["draft_detached"] and results["draft_cleared"]
    assert results["undo_restores_draft"] and results["redo_clears_draft"]
    assert results["new_edit_discards_redo"]
    assert results["empty_context_closed_store"]
    assert not any("topsecret-password" in line for line in log_lines)
    assert any("--password ***" in line for line in log_lines)
