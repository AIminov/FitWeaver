# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See `version.txt` for project version history. See `TODO.md` for the full task backlog.

---

## ⚡ Правило для Claude: обновляй этот файл и TODO.md в конце каждой сессии

В конце каждой рабочей сессии (перед финальным коммитом):
1. Обнови раздел **«Журнал сессий»** в `AGENTS.md` — что сделано, какие решения приняты, что отложено и почему.
2. Обнови раздел **«Next tasks»** — следующие приоритеты.
3. Обнови `TODO.md` — удали выполненные пункты (они уходят в `docs/CHANGELOG.md`), добавь новые.
   TODO.md хранит только открытые задачи; старая история — в `docs/history/`.
4. Закоммить оба файла вместе с остальными изменениями.

---

## Last session summary

**As of 2026-09-26** — Plans in the marked text format are compiled to YAML by a deterministic parser (`marked_plan.py`) with no LLM; the GUI, the Plan API and the new `garmin-fit parse-marked` CLI use it automatically, and only free text goes to the LLM. Product direction: small LLMs on a laptop CPU (no GPU); the Telegram bot is deprioritized. Desktop GUI: 4 tabs (План / LLM / Конструктор / Garmin Connect), simple/expert mode, per-email profiles, Garmin calendar editing, dual standalone exes. Suite: 390 passed (with the api extra). All architecture decisions (Plan API, SQLite staging, workout builder, error hints, drag&drop) are stable and in code. The per-session log lives in `AGENTS.md` («Журнал сессий»); `version.txt` keeps the version history; for detailed implementation notes see the git log (`git log --oneline src/`).

---

## Session continuity

**This file is the primary context source across machines.** The user (Amir / GitHub: AIminov) works on multiple PCs. Always read this file and `TODO.md` at the start of a session.

**Current version:** v10.5.0 (2026-09-02)  
**Repo:** https://github.com/AIminov/FitWeaver.git  
**Git identity:** `git config --global user.email "iminov@gmail.com" && git config --global user.name "AIminov"`  
**Auth:** user uses `gh` CLI — already authenticated as AIminov. No need to configure tokens.

**Next tasks (agreed 2026-09-26, start here):**
1. Live checks that need hardware/accounts: rebuild both exes and click through the LLM tab
   (marked text, progress/cancel) and sidebar commands; Garmin duplicate-skip against real
   calendar names; OpenAI `auto` mode against a live server.
2. LLM path for free text: make the model emit a short line format (or marked text) that
   `marked_plan.py` compiles, instead of Garmin YAML — CPU latency is dominated by output tokens
   (~2.6 tok/s measured). Compare on the golden suite (`docs/golden_dataset/`) with
   `garmin-fit-llm-eval`; do not change prompts without a measurement.
3. Rule-based pre-parser for common free-text phrases so many workouts skip the LLM entirely.
4. Code quality: one parser for the marked format (`marked_source_checks` → `marked_plan`),
   retire the legacy exec-based builder, extract GUI state logic from `fitweaver_gui.py`.
5. `TODO.md` lists every open task (only open ones). The Telegram bot is deprioritized.

**Working style preferences:**
- Start every session with `git pull` (work on several PCs diverged into two 22-commit lines once)
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
pip install -e ".[api]"          # add the Plan API (FastAPI+uvicorn) -- needed to run garmin-fit-api
pip install -e ".[build]"        # add PyInstaller -- needed to package the desktop GUI as .exe
pip install -e ".[gui]"          # add customtkinter -- optional GUI theming (GUI falls back to plain Tkinter without it)
```

## Common Commands

```bash
# Run all tests (466 passed with the api extra, as of 2026-09-27)
python3 -m pytest tests/

# Run a single test file
python3 -m pytest tests/test_build_from_plan.py

# Run a single test by name
python3 -m pytest tests/test_plan_validator.py -k test_repeat_back_to_offset

# Lint (tabs are the project style — E501/W19x are intentionally ignored)
ruff check src/

# Desktop GUI (recommended for local users) — Calendar / LLM Generator / Конструктор / Garmin Connect
python fitweaver_gui.py

# Full workflow
python -m garmin_fit.cli run

# Validate YAML plan
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml

