# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See `version.txt` for project version history.

## Development Setup

```bash
pip install -e ".[dev]"          # editable install with test/lint deps
pip install -e ".[garmin-calendar]"  # add Garmin Connect upload support
```

## Common Commands

```bash
# Run all tests
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_build_from_plan.py

# Run a single test by name
python -m pytest tests/test_plan_validator.py -k test_repeat_back_to_offset

# Lint (tabs are the project style — E501/W19x are intentionally ignored)
ruff check src/

# Full workflow
python -m garmin_fit.cli run

# Validate YAML plan
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml

# LLM generation (LM Studio)
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1

# Interactive menu
python -m garmin_fit.runner
```

## Pipeline

```
text/md → LLM → YAML (Plan/) → direct FIT build → validation → archive
```

Run: `python -m garmin_fit.cli run` (full workflow) or `python -m garmin_fit.runner` (interactive menu).

## Two build paths — BOTH must stay in sync

| Path | Script | Used by |
|------|--------|---------|
| **Direct** (default) | `src/garmin_fit/build_from_plan.py` | `workflow_full`, Telegram bot |
| **Legacy/debug** | `src/garmin_fit/generate_from_yaml.py` + `src/garmin_fit/build_fits.py` | `--templates-only` / `--build-only` |

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
src/garmin_fit/   ← canonical source — ALL edits go here
garmin_fit/       ← alias layer (sys.modules redirect or copy-pattern) — DO NOT edit directly
Scripts/          ← compatibility shims (copy-pattern, reload for testability) — DO NOT edit directly
```

Key modules:
- `config.py` — paths; `GARMIN_FIT_RUNTIME_DIR` env var overrides `RUNTIME_ROOT`
- `cli.py` / `legacy_cli.py` / `validate_cli.py` / `runtime_cli.py` — CLI entry points
- `_shared_cli.py` — `configure_logging()`, `generate_run_id()`
- `plan_service.py` — service layer (LLM draft, SBU custom drills, preview)
- `pipeline_runner.py` — programmatic wrapper around orchestrator
- `runtime_layout.py` — init/copy mutable runtime directory structure
- `garmin_calendar_export.py` — Garmin Connect Calendar upload/delete
- `garmin_auth_manager.py` — token caching for Garmin Connect auth
- `garmin_step_mapper.py` — maps YAML step types to Garmin API payloads
- `llm/request_cli.py` — LLM generation CLI; `--workouts N` overrides expected count
- `bot.py` / `telegram_bot.py` — Telegram bot entry point and handler logic

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
