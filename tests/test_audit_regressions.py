"""Regressions for desktop plan isolation and preservation of user files."""
import sqlite3
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitweaver_gui as gui
from garmin_fit import archive_manager, orchestrator, plan_artifacts
from garmin_fit.plan_domain import WorkoutStep, plan_to_data
from garmin_fit.plan_store import _SCHEMA, PlanStore


@pytest.fixture
def store_factory(tmp_path):
    stores = []

    def create(name="plan", steps=None, legacy=False):
        path = tmp_path / f"{name}.yaml"
        path.write_text(yaml.safe_dump({"workouts": [{"filename": name, "name": name,
            "steps": steps or [{"type": "time_step", "seconds": 60}]}]}), encoding="utf-8")
        db = tmp_path / f"{name}.db"
        if legacy:
            with sqlite3.connect(db) as conn:
                conn.executescript(_SCHEMA.replace("cad_low TEXT, cad_high TEXT, ", ""))
        store = PlanStore.open(db)
        stores.append(store)
        store.load_from_yaml(path)
        return store, path

    yield create
    for store in stores:
        store.close()


@pytest.mark.parametrize("legacy", [False, True])
def test_all_step_types_survive_store_and_yaml(store_factory, legacy):
    steps = [
        {"type": "dist_open", "km": 1},
        {"type": "time_step", "seconds": 60},
        {"type": "open_step"},
        {"type": "dist_hr", "km": 1, "hr_low": 120, "hr_high": 140},
        {"type": "time_hr", "seconds": 60, "hr_low": 120, "hr_high": 140},
        {"type": "dist_pace", "km": 1, "pace_fast": "5:00", "pace_slow": "5:30"},
        {"type": "time_pace", "seconds": 60, "pace_fast": "5:00", "pace_slow": "5:30"},
        {"type": "dist_cadence", "km": 1, "cad_low": 170, "cad_high": 180},
        {"type": "time_cadence", "seconds": 60, "cad_low": 165, "cad_high": 175},
        {"type": "sbu_block", "drills": [{"name": "Skip", "seconds": 20, "reps": 2}]},
        {"type": "repeat", "back_to_offset": 7, "count": 2},
    ]
    store, path = store_factory(steps=steps, legacy=legacy)
    assert store.validate()[0] == []
    store.rename_workout_filename(1, "renamed")
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))["workouts"][0]["steps"]
    for expected, actual in zip(steps, saved, strict=True):
        assert all(actual.get(key) == value for key, value in expected.items())
    from garmin_fit.build_from_plan import build_workout_steps
    from garmin_fit.garmin_step_mapper import map_workout
    workout = store.get_plan().workouts[0]
    assert build_workout_steps(workout)
    assert map_workout(workout)


@pytest.mark.parametrize("operation", ["rename", "replace", "add", "duplicate", "delete"])
def test_failed_file_write_restores_store_and_ids(store_factory, operation):
    store, path = store_factory()
    before = plan_to_data(store.get_plan())
    raw = path.read_bytes()
    revision = store.revision
    with patch("garmin_fit.plan_store.atomic_write_text", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            if operation == "rename":
                store.rename_workout_filename(1, "changed")
            elif operation == "replace":
                store.replace_workout_steps(1, [WorkoutStep(step_type="time_step", seconds=999)])
            elif operation == "add":
                store.add_workout("new", "new", steps=[WorkoutStep(step_type="time_step", seconds=60)])
            elif operation == "duplicate":
                store.duplicate_workout(1)
            else:
                store.delete_workout(1)
    assert path.read_bytes() == raw
    assert plan_to_data(store.get_plan()) == before
    assert store.revision == revision
    assert store.find_workout_id_by_filename(before["workouts"][0]["filename"]) == 1
    store.rename_workout_filename(1, "successful")
    assert len(yaml.safe_load(path.read_text())["workouts"]) == 1


def test_external_edit_is_not_overwritten(store_factory):
    store, path = store_factory()
    before = plan_to_data(store.get_plan())
    path.write_text("# edited elsewhere\nworkouts: []", encoding="utf-8")
    with pytest.raises(ValueError, match="вне редактора"):
        store.rename_workout_filename(1, "changed")
    assert "edited elsewhere" in path.read_text()
    assert plan_to_data(store.get_plan()) == before


def test_duplicate_insertion_and_rename_do_not_write(store_factory):
    store, path = store_factory()
    name = store.get_plan().workouts[0].filename
    before = path.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        store.add_workout(name, name, steps=[WorkoutStep(step_type="time_step", seconds=60)])
    assert path.read_bytes() == before
    copy_id = store.duplicate_workout(1)
    assert store.validate()[0] == []
    before = path.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        store.rename_workout_filename(copy_id, name)
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["store", "profile", "revision"])
def test_editor_rejects_changed_context(store_factory, change):
    store, path = store_factory()
    other, other_path = store_factory("other")
    app = SimpleNamespace(_store=store, _active_profile_email="a@example.test",
        yaml_path=SimpleNamespace(get=lambda: str(path)),
        _builder_edit_workout_id=1, _builder_steps=deepcopy(store.get_plan().workouts[0].steps),
        _builder_filename_var=SimpleNamespace(get=lambda: "changed"))
    app._current_plan_context = lambda: gui.App._current_plan_context(app)
    app._builder_edit_context = app._current_plan_context()
    if change == "store":
        app._store = other
    elif change == "profile":
        app._active_profile_email = "b@example.test"
    else:
        store.rename_workout_filename(1, "updated")
    before = (path.read_bytes(), other_path.read_bytes())
    with patch.object(gui.messagebox, "showwarning") as warning:
        gui.App._builder_save_edit(app)
    warning.assert_called_once()
    assert (path.read_bytes(), other_path.read_bytes()) == before


