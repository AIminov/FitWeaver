# Scripts Dependency Audit

## Purpose

This audit records where `Scripts.*` is still required after the migration to
`src/garmin_fit`.

## Current Conclusion

`Scripts` no longer ships as part of the installed package.

Reason:

- compatibility entry points still intentionally expose `Scripts.*`
- some documentation still references `Scripts.*` as a compatibility path
- source-checkout compatibility still keeps `Scripts/` in the repository

## Current Dependency Groups

### 1. Compatibility entry points

Still intentionally supported:

- `python get_fit.py`
- `python -m Scripts.telegram_bot`
- `python -m Scripts.llm.request_cli`
- `python Scripts/check_fit.py`

### 2. Documentation/examples tail

This category is being reduced incrementally.

It is not a blocker for runtime correctness, but it affects the decision to
remove or hide `Scripts.*` from user-facing materials.

## Decision

For the current project state:

- keep `Scripts/` as a compatibility layer
- ship only `src/garmin_fit` in the installed package
- continue migrating docs/examples away from `Scripts.*`

## Safe Future Exit Criteria

`Scripts/` can be reconsidered for deeper cleanup only after:

1. compatibility entry points are either removed or clearly documented as source-checkout-only
2. user-facing docs stop presenting `Scripts.*` as a normal path
3. we decide whether repository-local `Scripts/` shims are still part of the support policy