# Marked plan text → YAML without an LLM
python -m garmin_fit.cli parse-marked plan.txt --output Plan/plan.yaml --profile user_profile.yaml
python -m garmin_fit.cli to-marked Plan/plan.yaml --output plan.txt   # YAML → marked text

# LLM generation (LM Studio or Ollama)
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1

# Interactive menu (loop-based)
python -m garmin_fit.runner

# Telegram bot
python -m garmin_fit.bot
# or from Scripts/ (shim, also works):
python3 Scripts/telegram_bot.py
```

---

## Pipeline

```
marked text  → marked_plan.py (deterministic, no LLM) ─┐
free text/md → LLM ─────────────────────────────────────┴→ YAML (Plan/) → direct FIT build → validation → archive
                                                                                           ↘ Garmin Calendar upload (optional)
                                                                                           ↘ ZIP via Telegram bot (optional, deprioritized)
```

Routing lives in `plan_service.build_plan_draft()`: any text containing a `**** ШАГ ****` line is
compiled by `marked_plan.compile_marked_text()`; only free text reaches the LLM.

---

## LLM model compatibility

- **Target:** small models that run locally on a laptop CPU without GPU (Qwen3 8B IQ4_XS class
  via Ollama / llama.cpp). Golden-suite strict pass (2026-09-25): Unsloth Qwen3 8B IQ4_XS 8/10,
  `qwen3:8b` 6/10; ~45–200 s per workout, ~80% of it generating output tokens.
- **Marked text needs no LLM at all** — see `docs/MARKED_PLAN_FORMAT.md` / `marked_plan.py`.
- Qwen3 natively supports `enable_thinking: false`.
- **Broken:** `google/gemma-4-e4b` — ignores `enable_thinking: false`, enters thinking mode on retry, hangs 3000+ sec.
- Config: `bot_config.yaml` → `llm_model`; the GUI keeps its own LLM settings.

---

## One build path

`src/garmin_fit/build_from_plan.py` builds FIT files directly from YAML domain objects; it is
used by the full workflow, the GUI and the bot. The legacy template path (`generate_from_yaml.py`
+ `build_fits.py`, which generated and exec'd Python code) and `garmin-fit-legacy` were removed
on 2026-09-26. `build_yaml_to_fit_index()` in `workout_utils.py` is the single YAML→FIT index
mapping.

The Garmin Connect payload (`garmin_step_mapper.py`) is the second consumer of the same YAML;
`tests/test_fit_garmin_equivalence.py` checks that both execute identically.

---

## back_to_offset — CRITICAL

`back_to_offset` in YAML is always a **YAML-level step index** (0-based position in the `steps` list).
The builder calls `build_yaml_to_fit_index()` to translate it to the correct FIT runtime index at build time, accounting for `sbu_block` expansion.

**Never** put FIT runtime indices directly in YAML — the validator will reject them (`back_to_offset >= s_idx`).

The desktop GUI's "🧱 Конструктор" tab (visual workout builder, `workout_builder.py` + `plan_store.py`) is the recommended way to avoid hand-computing this value: select a range of blocks and click "Повторить ×N" — `back_to_offset` is computed from the selection, never typed.

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

## Heart-rate caps

An upper-only cap ("пульс до 140", "не выше 140", "HR <= 140") is encoded as `hr_low: 60,
hr_high: 140` everywhere (`plan_domain.HR_CAP_FLOOR_BPM`, agreed with the user 2026-09-27):
60 is a typical resting HR, so the watch alerts only above the cap. Any other incomplete target
(lower-only bound, single pace value except the agreed ±10 s/km widening) is never completed.

## sbu_block expansion

Each drill expands to `reps × 2` FIT steps (active + open recovery).
- Default block (5 drills, 2 reps each) = 24 FIT steps
- 4 drills × 2 reps = 16 FIT steps
- 2 drills × 2 reps = 8 FIT steps (deload)

`DEFAULT_DRILLS` in `sbu_block.py` are in Russian. `garmin_step_mapper.py` uses `language="ru"` by default for recovery/fallback labels ("Отдых" / "Упражнение N"). The Telegram bot passes `_lang(user_id)` to `GarminCalendarExporter(language=...)`.

---

## Telegram bot

**State machine:** idle → generating → awaiting_sbu_choice → awaiting_clarification → awaiting_confirm → building → idle

**Session timeout:** `UserState.last_active`/`onboarded` fields; `_enforce_session()` resets via `reset_state()` and re-prompts `/start` if the user skipped onboarding or has been idle past `session_timeout_sec` (`bot_config.yaml`, default 1200s). Wired into `handle_text_message`; `handle_lang_choice` (the real `/start` flow) marks `onboarded=True`.

**Plan generation is now via the Plan API, not a direct LLM connection.** `_build_llm_client()` returns a `PlanApiClient` (`src/garmin_fit/api_client.py`) pointed at `bot_config.yaml`'s `plan_api_url`/`plan_api_token` — a running `garmin-fit-api` instance (see "Plan API" section below). The bot calls `llm.build_plan_draft(plan_text)` / `llm.apply_custom_sbu_choice(yaml_data, user_text)` directly on that client (not the module-level `plan_service` functions) so `plan_service.py`'s repair/validation logic runs exactly once, inside the API process — never duplicated in the bot. `PlanApiError` subclasses `RuntimeError`, so the bot's existing broad `except Exception` clauses catch it with no changes; a dedicated `api_unreachable` message covers the new "API process down/unreachable" failure mode distinct from `llm_no_connect` (which checks the LLM behind the API, not the API itself).

**Language:** stored in `UserState.language` ("ru" / "en"). Set via `/start` → inline keyboard. `_lang(user_id)` returns it. `_m(user_id, key)` looks up `MSG[lang][key]`.

**Running the bot:** `python -m garmin_fit.bot` from project root (needs a running `garmin-fit-api` instance — see below). The `Scripts/telegram_bot.py` shim also works (fixed — now calls `main()`).

---

## Plan API (`src/garmin_fit/api/`)

Thin FastAPI+uvicorn facade over `plan_service.py` — the one place `build_plan_draft`/
`apply_custom_sbu_choice` actually run. Both the Telegram bot and the GUI's "LLM автора" mode
are HTTP clients of this (`src/garmin_fit/api_client.py`'s `PlanApiClient`); the GUI's "Своя
LLM" mode still talks to `UnifiedLLMClient` directly and does not need this running.

**Setup:** `pip install -e ".[api]"`, `cp api_config.yaml.example api_config.yaml`, fill in
`api_token` (or set `FITWEAVER_API_TOKEN` env var instead) and `llm_url`/`llm_model`/
`llm_api_type`. Run with `garmin-fit-api` (or `python -m garmin_fit.api_cli` if the entry
point isn't on `PATH`).

**Endpoints:** `POST /v1/generate-draft`, `POST /v1/apply-sbu-choice`, `GET /v1/health` — all
require an `X-Api-Token` header matching `api_config.yaml`'s `api_token`. Rate-limited via an
in-memory token bucket (`rate_limit_per_minute`/`rate_limit_burst` in `api_config.yaml`),
keyed per token, state on `app.state` (not a module global — each `create_app()` call gets
isolated bucket state, this matters for tests).

**Security note:** never expose the raw LLM server (`llm_url`) directly to the internet —
always go through this API, which is what the auth token and rate limiter protect. This is
mandatory, not optional, if the API's port is ever reachable from outside localhost.

---

## Desktop packaging (.exe)

GUI-only (not the bot or Plan API — those stay Python-run services). `packaging/` has:
`cli_entry.py` (wraps `garmin_fit.cli:main` for a second exe), `fitweaver_gui.spec` /
`fitweaver_cli.spec` (two separate PyInstaller spec files — deliberately not two
`Analysis`/`PYZ` blocks in one spec, see the docstring in `fitweaver_gui.spec` for why that
silently corrupts one of the two onefile exes), and `build.ps1`.

**Build:** `powershell packaging/build.ps1` (or manually: `pip install -e
".[garmin-calendar,build]"`, then build from an isolated staging copy — see below — with
`pyinstaller packaging/fitweaver_gui.spec` and `pyinstaller packaging/fitweaver_cli.spec`).
Produces `dist/FitWeaver.exe` + `dist/garmin-fit-cli.exe`. Since 2026-09-26 the GUI runs every
sidebar action (build, Garmin upload/delete, the "ПРОДВИНУТЫЕ" section) **in-process** through
`garmin_fit.cli_runner.run_cli_captured()`, so `FitWeaver.exe` works on its own; the CLI exe is
optional. (It used to shell out to the sibling CLI exe, which cost ~4.5 s of onefile unpacking
per action and put the Garmin password on a command line.) Workflow steps likewise call each
module's `main(argv)` in-process (`workflow.run_step`) — `sys.executable -m module` does not
work inside a frozen exe, where `sys.executable` is the exe itself.

**Why two exes, and why the CLI one excludes the GUI toolkits:** the split exists because
the two have different Windows subsystems — the GUI is built `console=False` (windowed, no
console window on launch) and the CLI `console=True` (a real console app that blocks the
prompt and prints where you ran it). Merging them into one exe with a `--cli` flag would
save a file but force one subsystem on both: a windowed build returns the shell prompt
immediately and prints nothing visible when run directly from a terminal, which is exactly
how the CLI is used for smoke checks. The GUI's own shell-out is unaffected either way
(it reads a pipe), so the merge would trade a working standalone CLI for one less file.
Not worth it — see the 2026-09-07 journal entry in `AGENTS.md`.

What *was* worth fixing: `fitweaver_cli.spec` used to force-include every `garmin_fit`
submodule via `collect_submodules`, which reached `gui_theme` and its lazy
`import customtkinter` — PyInstaller follows that statically, so the console exe carried
all of customtkinter and tkinter despite `import garmin_fit.cli` pulling in zero tkinter
modules. The spec now filters the GUI-only modules out of that list and passes
`excludes=["tkinter", "_tkinter", "customtkinter", "PIL"]`, taking the CLI exe from 28.0 MB
to 24.7 MB. Don't restore the blanket `collect_submodules` there.

**Portable folder, not `%APPDATA%`:** writable state (`Plan/`, `profiles/`,
`.gui_session.json`, `Output_fit/`, `Archive/`) resolves from `sys.executable`'s parent
directory when frozen (`config.py`'s `PROJECT_ROOT`, `fitweaver_gui.py`'s own `PROJECT_ROOT`)
— stable across onefile's per-launch temp extraction, and matches the existing
"run-from-a-git-checkout" mental model users already have.

**Why the build must happen from an isolated staging copy, not the live source tree:** the
repo root also has a `garmin_fit/` compatibility bridge package (see Architecture below) that
contains only `__init__.py` + an empty `llm/` dir and extends its `__path__` to
`src/garmin_fit` via `__path__.append(...)` — but only at real runtime. PyInstaller
auto-adds the main script's own directory (the repo root, since `fitweaver_gui.py` lives
there) to its search path, and when resolving the *lazily* imported `garmin_fit` submodules
that make up almost all of `fitweaver_gui.py`'s own imports (inside method bodies, not at
module level), its static analysis doesn't execute `__init__.py` and so never sees the
appended path — it silently resolves against the near-empty bridge directory instead,
dropping modules like `plan_store`/`workout_builder` from the frozen build with **no
build-time error or warning**. `build.ps1` copies `src/`, `fitweaver_gui.py`, and
`packaging/` into `build/stage/` (no root-level `garmin_fit/` present there at all) and
builds from there instead, removing the ambiguity entirely.

Out of scope for now: packaging the bot/API as exes, a real installer (Inno
Setup/NSIS)/code signing, auto-update.

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
- `cli.py` / `validate_cli.py` / `runtime_cli.py` — CLI entry points
- `cli_runner.py` — runs `cli.main` in-process with captured output (the GUI's command runner)
- `_shared_cli.py` — `configure_logging()`, `generate_run_id()`
- `plan_schema.py` — Pydantic v2 schema; `_is_valid_pace()`, `_pace_to_seconds()`, `_check_pace_ordering()` are shared with `plan_validator.py`
- `plan_validator.py` — semantic validation (imports helpers from `plan_schema.py`)
- `plan_domain.py` — domain objects (`WorkoutStep`, `Workout`, `WorkoutPlan`, `Drill`); logs warnings on dropped non-Mapping items
- `plan_processing.py` — YAML repair, name normalization
- `plan_service.py` — service layer (LLM draft, SBU custom drills, preview); routes marked text to `marked_plan`
- `marked_plan.py` — deterministic parser/compiler for the marked text format (step tree → YAML, repeat offsets computed, `render_marked_plan()` back to text); `garmin-fit parse-marked` CLI
- `workout_utils.py` — FIT step builders + canonical `build_yaml_to_fit_index()`
- `build_from_plan.py` — direct YAML→FIT builder (default path)
- `sbu_block.py` — SBU FIT step generator; `DEFAULT_DRILLS` in Russian
- `garmin_step_mapper.py` — maps domain objects to Garmin Calendar API payloads; `map_workout(workout, language="ru")`
- `garmin_calendar_export.py` — `GarminCalendarExporter(client, language="ru")`; upload/schedule/delete
- `garmin_auth_manager.py` — token caching for Garmin Connect auth
- `logging_utils.py` — `setup_file_logging()` guards against duplicate FileHandler
- `pipeline_runner.py` — wrapper used by `telegram_bot.py`; do not remove (it's imported)
- `runner.py` — interactive menu, 14 options, loop-based
- `bot.py` / `telegram_bot.py` — Telegram bot entry point and async state machine
- `llm/request_cli.py` — LLM generation CLI; `--workouts N` overrides expected count
- `llm/client.py` — `UnifiedLLMClient`: transports (Ollama streaming, OpenAI-compatible), segmented generation, cache, retries
- `llm/source_facts.py` — source-text heuristics (dated headers, interval counts, HR caps) that repair or flag model answers
- `llm/yaml_cleanup.py` — cleanup of raw model answers before YAML parsing
- `free_text_rules.py` — deterministic rules for common workout lines (tried before the LLM per workout)
- `llm/golden.py` — golden-dataset suite builder and fact-level comparison
- `llm/benchmark.py` — LLM quality benchmark; `DEFAULT_SUITE` uses `PROJECT_ROOT`
- `check_fit.py` — FIT file validator; large file threshold in `_LARGE_FILE_BYTES`
- `plan_store.py` — SQLite staging layer for the desktop GUI only; YAML stays canonical everywhere else. `PlanStore` writes back to the loaded YAML file after every mutation
- `profile_store.py` — per-user (email-keyed) GUI state: plan session, personal HR profile, onboarding/legacy-migration; reuses the same email slug as `workflow._resolve_garmin_token_dir`
- `workout_builder.py` — pure-Python support for the GUI's visual workout builder (no Tkinter/SQLite): `BLOCK_DEFS`, `TEMPLATES`, `compute_repeat_step()`, `validate_draft()`
- `api/` — FastAPI facade over `plan_service.py` (`app.py`/`auth.py`/`rate_limit.py`/`schemas.py`/`config.py`); `api_cli.py` is the `garmin-fit-api` entry point
- `api_client.py` — `PlanApiClient`/`PlanApiError`, the shared HTTP client the bot and the GUI's "LLM автора" mode both use to reach `api/`

`packaging/` (repo root, not under `src/garmin_fit/`) — PyInstaller packaging for the desktop
GUI: `cli_entry.py`, `fitweaver_gui.spec`/`fitweaver_cli.spec`, `build.ps1`. See "Desktop
packaging (.exe)" above.

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

- `docs/PLAN_WRITING_GUIDE.md` — user guide (Russian): how to write a plan so it parses without an LLM; `tests/test_plan_writing_guide.py` checks every example in it
- `docs/YAML_GUIDE.md` — full YAML reference
- `docs/MARKED_PLAN_FORMAT.md` — marked plan text format (LLM-free input)
- `docs/CHANGELOG.md` — version history
- `docs/PROJECT_FLOW.md` — pipeline details
- `docs/TELEGRAM_SETUP.md` — bot setup and troubleshooting
- `docs/GARMIN_CALENDAR.md` — Garmin Connect Calendar upload guide
- `docs/golden_dataset/` — golden dataset (62 workout groups, 77 text variants, VALID / NEEDS_CLARIFICATION /
  UNSUPPORTED) for evaluating the marked parser and the local LLM. The FunctionGemma fine-tune
  experiment it was built for did not work and was removed on 2026-09-26.
