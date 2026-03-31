# Garmin FIT Workout Generator — Claude Context

See `version.txt` for project version history.

## Pipeline

```
text/md → LLM → YAML (Plan/) → direct FIT build → validation → archive
```

Run: `python get_fit.py` (full workflow) or `python run.py` (interactive menu).

## Two build paths — BOTH must stay in sync

| Path | Script | Used by |
|------|--------|---------|
| **Direct** (default) | `Scripts/build_from_plan.py` | `workflow_full`, Telegram bot |
| **Legacy/debug** | `Scripts/generate_from_yaml.py` + `Scripts/build_fits.py` | `--templates-only` / `--build-only` |

When adding new step types or fixing step generation logic, update **both** builders.

## back_to_offset — CRITICAL

`back_to_offset` in YAML is always a **YAML-level step index** (0-based position in the `steps` list).
Both builders call `_build_yaml_to_fit_index()` to translate it to the correct FIT runtime index at build time, accounting for `sbu_block` expansion.

**Never** put FIT runtime indices directly in YAML — the validator will reject them (`back_to_offset >= s_idx`).

Example (SBU + accelerations):
```yaml
steps:
  - type: dist_hr        # YAML 0 → FIT 0
  - type: sbu_block      # YAML 1 → FIT 1–16  (4 drills × 2 reps × 2 steps)
  - type: time_hr        # YAML 2 → FIT 17
  - type: time_step      # YAML 3 → FIT 18
  - type: repeat
    back_to_offset: 2    # ← YAML index 2, system computes FIT 17 automatically
    count: 4
```

## sbu_block expansion

Each drill expands to `reps × 2` FIT steps (active + open recovery).
- 4 drills × 2 reps = 16 FIT steps
- 2 drills × 2 reps = 8 FIT steps (deload)
- Default block (5 drills) = 24 FIT steps

## Week numbering

ISO weeks (Monday start): `date.isocalendar()[1]`
Filename pattern: `W{iso_week}_{MM-DD}_{Day}_{Type}_{Details}`

## Architecture (src/garmin_fit is canonical)

```
src/garmin_fit/   ← canonical source
garmin_fit/       ← alias layer (sys.modules redirect or copy-pattern)
Scripts/          ← compatibility shims (copy-pattern, reload for testability)
```

Key modules:
- `config.py` — paths; `GARMIN_FIT_RUNTIME_DIR` env var overrides `RUNTIME_ROOT`
- `cli.py` / `legacy_cli.py` / `validate_cli.py` — CLI entry points
- `_shared_cli.py` — `configure_logging()`, `generate_run_id()`
- `plan_service.py` — service layer (LLM draft, SBU custom drills, preview)
- `pipeline_runner.py` — programmatic wrapper around orchestrator
- `runtime_layout.py` — init/copy mutable runtime directory structure
- `llm/request_cli.py` — LLM generation CLI; `--workouts N` overrides expected count

## JSON Schema (Pydantic)

`WorkoutPlanSchema.model_json_schema()` generates machine-readable schema for all step types.
Use `get_plan_json_schema()` from `garmin_fit.llm.prompt` for external tools.
Compact version injected into prompt with `get_system_prompt(include_json_schema=True)`.

## LLM workout count detection

`normalize_source_text()` auto-detects expected workout count:
1. Dated headers (`12.03`, `12.03.2026`) or numbered headers (`Тренировка N`)
2. Phase-structured plans (`## ФАЗА N (недели A–B)` + `### DayName` sections)
3. If both fail → interactive prompt or `--workouts N` CLI flag

`workouts_hint` is passed through `generate_yaml_draft()` / `generate_yaml_from_plan()`.

## Docs

- `docs/YAML_GUIDE.md` — full YAML reference
- `docs/CHANGELOG.md` — version history
- `docs/PROJECT_FLOW.md` — pipeline details
