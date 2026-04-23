# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See `version.txt` for project version history. See `TODO.md` for the full task backlog.

---

## ⚡ Правило для Claude: обновляй этот файл и TODO.md в конце каждой сессии

В конце каждой рабочей сессии (перед финальным коммитом):
1. Обнови раздел **«Журнал сессий»** ниже — что сделано, какие решения приняты, что отложено и почему.
2. Обнови раздел **«Next tasks»** — следующие приоритеты.
3. Обнови `TODO.md` — пометь выполненные пункты `✅ FIXED`, добавь новые идеи.
4. Закоммить оба файла вместе с остальными изменениями.

---

## Журнал сессий

### 2026-04-23 (v10.4 / v10.4.1)
**Сделано:**
- `build_yaml_to_fit_index()` вынесен в `workout_utils.py` — теперь один источник правды для обоих билдеров
- Валидация pace и HR дедуплицирована: `_is_valid_pace`, `_check_pace_ordering`, `_pace_to_seconds` живут в `plan_schema.py`, импортируются в `plan_validator.py`
- HR поля ограничены `le=250` в Pydantic-схеме
- `logging_utils.setup_file_logging()` не добавляет дублирующий FileHandler при повторном вызове
- `garmin_calendar_export._date_in_range()` логирует warning вместо тихого включения при нечитаемой дате
- `plan_domain` логирует предупреждения при отброске не-Mapping элементов
- `build_from_plan.build_all_fits_from_plan()` перечисляет имена упавших тренировок в итоговом логе
- `Scripts/telegram_bot.py` — шим молчал (не вызывал `main()`), исправлено
- `test_config.py` — изоляция тестов через `setUp`/`tearDown`
- Локализация СБУ в Garmin Calendar: "Отдых"/"Recovery", "Упражнение N"/"Drill N"; язык берётся из выбора пользователя в боте
- `requires-python` понижен с `>=3.13` до `>=3.10`
- `runner.py` переписан: loop, 14 опций, читает `GARMIN_EMAIL`/`GARMIN_PASSWORD` из env

**Решения/отказы:**
- `pipeline_runner.py` НЕ удалять — `telegram_bot.py` импортирует `run_pipeline` и `save_yaml_to_plan_dir` напрямую
- `sbu_block.py DEFAULT_DRILLS` НЕ выносить в конфиг — избыточно, имена уже на русском
- Gemma-4 сломана с `enable_thinking: false` — рекомендован Qwen3

**Следующие задачи:** TODO #6 (session timeout), #7 (YAML preview UX footer)

---

## Session continuity

**This file is the primary context source across machines.** The user (Amir / GitHub: AIminov) works on multiple PCs. Always read this file and `TODO.md` at the start of a session.

**Current version:** v10.4.1 (2026-04-23)  
**Repo:** https://github.com/AIminov/FitWeaver.git  
**Git identity:** `git config --global user.email "iminov@gmail.com" && git config --global user.name "AIminov"`  
**Auth:** user uses `gh` CLI — already authenticated as AIminov. No need to configure tokens.

**Next tasks (agreed, start here):**
1. `TODO #6` — Bot session timeout: `last_active` + `onboarded` in `UserState`, reset after 20 min inactivity, `SESSION_TIMEOUT_SEC` in `bot_config.yaml`
2. `TODO #7` — YAML preview footer UX: add clear instructions for what to do if the plan is wrong (resend text / /cancel)

**Working style preferences:**
- Communicate in Russian, code/commits in English
- No trailing summaries of what was just done — user can see the diff
- Commit and push after each logical unit of work
- When skipping a TODO item, explain why in one sentence
- Default language for bot strings and SBU drill labels: Russian (`language="ru"`)

---

## Development Setup

```bash
pip install -e ".[dev]"          # editable install with test/lint deps
pip install -e ".[garmin-calendar]"  # add Garmin Connect upload support
```

## Common Commands

```bash
# Run all tests (197 passing as of v10.4.1)
python3 -m pytest tests/

# Run a single test file
python3 -m pytest tests/test_build_from_plan.py

# Run a single test by name
python3 -m pytest tests/test_plan_validator.py -k test_repeat_back_to_offset

# Lint (tabs are the project style — E501/W19x are intentionally ignored)
ruff check src/

# Full workflow
python -m garmin_fit.cli run

# Validate YAML plan
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml

# LLM generation (LM Studio or Ollama)
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1

# Interactive menu (loop-based, 14 options)
python -m garmin_fit.runner

# Telegram bot
python -m garmin_fit.bot
# or from Scripts/ (shim, also works):
python3 Scripts/telegram_bot.py
```

---

## Pipeline

```
text/md → LLM → YAML (Plan/) → direct FIT build → validation → archive
                                                 ↘ Garmin Calendar upload (optional)
                                                 ↘ ZIP via Telegram bot (optional)
```

---

## LLM model compatibility

**Recommended:** `qwen3-27b` (or any Qwen3) — natively supports `enable_thinking: false`.  
**Broken:** `google/gemma-4-e4b` — ignores `enable_thinking: false`, enters thinking mode on retry, hangs 3000+ sec.  
Config: `bot_config.yaml` → `llm_model`.

---

## Two build paths — BOTH must stay in sync

| Path | Script | Used by |
|------|--------|---------|
| **Direct** (default) | `src/garmin_fit/build_from_plan.py` | `workflow_full`, Telegram bot |
| **Legacy/debug** | `src/garmin_fit/generate_from_yaml.py` + `src/garmin_fit/build_fits.py` | `--templates-only` / `--build-only` |

When adding new step types or fixing step generation logic, update **both** builders.

