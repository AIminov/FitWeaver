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

Primary interfaces:

```bash
python -m garmin_fit.cli run
python -m garmin_fit.llm.request_cli
python -m garmin_fit.bot
python -m garmin_fit.runtime_cli --runtime-root runtime --copy-existing
```

Legacy-compatible interfaces kept for transition:

```bash
python get_fit.py
python -m Scripts.telegram_bot
python -m Scripts.llm.request_cli
python Scripts/check_fit.py
```

These legacy commands are intended for use from the repository checkout.

`get_fit.py` remains available as a compatibility entry point, but new usage
should go through `garmin_fit.cli` / `garmin_fit.legacy_cli`.

## Intent

The compatibility layer stays in place to avoid breaking:

- existing local automation
- old shell aliases and ad hoc scripts

New code should target `garmin_fit` and `src/garmin_fit`, not `Scripts`.

## Cleanup Scope Remaining

Remaining work is mostly optional cleanup:

- reduce duplicate wrappers where local root execution is no longer needed
- migrate any old personal utilities out of `Scripts/`
- eventually deprecate `get_fit.py` once package CLI adoption is complete
