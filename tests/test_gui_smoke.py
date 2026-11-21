"""End-to-end GUI smoke under a real Tk mainloop (skipped without a display).

Exercises the flows that broke silently before: marked text compiled without
the LLM, the result shown as marked text and put back into the editor, a CLI
command run in-process (fast, logged) and the Garmin password redacted in the
log. Session, profiles and logs go to a temporary directory; network and
dialogs are stubbed.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "marked_plan_example.txt"
FIXTURE = ROOT / "tests" / "fixtures" / "direct_pipeline_basic.yaml"


def test_gui_main_flows(tmp_path):
    sys.path.insert(0, str(ROOT))
    import fitweaver_gui
    from garmin_fit import config, logging_utils, profile_store

    def unexpected_dialog(title, message, **kwargs):
        raise AssertionError(f"{title}: {message}")

    stubs = [
        patch.object(fitweaver_gui, "SESSION_FILE", tmp_path / ".gui_session.json"),
        patch.object(fitweaver_gui, "PROJECT_ROOT", tmp_path),
        patch.object(profile_store, "PROFILES_ROOT", tmp_path / "profiles"),
        patch.object(config, "ARTIFACTS_DIR", tmp_path / "artifacts"),
        patch.object(logging_utils, "setup_file_logging", lambda *a, **k: None),
        patch("urllib.request.urlopen", side_effect=OSError("offline in tests")),
        patch.object(fitweaver_gui.messagebox, "showwarning", lambda *a, **k: None),
        patch.object(fitweaver_gui.messagebox, "showerror", unexpected_dialog),
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
            results["text_view"] = app._yaml_out.get("1.0", "end")
            app._toggle_out_view()
            results["yaml_view"] = app._yaml_out.get("1.0", "end")
            app._toggle_out_view()
            app._generated_to_editor()
            results["editor"] = app._plan_text.get("1.0", "end")
            results["t0"] = time.time()
            app._run(["validate-yaml", "--plan", str(FIXTURE)])
            wait_then(lambda: len(done_lines()) >= 1 and not app._operation_active, step_garmin)

        def step_garmin():
            results["validate_seconds"] = time.time() - results["t0"]
            results["validate_result"] = done_lines()[-1]
            app.pass_var.set("topsecret-password")
            app._run(["garmin-calendar", "--plan", str(FIXTURE), "--dry-run"])
            wait_then(lambda: len(done_lines()) >= 2 and not app._operation_active, finish)

        def finish():
            app.pass_var.set("")

            def drop(workout, day, *, copy=False):
                app._drag_moved = True
                event = SimpleNamespace(x_root=0, y_root=0, state=4 if copy else 0)
                with patch.object(app, "_cell_date_at_root_coords", return_value=day):
                    app._calendar_drag_release(event, workout)

            original = app.workouts[0]
            count = len(app.workouts)
            drop(original, "2026-10-12")
            moved = app.workouts[0]
            drop(moved, "2026-10-13", copy=True)
            copied = app.workouts[-1]
            results["calendar_copy"] = len(app.workouts) == count + 1
            app._calendar_history_move()
            app._calendar_history_move()
            results["calendar_undo"] = len(app.workouts) == count and app.workouts[0] == original
            app._calendar_history_move(redo=True)
            app._calendar_history_move(redo=True)
            results["calendar_redo"] = app.workouts[0] == moved and app.workouts[-1] == copied
            app._calendar_history_move()
            app._calendar_history_move()
            # An editor opened for A must not write into B even when both
            # disposable databases assign workout ID 1.
            app._show_detail(app.workouts[0])
            app._edit_selected_workout()
            second_plan = plan_copy.with_name("second.yaml")
            second_plan.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            app.yaml_path.set(str(second_plan))
            app._reload_yaml()
            results["calendar_history_isolated"] = not (app._calendar_undo or app._calendar_redo)
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
            check_late_result(cancel=True)

        def check_late_result(*, cancel):
            release = threading.Event()
            started = threading.Event()

            def generate(*args, **kwargs):
                started.set()
                if not release.wait(5):
                    raise TimeoutError("GUI did not release the fake model")
                return SimpleNamespace(
                    yaml_text=results["yaml"], warnings=[], repairs=[], validation_errors=[],
                )

            app.llm_conn_mode.set("api")
            app._plan_text.delete("1.0", "end")
            app._plan_text.insert("1.0", "Slow model request")
            with patch.object(app, "_make_llm_client", return_value=SimpleNamespace(build_plan_draft=generate)):
                app._llm_generate()

            def change_input():
                try:
                    if cancel:
                        results["cancel_available"] = str(app._cancel_btn.cget("state")) == "normal"
                        app._cancel_btn.invoke()
                        results["cancel_progress"] = "Отменяю" in app._llm_progress.cget("text")
                    else:
                        app._plan_text.insert("end", " edited")
                finally:
                    release.set()
                wait_then(lambda: not app._operation_active, check_result)

            def check_result():
                status = app._llm_progress.cget("text")
                if cancel:
                    results["cancel_discarded"] = not app._generated_yaml and "отменена" in status
                    check_late_result(cancel=False)
                else:
                    results["stale_discarded"] = not app._generated_yaml and "изменились" in status
                    app.quit()

            wait_then(started.is_set, change_input)

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
    assert "•" in results["text_view"]
    assert "**** ШАГ ****" not in results["text_view"]
    assert str(results["yaml_view"]).startswith("workouts:")
    assert str(results["editor"]).startswith("==== ТРЕНИРОВКА")
    assert results["validate_result"] == "[OK] Готово"
    assert results["validate_seconds"] < 10  # in-process, no exe start-up
    assert results["editor_isolated"]
    assert results["draft_retained"]
    assert results["calendar_copy"] and results["calendar_undo"] and results["calendar_redo"]
    assert results["calendar_history_isolated"]
    assert results["draft_saved"] and results["draft_isolated"]
    assert results["draft_restored"] and results["draft_detached"] and results["draft_cleared"]
    assert results["undo_restores_draft"] and results["redo_clears_draft"]
    assert results["new_edit_discards_redo"]
    assert results["empty_context_closed_store"]
    assert results["cancel_available"] and results["cancel_progress"] and results["cancel_discarded"]
    assert results["stale_discarded"]
    assert not any("topsecret-password" in line for line in log_lines)
    assert any("--password ***" in line for line in log_lines)