The canonical `build_yaml_to_fit_index()` lives in `workout_utils.py` and is imported by `build_from_plan.py`. `generate_from_yaml.py` has its own dict-handling version (legacy path, raw dicts not domain objects).

---

## back_to_offset — CRITICAL

`back_to_offset` in YAML is always a **YAML-level step index** (0-based position in the `steps` list).
Both builders call `build_yaml_to_fit_index()` to translate it to the correct FIT runtime index at build time, accounting for `sbu_block` expansion.

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

---

## sbu_block expansion

Each drill expands to `reps × 2` FIT steps (active + open recovery).
- Default block (5 drills, 2 reps each) = 24 FIT steps
- 4 drills × 2 reps = 16 FIT steps
- 2 drills × 2 reps = 8 FIT steps (deload)

`DEFAULT_DRILLS` in `sbu_block.py` are in Russian. `garmin_step_mapper.py` uses `language="ru"` by default for recovery/fallback labels ("Отдых" / "Упражнение N"). The Telegram bot passes `_lang(user_id)` to `GarminCalendarExporter(language=...)`.

---

## Telegram bot

**State machine:** idle → generating → awaiting_sbu_choice → awaiting_clarification → awaiting_confirm → building → idle

**Known issues to fix (see TODO #6, #7):**
- New users / second phone can skip `/start` and send plan text directly — bot accepts it because `state.status == "idle"` with no `onboarded` check.
- YAML preview footer only says "press /build if correct" — no instruction for what to do if wrong.

**Language:** stored in `UserState.language` ("ru" / "en"). Set via `/start` → inline keyboard. `_lang(user_id)` returns it. `_m(user_id, key)` looks up `MSG[lang][key]`.

**Running the bot:** `python -m garmin_fit.bot` from project root. The `Scripts/telegram_bot.py` shim also works (fixed — now calls `main()`).

---

## Garmin Calendar localization

`GarminCalendarExporter(client, language="ru")` — language flows to `map_workout()` → `map_steps()` → `_map_sbu_block()`. Recovery step label and unnamed drill fallback are localized. Bot passes user language automatically.

---

## Week numbering

ISO weeks (Monday start): `date.isocalendar()[1]`  
Filename pattern: `W{iso_week}_{MM-DD}_{Day}_{Type}_{Details}`

---

## Architecture (src/garmin_fit is canonical)

```
src/garmin_fit/   ← canonical source — ALL edits go here
garmin_fit/       ← alias bridge layer — DO NOT edit directly
Scripts/          ← compatibility shims — DO NOT edit directly
```

Key modules:
- `config.py` — paths; `GARMIN_FIT_RUNTIME_DIR` env var overrides `RUNTIME_ROOT`
- `cli.py` / `legacy_cli.py` / `validate_cli.py` / `runtime_cli.py` — CLI entry points
- `_shared_cli.py` — `configure_logging()`, `generate_run_id()`
- `plan_schema.py` — Pydantic v2 schema; `_is_valid_pace()`, `_pace_to_seconds()`, `_check_pace_ordering()` are shared with `plan_validator.py`
- `plan_validator.py` — semantic validation (imports helpers from `plan_schema.py`)
- `plan_domain.py` — domain objects (`WorkoutStep`, `Workout`, `WorkoutPlan`, `Drill`); logs warnings on dropped non-Mapping items
- `plan_processing.py` — YAML repair, name normalization
- `plan_service.py` — service layer (LLM draft, SBU custom drills, preview)
- `workout_utils.py` — FIT step builders + canonical `build_yaml_to_fit_index()`
- `build_from_plan.py` — direct YAML→FIT builder (default path)
- `generate_from_yaml.py` — legacy template-based builder (debug path)
- `sbu_block.py` — SBU FIT step generator; `DEFAULT_DRILLS` in Russian
- `garmin_step_mapper.py` — maps domain objects to Garmin Calendar API payloads; `map_workout(workout, language="ru")`
- `garmin_calendar_export.py` — `GarminCalendarExporter(client, language="ru")`; upload/schedule/delete
- `garmin_auth_manager.py` — token caching for Garmin Connect auth
- `logging_utils.py` — `setup_file_logging()` guards against duplicate FileHandler
- `pipeline_runner.py` — wrapper used by `telegram_bot.py`; do not remove (it's imported)
- `runner.py` — interactive menu, 14 options, loop-based
- `bot.py` / `telegram_bot.py` — Telegram bot entry point and async state machine
- `llm/request_cli.py` — LLM generation CLI; `--workouts N` overrides expected count
- `llm/benchmark.py` — LLM quality benchmark; `DEFAULT_SUITE` uses `PROJECT_ROOT`
- `check_fit.py` — FIT file validator; large file threshold in `_LARGE_FILE_BYTES`

---

## JSON Schema (Pydantic)

`WorkoutPlanSchema.model_json_schema()` generates machine-readable schema for all step types.
Use `get_plan_json_schema()` from `garmin_fit.llm.prompt` for external tools.
Compact version injected into prompt with `get_system_prompt(include_json_schema=True)`.

---

## LLM workout count detection

`normalize_source_text()` auto-detects expected workout count:
1. Dated headers (`12.03`, `12.03.2026`) or numbered headers (`Тренировка N`)
2. Phase-structured plans (`## ФАЗА N (недели A–B)` + `### DayName` sections)
3. If both fail → interactive prompt or `--workouts N` CLI flag

---

## Docs

- `docs/YAML_GUIDE.md` — full YAML reference
- `docs/CHANGELOG.md` — version history
- `docs/PROJECT_FLOW.md` — pipeline details
- `docs/TELEGRAM_SETUP.md` — bot setup and troubleshooting
- `docs/GARMIN_CALENDAR.md` — Garmin Connect Calendar upload guide