@pytest.mark.parametrize("change", ["path", "content", "profile", "none"])
def test_validation_result_matches_exact_input(tmp_path, change):
    path = tmp_path / "plan.yaml"
    path.write_text("workouts: []")
    app = SimpleNamespace(_active_profile_email="a", _set_yaml_status=Mock(), _result_var=Mock(),
        yaml_path=SimpleNamespace(get=lambda: str(path)))
    app._validation_context = lambda args: gui.App._validation_context(app, args)
    args = ["validate-yaml", "--plan", str(path)]
    context = app._validation_context(args)
    if change == "path":
        app.yaml_path = SimpleNamespace(get=lambda: str(tmp_path / "other.yaml"))
    elif change == "content":
        path.write_text("# changed\nworkouts: []")
    elif change == "profile":
        app._active_profile_email = "b"
    gui.App._handle_cli_result(app, args, True, context)
    assert app._set_yaml_status.call_args.kwargs["ready"] is (change == "none")


def test_failed_real_build_preserves_previous_fits(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    previous = out / "previous.fit"
    previous.write_bytes(b"previous build")
    path = tmp_path / "broken.yaml"
    path.write_text("workouts: [")
    with patch.object(orchestrator, "OUTPUT_DIR", out), patch.object(
        plan_artifacts, "ARTIFACTS_DIR", tmp_path / "artifacts"
    ):
        result = orchestrator.run_generation_pipeline(path)
    assert not result["success"]
    assert result["fit_files"] == []
    assert previous.read_bytes() == b"previous build"


@pytest.mark.parametrize("failure", ["partial", "invalid_fit"])
def test_failed_staged_output_is_not_published(tmp_path, store_factory, failure):
    _, path = store_factory()
    out = tmp_path / "out"
    out.mkdir()
    (out / "previous.fit").write_bytes(b"previous build")

    def build(_path, *, output_dir):
        (output_dir / "new.fit").write_bytes(b"new build")
        return (1, 2) if failure == "partial" else (1, 1)

    with patch.object(orchestrator, "OUTPUT_DIR", out), patch.object(
        plan_artifacts, "ARTIFACTS_DIR", tmp_path / "artifacts"
    ), patch.object(orchestrator, "build_all_fits_from_plan", side_effect=build), patch.object(
        orchestrator, "validate_directory", return_value=(0, 1) if failure == "invalid_fit" else (1, 1)
    ):
        result = orchestrator.run_generation_pipeline(path)
    assert not result["success"]
    assert result["fit_files"] == []
    assert (out / "previous.fit").read_bytes() == b"previous build"
    assert not (out / "new.fit").exists()


def test_publish_failure_restores_previous_fits(tmp_path):
    out, staging = tmp_path / "out", tmp_path / "staging"
    out.mkdir()
    staging.mkdir()
    (out / "a.fit").write_bytes(b"old")
    (out / "keep.txt").write_bytes(b"keep")
    (staging / "a.fit").write_bytes(b"new")
    (staging / "b.fit").write_bytes(b"new")
    replace = Path.replace

    def fail_second(path, target):
        if path.name == "b.fit":
            raise OSError("locked")
        return replace(path, target)

    with patch.object(Path, "replace", fail_second), pytest.raises(OSError):
        orchestrator._publish_fits(staging, out)
    assert (out / "a.fit").read_bytes() == b"old"
    assert (out / "keep.txt").read_bytes() == b"keep"
    assert not (out / "b.fit").exists()


def test_failed_rollback_retains_recovery_backup(tmp_path):
    out, staging = tmp_path / "out", tmp_path / "staging"
    out.mkdir()
    staging.mkdir()
    (out / "a.fit").write_bytes(b"original")
    (staging / "a.fit").write_bytes(b"replacement")
    import shutil
    copy = shutil.copy2

    def fail_restore(source, target):
        if Path(target).parent == out:
            raise OSError("output unavailable")
        return copy(source, target)

    with patch.object(Path, "replace", side_effect=OSError("publish failure")), patch.object(
        orchestrator.shutil, "copy2", side_effect=fail_restore
    ), pytest.raises(OSError, match="retained in"):
        orchestrator._publish_fits(staging, out)
    backups = list(tmp_path.glob(".fit-backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "a.fit").read_bytes() == b"original"


def test_successful_publication_replaces_only_fits(tmp_path):
    out, staging = tmp_path / "out", tmp_path / "staging"
    out.mkdir()
    staging.mkdir()
    (out / "old.fit").write_bytes(b"old")
    (out / "notes.txt").write_bytes(b"keep")
    (staging / "new.fit").write_bytes(b"new")
    orchestrator._publish_fits(staging, out)
    assert not (out / "old.fit").exists()
    assert (out / "notes.txt").read_bytes() == b"keep"
    assert (out / "new.fit").read_bytes() == b"new"


def test_archive_cli_routes_selected_plan(tmp_path):
    from garmin_fit import cli, workflow
    selected = tmp_path / "selected.yaml"
    selected.write_text("workouts: []")
    with patch.object(workflow, "workflow_archive", return_value=0) as archive:
        assert cli.main(["archive", "--plan", str(selected), "--yes"]) == 0
    assert archive.call_args.kwargs["plan_path"] == str(selected)
    assert archive.call_args.kwargs["assume_yes"] is True


@pytest.mark.parametrize("change", ["none", "fit", "plan", "path", "missing_report"])
def test_selected_archive_verifies_build_provenance(store_factory, tmp_path, change):
    import hashlib

    store, selected = store_factory("selected")
    _, other = store_factory("other")
    out = tmp_path / "out"
    out.mkdir()
    fit_name = store.get_plan().workouts[0].filename + ".fit"
    (out / fit_name).write_bytes(b"selected")
    (out / "unrelated.fit").write_bytes(b"unrelated")
    if change != "missing_report":
        prepared = plan_artifacts.prepare_plan_artifacts(selected, artifacts_dir=tmp_path / "artifacts")
        plan_artifacts.write_build_report(
            prepared, validate_strict=False, run_id="test-build", success=True,
            built_count=1, build_total_count=1, valid_count=1, total_count=1,
            fit_files=[out / fit_name], errors=[],
            fit_provenance={fit_name: hashlib.sha256(b"selected").hexdigest()},
        )
    if change == "fit":
        (out / fit_name).write_bytes(b"replaced")
    elif change == "plan":
        selected.write_text("workouts: []", encoding="utf-8")
    elif change == "path":
        copied = tmp_path / "another" / selected.name
        copied.parent.mkdir()
        copied.write_bytes(selected.read_bytes())
        selected = copied
    with patch.multiple(archive_manager, OUTPUT_DIR=out, PLAN_DIR=tmp_path,
        PLAN_DONE_DIR=tmp_path / "done", ARCHIVE_DIR=tmp_path / "archive",
        ARTIFACTS_DIR=tmp_path / "artifacts"):
        archive = archive_manager.archive_current_plan(
            plan_paths=[selected], scope_fits_to_plan=True)
    assert not selected.exists()
    assert other.exists()
    assert (out / "unrelated.fit").read_bytes() == b"unrelated"
    assert (out / fit_name).exists() is (change != "none")
    assert (archive / "output_fit" / fit_name).exists() is (change == "none")


def test_gui_archive_passes_selected_path(tmp_path):
    path = tmp_path / "plan.yaml"
    path.write_text("workouts: []")
    app = SimpleNamespace(_run=Mock(), yaml_path=SimpleNamespace(get=lambda: str(path)))
    with patch.object(gui.messagebox, "askyesno", return_value=True):
        gui.App._cmd_archive(app)
    app._run.assert_called_once_with(["archive", "--plan", str(path), "--yes"])
