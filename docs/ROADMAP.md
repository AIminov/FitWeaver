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
- Iteration 3 is largely completed: primary modules now live in `src/garmin_fit`, with root-level compatibility wrappers in `garmin_fit/` and shims in `Scripts/`.
- Iteration 4 is in progress: primary and legacy/debug CLIs are separated, and historical scripts are being isolated or rewritten as compatibility utilities.
- Iteration 5 completed for the current red test set: prompt contract drift and archive layout expectations were aligned, and package/runtime smoke tests were added.
- Iteration 6 is in progress: the root README is being updated to reflect the package-first CLI and runtime layout.
