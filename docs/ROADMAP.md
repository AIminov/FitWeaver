# Project Roadmap

This roadmap is structured to improve the project without breaking the current workflow.

## Iteration 1: Project Baseline

Goal: make the repository installable and keep runtime artifacts out of the source tree contract.

Changes:
- add `pyproject.toml`
- add `.gitignore`
- define official CLI entry points for the current layout
- document the migration plan and target structure

Exit criteria:
- the project has a declared build system
- runtime outputs and caches are ignored
- current commands still work

## Iteration 2: Runtime Separation

Goal: separate source code from generated data and mutable state.

Changes:
- introduce a dedicated runtime root, for example `runtime/`
- move plans, output FIT files, archives, logs, build artifacts, and state under the runtime root
- update `Scripts/config.py` to resolve paths from one configurable runtime base
- keep backward-compatible defaults during migration

Target runtime layout:

```text
runtime/
  plans/
  output_fit/
  archives/
  build_artifacts/
  logs/
  state/
```

Exit criteria:
- no mutable project data is required in the repository root
- the runtime base can be changed from one config location

## Iteration 3: Package Normalization

Goal: turn the codebase into a conventional Python package.

Changes:
- move application code from `Scripts/` to `src/garmin_fit/`
- replace `from Scripts...` imports with package imports
- keep temporary compatibility shims where necessary
- add a dedicated CLI module inside the package

Target source layout:

```text
src/
  garmin_fit/
    __init__.py
    cli.py
    workflow.py
    config.py
    llm/
    archive/
    build/
    validation/
    bot/
```

Exit criteria:
- code imports do not depend on the repository root layout
- the main workflow runs through package entry points

## Iteration 4: Legacy Isolation

Goal: reduce cognitive load by separating the supported workflow from diagnostic and migration tools.

Changes:
- move template-based legacy flow into `legacy/` or `tools/`
- isolate one-off utilities and historical scripts
- keep direct build as the primary supported path

Exit criteria:
- primary CLI exposes only supported commands by default
- legacy functionality remains available but clearly scoped

## Iteration 5: Test and Contract Cleanup

Goal: make tests reflect the current public behavior.

Changes:
- fix drift between the LLM prompt contract and tests
- fix archive collision tests or implementation mismatch
- add smoke tests for CLI entry points and path configuration

Exit criteria:
- tests validate the current contract, not a previous implementation snapshot
- path-sensitive behavior is covered by tests

## Iteration 6: Documentation Consolidation

Goal: align the docs with the real architecture.

Changes:
- update the root `README.md`
- separate primary workflow docs from legacy/debug docs
- document the runtime layout and configuration model

Exit criteria:
- a new contributor can understand how to run, test, and extend the project from the docs alone

## Execution Order

1. Iteration 1: Project Baseline
2. Iteration 2: Runtime Separation
3. Iteration 3: Package Normalization
4. Iteration 4: Legacy Isolation
5. Iteration 5: Test and Contract Cleanup
6. Iteration 6: Documentation Consolidation

## Current Execution

- Iteration 1 completed.
- Iteration 2 completed with `GARMIN_FIT_RUNTIME_DIR` support and runtime bootstrap tooling.
- Iteration 3 completed: `src/garmin_fit` is canonical, `garmin_fit/` is a bridge, `Scripts/` is compatibility-only and not packaged.
- Iteration 4 completed: primary and legacy/debug CLIs fully separated.
- Iteration 5 completed: prompt contract, archive layout, and Pydantic schema tests aligned. 98 tests total.
- Iteration 6 completed: README split (EN + RU), docs updated to package-first CLI, SCRIPTS_DEPENDENCY_AUDIT.md added.

## Planned: Garmin Calendar Export (v10)

**Goal:** deliver workouts directly to Garmin Connect Calendar — no USB required.
After publishing, workouts appear on the watch automatically on next Garmin Connect sync.

**Stack (no official API approval needed):**
- `garminconnect` (cyberjunky) — `upload_running_workout()`, `schedule_workout()`
- `garmin-auth` (drkostas) — token persistence, MFA, rate limit handling

**Architecture:**
```
YAML → domain objects ──┬── FitExporter        → .fit → USB (current, kept)
                        └── GarminCalendarExporter → Garmin Connect → watch
```

**New module:** `src/garmin_fit/garmin_calendar_export.py`

**Key mapping work:**
- YAML step types → garminconnect step helpers (`create_warmup_step`, `create_interval_step`, `create_repeat_group`, `create_cooldown_step`)
- Workout date from YAML filename pattern (`W11_03-14_...`)
- Auth: FileTokenStore for local, DBTokenStore for Telegram/cloud deployments

**Risk:** unofficial/reverse-engineered API — can break if Garmin changes auth infrastructure.
