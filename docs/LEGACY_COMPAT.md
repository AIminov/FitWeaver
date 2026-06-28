# Legacy Compatibility

## Status

`src/garmin_fit/` is the primary source tree.

`garmin_fit/` contains local execution wrappers so the package can run from the
repository root without installation.

`Scripts/` is now a legacy compatibility layer. Most modules there are thin
aliases that forward to `garmin_fit` / `src.garmin_fit`.

Installed packaging now ships `src/garmin_fit` only. `Scripts/` and the
repository-root `garmin_fit/` wrappers are for source-checkout compatibility,
not for the installed wheel.

## Supported Interfaces

Primary local interface:

```bash
python fitweaver_gui.py
```

Supported package CLIs for automation:

```bash
python -m garmin_fit.cli run
python -m garmin_fit.llm.request_cli
python -m garmin_fit.bot
python -m garmin_fit.runtime_cli --runtime-root runtime --copy-existing
```

Legacy-compatible interfaces kept for transition:

```bash
python -m Scripts.telegram_bot
python -m Scripts.llm.request_cli
python Scripts/check_fit.py
```

These legacy commands are intended for use from the repository checkout.

The old root launcher scripts (`get_fit.py`, `run.py`, `validate_yaml.py`,
`run_pipeline.bat`, `run_pipeline.sh`) have been removed. Use the GUI for local
work and package module commands for automation.

## Intent

The compatibility layer stays in place to avoid breaking:

- existing local automation
- old shell aliases and ad hoc scripts

New code should target the GUI, `garmin_fit` package commands, and
`src/garmin_fit`, not `Scripts`.

## Cleanup Scope Remaining

Remaining work is mostly optional cleanup:

- reduce duplicate wrappers where local root execution is no longer needed
- migrate any old personal utilities out of `Scripts/`
