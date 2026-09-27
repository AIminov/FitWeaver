# Changelog

## 2026-09-27 - Rules: cadence, titles, dates

### Fixed
- `каденс 175-185` / `175-185 шаг/мин` was read by the rules as a heart-rate range; cadence is now
  recognised by its label and becomes a cadence target.
- A header title that is also a step role (`12.10 (пн) — Восстановление`, `— Ускорения`) was
  taken as the role of the next step and the workout lost its name; words after the dash are now
  the title.
- Titles such as `Километровые`, `400-метровые`, `Минутки` were taken for a unit without a number
  and sent the whole workout to the LLM.
- `в разговорном темпе` (effort described in words) no longer passes the rules silently; like
  `комфортно` / `трудно разговаривать` it goes to the LLM.
- A dated header whose weekday does not match the date kept the wrong weekday in the LLM path
  (and could pick the wrong year); the date now wins, the weekday only helps choose the year when
  the year is missing.
- `уд/мин` in a step (`пульс 125–140 уд/мин`) no longer counts as a unit without a number.

## 2026-09-27 - `garmin-fit to-marked`

### Added
- `garmin-fit to-marked PLAN.yaml [--output TEXT]` renders an existing YAML plan as marked text
  for editing; `parse-marked` compiles it back to the same steps.

## 2026-09-27 - Builder: nested sets, correct repeat indices

### Fixed
- Adding a repeat in the builder above an existing repeat group did not shift that group's
  `back_to_offset`, so the lower repeat pointed at the new repeat row instead of its first step
  and the workout changed silently. `workout_builder.insert_repeat_into_draft` inserts and shifts.

### Added
- The builder and `PlanStore.add_repeat_over_range` accept a range that contains whole repeat
  groups, so nested sets like 3 × (4 × 400 m) can be built; a range that cuts through a group is
  still rejected. Both use one rule (`compute_repeat_step`).

## 2026-09-27 - No more cache files beside the user's plans

### Changed
- The GUI's plan staging database lives in `Build_artifacts/workdb/` (named by a hash of the plan
  path) instead of `<plan>.yaml.workdb` next to the plan; an old sibling file is removed when the
  plan is opened (it is a disposable cache rebuilt from the YAML on every open).
- Removed unused GUI helpers that wrote `Plan/_gui_draft_*.yaml` files.

## 2026-09-27 - Building FIT files no longer moves the plan or the FIT files

### Fixed
- After a successful build ("Собрать FIT-файлы", `garmin-fit run`) the automatic archive moved
  the FIT files out of `Output_fit/` and moved the plan file — even one opened from any folder —
  into `Plan/plan_done/`. The GUI then pointed at a missing plan and "Открыть папку FIT" showed
  an empty folder. The post-build archive is now a snapshot (copies); the explicit `archive`
  command still archives and cleans.

## 2026-09-27 - Garmin duration estimate from stated facts

### Added
- When a workout states no total duration, the Garmin payload's `estimatedDurationInSecs` is
  computed from the steps: timed steps, distance × mid pace for pace steps, SBU drills, repeats
  multiplied. If any step's duration is not stated (distance with HR only, lap-button step) the
  estimate stays empty — nothing is guessed. YAML is unchanged (`estimated_duration_min` stays
  null unless the source states it).

## 2026-09-27 - GUI smoke test in the suite

### Added
- `tests/test_gui_smoke.py` drives the real GUI under a Tk mainloop: marked text compiled
  without the LLM, result shown as marked text and put back into the editor, a CLI command run
  in-process, and the Garmin password redacted in the log. Session, profiles and logs go to a
  temp directory; network and dialogs are stubbed. Runs where a display exists (Windows CI job,
  local), skipped otherwise.
- `llm/client.py` split: `llm/source_facts.py` (source-text heuristics) and `llm/yaml_cleanup.py`
  (raw answer cleanup); old helper names remain as aliases.

## 2026-09-27 - Crash-safe writes of user files

### Fixed
- The open plan (rewritten after every edit in the GUI), the GUI session, per-profile session,
  templates and HR profile, and YAML saved from the GUI are written atomically
  (`fileio.atomic_write_text`: temp file + fsync + `os.replace`). A crash or failing write can no
  longer leave a truncated plan or profile.

## 2026-09-27 - Rules cover one-line coach notes

### Changed
- `free_text_rules.py` also understands weekday-first headers (`вт 3.03: …`), weekday-only
  headers (`чт: …`), a `Название: …` title, sentences wrapped over lines, and several steps in
  one line separated by commas / «затем» / «потом» (a part without a distance or duration belongs
  to the previous step; `отдых …` after an interval is its recovery). HR ranges followed by
  punctuation (`пульс 135-145,`) are recognised.
- New precision guards: a unit without a number (`километр заминки`, `км разминки`, `беги час`)
  and a warmup mentioned after the main work (or cooldown before it) send the workout to the LLM.
- Golden dataset: 26 of 59 valid variants parsed (was 15), none of the unclear/unsupported cases;
  all agree with the reference except one where the reference drops a stated distance.

## 2026-09-27 - Upper-only HR caps become 60-cap

### Changed
- "Пульс до 140" / "не выше 140" / "HR <= 140" is encoded as `hr_low: 60, hr_high: 140`
  everywhere (60 = typical resting HR, the watch alerts only above the cap): YAML repair (any HR
  step with only `hr_high`, previously 80 and cooldown only), the marked parser, the rules, the
  marked-source checks, the LLM prompt/contract/examples, and a repair of model-invented lower
  bounds when the source states only a cap. Lower-only bounds are still never completed.

## 2026-09-26 - Golden dataset in the LLM evaluation harness

### Added
- `garmin-fit-llm-eval --suite-from-golden` builds a suite from the golden dataset (59 cases:
  valid single-workout variants with `expected_steps`); suite cases may carry `expected_steps`,
  checked fact by fact by `llm/golden.py` (shared with the rules' regression test).

## 2026-09-26 - Smaller exes, nested Garmin import, constant-time API token check

### Changed
- The PyInstaller specs leave out the Telegram bot and Plan API modules and heavy optional
  packages the desktop apps never import (pandas, numpy, pytest, telegram, fastapi, uvicorn,
  rich, pygments, openpyxl, …): `FitWeaver.exe` shrinks from 65 MB to about 36 MB, which also
  shortens the onefile unpacking on every start.
- Garmin workouts with nested repeat groups (e.g. 3 sets of 4 × 400 m, as the app now uploads
  them) can be opened in the builder; a round-trip test checks YAML → Garmin → YAML.
- FIT integrity (`is_fit` + CRC) is checked in-process with the installed garmin-fit-sdk instead
  of one Python subprocess per file against the vendored `sdk/py` copy (same SDK version):
  12 files 1.37 s → 0.01 s. `doctor` no longer requires the vendored copy (it failed in the exe).
- `check_fit` no longer configures logging or calls `sys.exit` when imported (the GUI imports it
  in-process).

### Security
- The Plan API compares the `X-Api-Token` header in constant time (`hmac.compare_digest`).

## 2026-09-26 - Common workout lines parsed without the LLM

### Added
- `free_text_rules.py`: deterministic rules for workouts written the usual way (dated header,
  title, `Разминка: 2 км (5:45-6:00)`, `6x800м по 4:20-4:30, восстановление 400 м`,
  `5 циклов: 2 мин … + 3 мин …`, `СБУ: …`, `Итого: …`). A workout is converted only if every line
  is understood and every number is accounted for; non-running sessions, effort described only
  in words and unsupported structures (series, ladders) go to the LLM as before. The result
  goes through the marked-format compiler and validation.
- GUI, Plan API and `garmin-fit-llm` try the rules per workout first (`use_rules`); the eval
  harness keeps them off so LLM scores measure the model. Unambiguous coach shorthand is expanded
  first (`р2`, `з1`, `темп5`, `6х800`, `отд 400`, dotted paces, `+` chains). On the golden dataset
  the rules parse 15 of 59 valid variants, never parse any of the 18 unclear/unsupported cases,
  and differ from the reference only where the reference adds a target the text does not give.

## 2026-09-26 - Review generated plans as text

### Added
- The LLM tab can show a generated plan as marked text ("Показать как текст") instead of YAML and
  put it into the plan editor ("Править как текст"): fix it there and generate again — marked text
  compiles instantly without the LLM. `marked_plan.plan_data_to_marked_text()` renders YAML back
  to marked text that compiles to the same steps (nested repeats included).

### Fixed
- Russian counts in GUI statuses use the right plural form ("3 тренировки", not "3 тренировок").

## 2026-09-26 - Legacy template builder removed

### Removed
- The legacy build path (`generate_from_yaml.py` generated Python templates from YAML and
  `build_fits.py` executed them), `compare_build_modes.py`, `legacy_cli.py` and the
  `garmin-fit-legacy` command, with their `Scripts/` shims and the runner menu items. The direct
  builder was already the default everywhere; the legacy path doubled maintenance ("update both
  builders") and executed generated code. Archives no longer contain debug templates (old
  archives restore without them); the build report drops `build_mode`/`template_exports`
  (`report_version` 2).

## 2026-09-26 - Garmin upload skips already scheduled workouts

### Changed
- A live scheduled upload reads the Garmin calendar for the affected months first and skips
  workouts already scheduled on the same date under the same name; `--allow-duplicates`
  restores the old behaviour. The upload summary reports skipped workouts.

## 2026-09-26 - Local LLM generation: partial results, cache, progress, cancel

### Changed
- Plans with per-workout headers are always generated one workout per request (the old limit
  of 10 sent larger plans in one request that did not fit `num_predict`). Larger plans without
  headers get a warning that the answer may be cut off.
- A failed workout no longer discards the others: the successful ones are returned and the
  failures are listed (`GeneratedYamlResult.failed_segments`, also over the Plan API).
- Plan-wide notes before the first workout (zones, paces) are prepended to every workout request.
- Successful workouts are cached by model, options, system prompt and source text
  (`Build_artifacts/llm_segment_cache/` in the GUI): re-running an edited plan only regenerates
  the changed workouts.
- Ollama requests stream: the GUI shows "workout 3/10" and answer progress and has a Cancel
  button; requests keep the model loaded (`keep_alive: 30m`) and the GUI warms the model up when
  the LLM tab opens.

## 2026-09-26 - GUI runs commands in-process

### Changed
- GUI sidebar actions run `garmin_fit.cli` in-process (`cli_runner.run_cli_captured`) instead of
  starting `garmin-fit-cli.exe`/`python -m`: no ~4.5 s onefile unpack per action (including the
  automatic YAML check after loading a plan); `FitWeaver.exe` no longer needs the CLI exe beside it.
- Workflow steps call each module's `main(argv)` in-process.

### Fixed
- In the packaged CLI, `validate-fit`, `archive`, `list-archives` and `restore` ran
  `sys.executable -m …`, which fails inside a frozen exe.
- `archive`/`restore` asked for confirmation on stdin, which the GUI does not have. They take
  `--yes`; the GUI confirms in a dialog. Missing stdin now cancels instead of crashing.
- Log files are written as UTF-8 (Cyrillic messages failed with the Windows ANSI code page).

## 2026-09-26 - Garmin Connect and FIT correctness fixes

### Fixed
- Nested repeats uploaded to Garmin Connect repeated the inner body one extra time per outer
  iteration (the inner steps were emitted both inside and next to the inner group). Repeats are now
  folded into a tree with a stack; overlapping (non-nested) ranges are rejected.
- SBU blocks inside a repeat ignored the requested language (always Russian labels).
- Steps that could not be mapped were silently dropped from the uploaded workout. They now raise
  `StepMappingError` naming the step, so that workout fails instead (dry-run reports it too).
- Auto-detected workout year moved past dates a year ahead (yesterday → next year), so
  `--skip-past` never skipped anything; `02-29` crashed in non-leap years. The year is now picked
  from last/this/next year by the filename's weekday token and proximity to today.
- FIT distances were truncated by float error (`int(1.15 * 100) == 114`): 287 of the 10-m
  distances up to a marathon were 10 m short on the watch. Conversions now round.

- The GUI passed the Garmin password to the CLI as `--password`, exposing it on the process
  command line and writing it in clear text to the GUI log (the command line is logged). It now
  travels only in the child's `GARMIN_PASSWORD` environment variable.
- LLM segment headers without a year were dated in 2025 (hard-coded), giving wrong weekdays in
  workout names. `infer_date()` now picks the nearest real date for the LLM path, the marked
  parser and filename dates alike.

### Added
- `tests/test_fit_garmin_equivalence.py`: executes the FIT steps and the Garmin payload of the
  same YAML and checks the runner does the same thing.

## 2026-09-26 - Deterministic parser for the marked plan format

### Added
- `src/garmin_fit/marked_plan.py`: plans written in the marked format (`==== ТРЕНИРОВКА ====`,
  `**** ШАГ ****`, `**** ПОВТОР: N РАЗ **** … **** КОНЕЦ ПОВТОРА ****`) are parsed into a step
  tree and compiled to Garmin YAML without an LLM. Repeat offsets/counts (nesting included) are
  computed by code; missing facts are never invented and every simplification is reported with
  its source line. `render_marked_plan()` renders the tree back to canonical marked text.
- `plan_service.build_plan_draft()` routes marked text to the parser (GUI, Plan API); only free
  text reaches the LLM. The GUI LLM tab compiles marked text offline and reports
  "Разобрано без LLM"; HR zones `Z1–Z5` resolve from the active profile.
- `garmin-fit parse-marked TEXT [--output YAML] [--year] [--profile]` CLI command.
- User guide `docs/MARKED_PLAN_FORMAT.md` and `examples/marked_plan_example.txt`.

### Merged
- Parallel line of 2026-09-03…17 merged; the local LLM design wins where the two conflict.
  Taken from it: CI matrix (3.10/3.12/3.13), GUI toolkits excluded from the CLI exe, one shared
  retry budget (`MAX_RETRIES`) in `plan_service`.

### Removed
- FunctionGemma 270M fine-tune experiment (did not work): `docs/llm_finetune/` scripts and
  `run_finetune.bat`. The golden dataset moved to `docs/golden_dataset/`.
- `tests/test_llm_pipeline_regressions.py`, which tested the other line's LLM client.

## 2026-09-24 - Simpler profile setup

### Changed
- New Garmin profiles now collect email and password together. The password stays in memory only
  and is also available beside the profile selector; it is cleared on profile switch or exit.
- HR setup asks only for maximum heart rate, which derives the Z1–Z5 ranges used by LLM prompts
  and the workout builder. Resting heart rate is no longer requested or written by the GUI.

## 2026-09-23 - Garmin calendar editing and cadence targets

### Fixed
- The Garmin calendar now recognizes schedule IDs exposed as `scheduleId` or `id` by some
  response shapes. Selecting an event without a schedule ID explains why editing is unavailable.
- Garmin `pace.zone` targets now import as editable pace ranges; the two m/s bounds are normalized
  regardless of their order in the Garmin response.

### Added
- Garmin Connect calendar events with a schedule ID can be opened in the builder and saved back.
  The app uploads and schedules the edited copy before removing the old calendar assignment;
  the original workout template stays in the Garmin library.
- Added cadence target ranges (`cad_low` / `cad_high`) for distance- and time-based steps across
  YAML validation, FIT generation, Garmin Connect payloads, LLM schema, and the builder.
- Added dedicated pace/cadence blocks and a profile based Z1–Z5 picker that applies BPM ranges.

### Safety
- Garmin workouts with unsupported step or target formats are rejected for editing so the import
  cannot silently discard instructions.

## Unreleased

### 2026-09-07 - Nested repeats, and a lighter CLI executable

#### Added
- Nested `repeat` blocks are allowed, so sets of intervals ("3 sets of 4x400m")
  can be expressed. The ban came from the v8.4 prompt checklist and had outlived
  its reason: `plan_validator` already distinguished containment from crossing
  and rejected only the latter, and the Garmin mapper emits nested
  `RepeatGroupDTO`s. Previously the model had to flatten such a workout into 12
  straight reps, losing the between-sets recovery.
- Two nesting tests for the FIT builder, which had none. The important one covers
  nesting after an `sbu_block`: that is the only step type expanding into several
  FIT steps, so both anchors of a nested pair must be translated through
  `build_yaml_to_fit_index`.

#### Changed
- `fitweaver_cli.spec` no longer bundles the GUI toolkits. A blanket
  `collect_submodules("garmin_fit")` reached `gui_theme`, whose lazy
  `import customtkinter` PyInstaller follows statically, so the console exe
  carried all of customtkinter and tkinter -- while `import garmin_fit.cli` pulls
  in no tkinter modules at all. 28.0 MB -> 24.7 MB.

#### Decided
- The two executables stay separate. Merging them behind a `--cli` flag would
  force one Windows subsystem on both: a windowed build run from a terminal
  returns the prompt immediately and prints nothing visible, which is how the CLI
  is actually used. The GUI's shell-out reads a pipe and is indifferent, so the
  merge would trade a working standalone CLI for one fewer file.

### 2026-09-07 - Consistency pass: docs vs code

#### Fixed
- **Bot setup guide described an architecture removed two versions ago.**
  `docs/TELEGRAM_SETUP.md` told users to put `llm_model` / `llm_url` /
  `llm_api_type` in `bot_config.yaml`. The bot has not read those keys since it
  moved behind the Plan API; `telegram_bot.py` requires `plan_api_url` and
  `plan_api_token`, so a config built from the guide failed at startup. The
  guide now walks through starting `garmin-fit-api` first, and its
  troubleshooting distinguishes "Plan API unreachable" from "LLM behind the API
  unreachable".
- **One retry budget instead of four.** `llm.client.MAX_RETRIES` was 2, but
  `plan_service`, `api_client` and `api.schemas` each defaulted to 3 (so the bot
  got 3) while the GUI hardcoded 1 in both connection modes. The GUI therefore
  gave up on the first malformed YAML where the CLI recovered. All entry points
  now default to `MAX_RETRIES`, pinned by regression tests.
- **Docs that described removed mechanisms.** `LLM_VALIDATION_SYSTEM.md`
  documented a 16-point prompt checklist and a contract sample with keys the
  contract does not have; `PROJECT_FLOW.md` documented segmented generation.
  Both were accurate for v8.4 and were carried forward unedited -- the checklist
  became `llm_contract.yaml`, and segmentation was deliberately removed on
  2026-09-06. Corrected, with historical notes explaining the change.
- `README.md` / `README.ru.md` / `docs/README.md` recommended
  `--openai-mode completions`, the mode the 2026-09-06 session identified as the
  cause of context exhaustion on LM Studio. Now `auto`, matching the code default.
- `docs/GARMIN_CALENDAR.md` suggested installing an unpublished PyPI package;
  `api_config.yaml.example` pointed at `bot_config.yaml` keys that no longer
  exist; `request_cli.py`'s `--model` help omitted the `@iq3_xxs` suffix, so
  copying it targeted a model LM Studio does not have loaded.

#### Changed
- Test temp bootstrap moved from `tests/test_000_temp_bootstrap.py` into
  `tests/conftest.py` and out of the repository. It only took effect when the
  whole directory was collected, so single-file runs landed in the machine's
  system temp; and its in-repo location meant every scratch directory was queued
  for OneDrive sync. It now prefers `$FITWEAVER_TEST_TMP`, then a named
  directory under the system temp, and keeps the repo-local path as a
  documented fallback.
- CI runs a Python matrix of 3.10 / 3.12 / 3.13. It previously tested only 3.13
  while `requires-python` declares `>=3.10`, leaving the floor uncovered.
- `CLAUDE.md` synced with `AGENTS.md` / `TODO.md`: localhost LM Studio canon,
  current test count, `.[gui]` extra documented.
- Both Windows executables rebuilt so the frozen build carries the shared retry
  budget. Verified that the lazily imported GUI modules (`plan_store`,
  `workout_builder`, `profile_store`, `api_client`, `gui_theme`,
  `garmin_calendar_export`) are present in the build's TOC -- PyInstaller drops
  those silently when the build is run from the live tree instead of the
  staging copy, with no build-time error.

### 2026-09-06 - Free-form plans and local LM Studio

#### Fixed
- Full plan text is sent to the model in **one request**. Automatic segmentation
  into 2-10 blocks was dropped: it lost the shared context of the plan and
  cross-day references such as "repeat Tuesday's workout".
- Removed guessing of `repeat` and `back_to_offset`. An invalid repeat anchor is
  now rejected by the validator rather than silently rewritten to a wrong step.
- Positional intensity defaults (first step -> warmup, last -> cooldown) removed;
  intensity is only set when the source states it.
- Windows proxy no longer swallows loopback LLM requests; `auto` detects a
  native LM Studio endpoint and uses it with reasoning disabled and an output
  budget derived from the loaded context length.
- Valid YAML with an unusual key order is no longer corrupted by the indentation
  heuristic. `<think>` prefixes, truncated responses and incomplete chat replies
  are handled explicitly.
- `distance_km` is recomputed from fully distance-based steps and `repeat`.

#### Changed
- Canonical LLM endpoint is local LM Studio at `http://127.0.0.1:1234` with
  `qwen3.8-27b@iq3_xxs`. The LAN Qwen server is retired.
- `openai`/`pydantic` declared in dependencies; `auto` mode unified across GUI,
  doctor and benchmark.
- Both Windows executables rebuilt from an isolated staging copy.

### 2026-09-04 - Markdown plans and interval reliability

#### Fixed
- Markdown headers of the form `### date, day - title` (including indentation
  and the comma) are parsed into separate workout blocks; previously the whole
  plan reached the model as one lump and workouts could be lost.
- Days containing only strength work, sauna or general conditioning are no
  longer counted as separate running workouts.
- The GUI shows LLM generation errors instead of a false "ready - 0 workouts".
- An obvious step `type` is recovered from the step's own fields before
  validation.

#### Changed
- Prompt strengthened on exact workout count, fact preservation, intervals and
  repetitions; `easy_drills` synced with the contract.

## 2026-09-02 - Consistency pass (v10.5.0)

### Changed
- Version bumped to 10.5.0 across `pyproject.toml`, `src/garmin_fit/__init__.py`,
  `fitweaver_gui.py` and `version.txt`.
- Project folder renamed from `Garmin8.8` to `FitWeaver10.5` (the old name tracked
  a version scheme retired at v9.0).
- Session journal now lives only in `AGENTS.md`; CLAUDE.md keeps the working rules
  and points at it. Stale "Next tasks" lists synced with `TODO.md`.
- `ruff` `target-version` lowered to `py310` to match `requires-python`.

### Fixed
- `docs/YAML_GUIDE.md` pointed at the removed `Scripts/llm/*.yaml` duplicates
  instead of the canonical files under `src/garmin_fit/llm/`.
- Test counts claimed in CLAUDE.md and AGENTS.md corrected to the actual suite.
- Removed a BOM from this file, an unused `tempfile` import in the GUI, and a
  dead variable in `tests/test_plan_store.py`; import blocks sorted.

## 2026-07-11 - Desktop GUI completion (v10.4.1)

### Added
- Desktop GUI (`fitweaver_gui.py`): 4 tabs — Calendar, LLM Generator,
  Constructor (visual builder), Garmin Connect.
- Simple / Expert UI modes.
- Per-email profile isolation (working plan, HR zones, Garmin session).
- SQLite staging layer (`plan_store`) with write-through to canonical YAML,
  and a visual workout builder with draft validation + safe repeat-step editing.
- Dual standalone Windows builds: `FitWeaver.exe` + `garmin-fit-cli.exe`
  (PyInstaller staging that avoids the root compatibility bridge package).
- Always-visible log panel with friendly error hints; onboarding "next step"
  card; in-header version display; non-blocking update check.
- Garmin Connect tab: explicit connection check, MFA in a modal (not hidden
  stdin), safe logout, per-profile operation history, diagnostics export.
- Busy-state guards so conflicting GUI/CLI operations cannot be double-started.

### Changed
- Session log history moved to `version.txt`; detailed notes in git log.
- README/README.ru synchronized to the 4 tabs and the two exe.

### Fixed (post-audit, 2026-09-02)
- GUI LLM error path no longer references a cleared exception variable
  (previously could leave the UI locked after an unexpected LLM error).
- `validate-yaml`/build no longer crash on symbolic pace constants
  (`EASY_F`, ...): ordering check resolves them via `PACE_CONSTANT_VALUES`.
- Garmin Calendar upload now runs repair+validation before upload (no more
  silently-truncated workouts).
- `state_manager`: fresh-state `time_created` uses current time (was a
  hardcoded 2026-02-06); lock file no longer unlinked after unlock (race);
  `reset_state` runs under the process lock.
- `save_workout` allocates a collision-safe serial/timestamp when none given
  (no more default `12345`).
- `llm/benchmark` `ROOT` -> `PROJECT_ROOT` (was a `NameError` on first run).
- REST mapper nested-repeat offset fixed; validator rejects crossing repeat
  ranges (fully-nested repeats remain allowed).
- `test_telegram_bot_cancel` no longer hangs the suite on Python 3.10
  (`asyncio.to_thread` neutralized in the tests).

## 2026-06-28 - GUI-first cleanup

### Removed
- Obsolete repository-root launcher scripts: `get_fit.py`, `run.py`,
  `validate_yaml.py`, `run_pipeline.bat`, and `run_pipeline.sh`.

### Changed
- README quick starts now make `python fitweaver_gui.py` the primary local
  workflow and keep package CLIs as the automation path.
- Legacy compatibility docs now point users away from root launchers and toward
  the GUI / `python -m garmin_fit...` commands.
- CLI follow-up hints no longer reference removed `get_fit.py` commands.

---

## 2026-04-23 — v10.4.1 (SBU Localization)

### Fixed
- **SBU drill labels in Garmin Calendar** are now shown in the user's chosen language.
  - Recovery step: `"Отдых"` (ru) / `"Recovery"` (en)
  - Unnamed drill fallback: `"Упражнение N"` (ru) / `"Drill N"` (en)
  - `DEFAULT_DRILLS` names (`"Выс.бедро"`, `"Захлест"`, etc.) were already in Russian.
- `GarminCalendarExporter` accepts `language` parameter; Telegram bot passes `_lang(user_id)` when creating the exporter, so the language follows the user's `/start` choice.

---

## 2026-04-23 — v10.4 (Code Quality Pass)

### Added
- **Interactive runner** (`python -m garmin_fit.runner`): loop-based menu with 14 options
  covering all workflows — LLM generation, direct build, Garmin Calendar upload/delete/dry-run,
  archive management, validation. Reads `GARMIN_EMAIL` / `GARMIN_PASSWORD` from env or prompts.
- **`workout_utils.build_yaml_to_fit_index()`**: canonical implementation for domain-object step lists,
  shared by both build paths. Eliminates duplicate logic between `build_from_plan.py` and `generate_from_yaml.py`.

### Fixed
- **`Scripts/telegram_bot.py` silent exit:** shim replaced `sys.modules["__main__"]` but never
  called `main()`. Added `if __name__ == "__main__": raise SystemExit(_impl.main())`.
- **Duplicate log handlers:** `setup_file_logging()` now guards against adding a second
  `FileHandler` to the root logger when called more than once in the same process.
- **Silent date parse failure in calendar export:** `_date_in_range()` now logs a warning
  when a workout filename date is unparseable, instead of silently including it in all ranges.
- **Silent data loss in domain layer:** `plan_from_data()`, `workout_from_data()`, `step_from_data()`
  now log a warning with a count when non-Mapping items are filtered from lists.
- **`pip install` Python version constraint:** `requires-python` changed from `>=3.13` → `>=3.10`.

### Improved
- **Partial build failure reporting:** `build_all_fits_from_plan` now lists the names of failed
  workouts in the final summary and warns about partial results left in `Output_fit/`.
- **`test_config.py` test isolation:** replaced manual `importlib.reload` cleanup with
  `setUp`/`tearDown` methods; `tearDown` is guaranteed to run even when a test raises.
- **HR upper bound:** added `le=250` to all HR fields in Pydantic schema — previously `hr_high=500` was accepted.
- **Pace validation deduplication:** `_validate_pace()` removed from `plan_validator.py`;
  both modules now use `_is_valid_pace()` from `plan_schema.py`. Same for `_check_pace_ordering()`.
- **`llm/benchmark.py`:** removed unused `ROOT` intermediate variable; `DEFAULT_SUITE` uses `PROJECT_ROOT` directly.
- **`check_fit.py`:** hardcoded `1_000_000` byte threshold extracted to named constant `_LARGE_FILE_BYTES`.

### Documentation
- `README.md` / `README.ru.md`: added Garmin Calendar Delete section, improved runner description.
- `docs/PROJECT_FLOW.md`: fixed `python -m garmin_fit.check_fit` → `python -m garmin_fit.cli validate-fit`.
- `docs/LLM_VALIDATION_SYSTEM.md`: removed broken links to removed doc files.
- `CLAUDE.md`: expanded with module list, `back_to_offset` critical note, pipeline overview.

### Verified
- Unit suite: `python3 -m pytest tests/ -q` — 196 tests passing.
- Ruff: `ruff check src/` — clean.

---

## 2026-04-20 — v10.3 (LLM Speed Fix + UX Polish)

### Added (UX)
- **3-message YAML preview:** YAML is now sent as a separate standalone message
  after the status line, making it trivial to copy in Telegram without selecting
  around surrounding text. Footer ("send /build") is a third message.
- **Delivery keyboard after Garmin upload:** when a ZIP is still available after
  uploading to Garmin Calendar, the bot immediately re-sends the delivery keyboard
  so the user can also download the ZIP without typing `/build`.

### Fixed (UX)
- **`/send_to_garmin` status:** after a successful upload the bot now correctly
  sets status to `awaiting_delivery_choice` only when the ZIP file actually exists
  on disk; otherwise resets to `idle`.
- **Dead i18n key removed:** `delivery_choice_busy` was defined but never sent —
  removed from both RU and EN message dictionaries.

---

## 2026-04-20 — v10.3 (LLM Speed Fix)

### Fixed
- **Thinking mode causing 3+ minute hangs on Gemma-4 / Qwen3:**
  `_call_openai_chat` now passes `extra_body={"chat_template_kwargs": {"enable_thinking": false}, "thinking": {"type": "disabled"}}`.
  LM Studio forwards these to llama.cpp, preventing the model from silently reasoning for 180+ seconds.
- **`source_fact_mismatch` triggering retries:** demoted from validation error to warning.
  This soft date/distance heuristic check was the trigger for retries; a retry with
  feedback is what activated thinking mode on the second call.
- **`source_fact_mismatch` demotion order:** source fact checks now run before
  demotion, so the heuristic cannot be re-added as a blocking error after it was
  converted to a warning.
- **Single upper HR cap in cooldowns:** `до 130` / `HR <= 130` is documented in
  the prompt as `hr_low: 80`, `hr_high: <cap>`, and the YAML repair layer
  applies the same fallback to cooldown `hr_low: null` or `hr_low >= hr_high`.
- **Excessive retries:** `MAX_RETRIES` reduced 3→1; `SUSPICIOUS_SEGMENT_RETRIES` 1→0.
- **Telegram delivery buttons after restart:** stale inline delivery callbacks now
  check that the temporary ZIP still exists and ask the user to rebuild with
  `/build` instead of trying to upload missing artifacts.
- **`/cancel` during LLM generation:** cancellation is acknowledged while the LLM
  request is running, then processing stops immediately after the model returns.
- **Telegram network timeout during Garmin login:** transient `TimedOut` /
  `NetworkError` from status replies no longer aborts Garmin authentication.
- **Garmin login after build:** `/connect_garmin` now restores the previous bot
  state after authentication, so a built plan in `awaiting_delivery_choice` is
  not forgotten.
- **Garmin delivery fallback:** choosing Garmin before connecting no longer
  deletes the pending ZIP or clears delivery state.
- **Garmin upload after archive:** `/send_to_garmin` now falls back to in-memory
  `yaml_text` when the build YAML file has already been moved to `Plan/plan_done/`.
- **ZIP availability after Garmin upload:** successful Garmin upload no longer
  deletes the pending ZIP; `/build` can re-send delivery buttons so the user can
  still download the same FIT bundle.

### Changed
- System prompt compressed: VALIDATION CHECKLIST 16 lines → 5 lines.
  Token count ~1419 → ~1141 (~275 tokens saved, ~20% faster prompt processing).
- Telegram text messages that start with `workouts:` are treated as ready YAML,
  validated/repaired, and loaded without an LLM call.
- `/build` while delivery buttons are pending now asks the user to choose a
  delivery option instead of incorrectly saying there is no confirmed YAML; if
  the original inline keyboard was replaced by a Garmin warning, `/build`
  re-sends the delivery buttons.
- Garmin upload success messages now include the next steps: how to get the ZIP,
  how to start a new LLM plan, and how to clear the Garmin session.
- `docs/TELEGRAM_SETUP.md` troubleshooting now reflects the remaining causes of
  long LLM generation after the retry fixes.
- `docs/YAML_GUIDE.md` documents valid HR ranges and the recommended handling for
  single upper HR caps.

### Verified
- Unit suite: `python -m unittest discover -q` - 192 tests passing.
- Ruff on changed Python files: `python -m ruff check ...` - passing.

### Expected timings after fix
| Plan size | Before | After |
|-----------|--------|-------|
| 1 workout | ~73s (ok) + potential 236s retry | ~70s, no retry |
| 2 workouts | timeout (300s) | ~140s |

---

## 2026-04-20 — v10.2 (Telegram Bot UX Overhaul)

### Added
- **Bilingual UI (RU / EN):** `/start` now shows a language selector inline keyboard.
  Language is stored in `UserState.language`, preserved across `/cancel` resets.
  All 77 user-visible strings live in `MSG["ru"]` / `MSG["en"]`; accessed via `_m(user_id, key)`.
- **Delivery choice buttons:** after `/build` the bot shows an inline keyboard
  `[📁 Send FIT files (ZIP)] [📅 Upload to Garmin Calendar]` instead of
  auto-sending the ZIP. New state `awaiting_delivery_choice` blocks new plans
  until the user picks or `/cancel`s.
- **`/howto` command:** bilingual inline loading guide (USB, Garmin Express, Garmin Calendar).
- **`docs/HOW_TO_LOAD.md`:** full bilingual step-by-step loading instructions (RU + EN).
- **`/delete_workout` command:** delete last uploaded batch, list all, or delete all.
- **YAML file upload:** send `.yaml` / `.yml` directly to skip LLM generation.
- **`python -m garmin_fit.bot`:** fixed missing `if __name__ == "__main__"` guard.

### Fixed
- **LM Studio "Empty response from LLM":** `UnifiedLLMClient` now auto-appends `/v1`
  to `base_url` when `api_type="openai"` and the URL doesn't already end with `/v1`.
  Both `http://127.0.0.1:1234` and `http://127.0.0.1:1234/v1` now work correctly.
- **Per-user Garmin token isolation:** CLI and bot each use a per-email / per-user-id
  token directory, preventing cross-account contamination in multi-user setups.

### Changed
- Welcome messages (RU + EN): clearer YAML reuse tip, explicit bpm advice,
  Garmin account + privacy notice, reference to `/howto`.
- Example workouts: zone notation replaced with explicit HR bpm ranges;
  SBU example uses `drill / rest / reps` format; removed LLM-confusing phrases.
- `docs/TELEGRAM_SETUP.md` fully rewritten: new flow diagram, state table,
  LM Studio `/v1` troubleshooting, loading section.

---

## 2026-04-16 - v10.1 (Garmin Calendar SBU Notes)

### Changed
- `src/garmin_fit/garmin_step_mapper.py` - Garmin Calendar SBU export now uses
  one repeat group per drill, preserving each drill's `name`, `seconds`, and
  `reps` instead of flattening SBU into a generic fixed-time block.
- SBU active steps now set `ExecutableStepDTO.description`, the Garmin Connect
  "workout step note" field, so mobile Garmin Connect shows the drill
  instruction for the current step. Recovery steps are labeled `Recovery`.

### Added
- `garmin-calendar` CLI date-range filters are documented:
  `--from-date YYYY-MM-DD` and `--to-date YYYY-MM-DD`.
- `docs/GARMIN_PAYLOAD_SPEC.md` documents `ExecutableStepDTO.description`
  and the SBU repeat-group shape used for Calendar uploads.

### Verified
- Unit suite: `python -m unittest discover -q` - 178 tests passing.
- Live Garmin Connect mobile check on 2026-04-16: SBU step notes are visible
  after direct Calendar upload.

---

## 2026-04-15 — v10.0 (Garmin Calendar Export — cloud delivery, no USB)

### Added
- `src/garmin_fit/garmin_auth_manager.py` — thin wrapper over `garmin-auth`.
  `GarminAuthManager.connect()` returns an authenticated `garminconnect` client.
  Factories: `from_env()` (reads `GARMIN_EMAIL` / `GARMIN_PASSWORD`), `for_telegram()` (async MFA).
  `resume(mfa_code)` completes MFA in two-step flow.
- `src/garmin_fit/garmin_step_mapper.py` — maps all 9 YAML step types to Garmin
  workout-service REST API dicts (`ExecutableStepDTO`, `RepeatGroupDTO`).
  `map_workout()` builds a complete payload; `extract_date_from_filename()` auto-detects
  workout calendar date from filename pattern `W{week}_{MM-DD}_…`.
- `src/garmin_fit/garmin_calendar_export.py` — `GarminCalendarExporter` class.
  `upload_plan()` uploads and schedules all workouts; `dry_run` mode previews without
  API calls; 1.2 s rate-limit delay between uploads.  `publish_plan_to_garmin()`
  one-shot convenience function.
- `docs/GARMIN_PAYLOAD_SPEC.md` — reverse-engineered Garmin workout-service REST API
  specification (ExecutableStepDTO, RepeatGroupDTO, HR/pace target field names).
- `docs/GARMIN_CALENDAR.md` — user setup guide: install, credentials, MFA, CLI flags,
  date mapping, rate limits, troubleshooting.
- `pyproject.toml` — optional dependency group `[garmin-calendar]`
  (`garminconnect>=0.3.0,<0.4.0`, `garmin-auth>=0.3.0,<0.4.0`).
- `tests/test_garmin_step_mapper.py` — 64 tests covering all step types,
  repeat-body consumption, sbu_block expansion, date extraction, payload shape.
- `cli.py` — new `garmin-calendar` subcommand with `--plan`, `--email`, `--password`,
  `--token-dir`, `--year`, `--no-schedule`, `--dry-run` flags.
- `workflow.py` — `workflow_garmin_calendar()` orchestrator function.
- `runner.py` — menu options **G** (live upload) and **D** (dry run).

### Fixed
- `garmin_step_mapper.py` — `map_steps()` repeat-body-consumption bug: body steps were
  emitted as both standalone steps and repeat-group children.  Fixed by pre-scanning
  repeat boundaries before the emit loop.
- `cli.py`, `legacy_cli.py`, `validate_cli.py` — missing `if __name__ == "__main__":`
  guard caused complete silence when invoked via `python -m`.
- `garmin_calendar_export.py` — replaced `→` and `…` with ASCII equivalents for
  Windows cp1252 terminal compatibility.
- `workflow_garmin_calendar()` — replaced `logger.info/error` with `print()` for
  reliable terminal output.

### Verified
- End-to-end test on 2026-04-16: 1 workout uploaded (workout_id=1538061488),
  scheduled to 2026-05-01, confirmed visible in Garmin Connect Calendar.

---

## 2026-04-15 — Research: Garmin Calendar Export (planned v10)

Investigated direct delivery of workouts to Garmin Connect Calendar (no USB required).

**Finding:** unofficial Python libraries cover the full flow without official API approval:
- `garminconnect` (cyberjunky) — `upload_running_workout()`, `schedule_workout(workout_id, date)`, step helpers
- `garmin-auth` (drkostas) — token persistence (file/PostgreSQL), MFA support, rate limit handling

**Planned architecture:** two export backends from the same YAML domain objects —
`FitExporter` (current, kept as fallback) + `GarminCalendarExporter` (new).

Reference implementation: [hevy2garmin](https://github.com/drkostas/hevy2garmin) — same stack for completed activity upload.

See `docs/ROADMAP.md` → "Planned: Garmin Calendar Export (v10)" for full plan.

---

## 2026-04-06 — v9.2 (Telegram Bot — Clean ZIP, Clarification Flow)

### Changed
- `telegram_bot.py` — `_create_plan_zip()`: rewritten. ZIP now contains only `input_plan.txt` (user's original plan text) and `.fit` files. Artifacts, build reports, and Python templates removed from user-facing output.
- `telegram_bot.py` — ZIP always sent regardless of file count (previously: media group for ≤10 files, ZIP for >10).
- `telegram_bot.py` — ZIP folder structure changed to `YYYY/MM/decade-N/` (decade-1: days 1–10, decade-2: 11–20, decade-3: 21–31).
- `tests/test_telegram_bot_cancel.py` — `test_create_plan_zip_exports_templates_when_workspace_is_empty` replaced with `test_create_plan_zip_contains_only_input_and_fit` to match new ZIP contract.

### Added
- `telegram_bot.py` — Ambiguity clarification flow: when LLM returns `ambiguities`, bot enters `awaiting_clarification` state and asks the user to clarify before building. User can reply with clarification text (triggers one re-generation) or send `/build` to proceed as-is.
- `UserState.original_plan_text`: stores the exact user input for ZIP inclusion.
- `UserState.active_plan_text`: stores the current generation input and may include appended clarification text.
- `UserState.pending_clarification`, `UserState.clarification_attempted`: state for one-round clarification loop.
- `_handle_clarification()`: handler appending user clarification to original plan text and re-running `_process_plan`.
- `_decade_label()`: helper returning decade folder name from a day-of-month integer.

### Fixed
- `telegram_bot.py` — `clarification_attempted` and related ambiguity state are reset when a user starts a new plan, so clarification flow works again for subsequent plans without requiring `/cancel`.
- `telegram_bot.py` — ZIP export now keeps the exact original user plan text even after a clarification round; appended `User clarification: ...` text is used only for re-generation input.
- `telegram_bot.py` — ambiguity handling now still runs after SBU resolution (`standard` or custom drills), so plans with both `sbu_block` and `ambiguities` no longer skip the clarification step.
- `tests/test_telegram_bot_cancel.py` — added regression coverage for clarification reset, exact ZIP text preservation, and `SBU -> clarification` transitions.

### Removed
- `telegram_bot.py` — unused imports: `TemporaryDirectory`, `InputMediaDocument`, `generate_all_templates`, `TEMPLATES_DIR`.

---

## 2026-03-31 — v9.1 (Clean Packaging, Import Migration, Runner Fix)

### Changed
- `pyproject.toml`: finalized clean src-layout — `package-dir = {"" = "src"}`, `find where=["src"]`. `Scripts*` removed from installed package (remains in repo as compatibility layer only).
- `garmin_fit/__init__.py`: replaced per-module shim files with a single bridge that extends `__path__` to `src/garmin_fit/`. All 30 shim files removed.
- `[project.scripts]`: proper console entry points (`garmin-fit`, `garmin-fit-legacy`, `garmin-fit-runner`, etc.) wired to `src/garmin_fit` modules.
- `src/garmin_fit/runner.py`: interactive menu now uses `importlib.import_module()` + `mod.main()` instead of `subprocess.run()`. Fixes silent output on Windows (PowerShell stdout inheritance issue).
- All tests migrated from `Scripts.*` imports to `garmin_fit.*`.
- All examples migrated: `sys.path.append(Scripts)` removed, `garmin_fit.*` imports used.
- All docs updated: primary commands now `python -m garmin_fit.*`; `Scripts.*` retained only in explicit compatibility notes.
- `README.md` / `README.ru.md`: fixed step numbering gaps (1→2→4 → 1→2→3).
- `.gitignore`: added `*.egg-info/`.

### Added
- `docs/SCRIPTS_DEPENDENCY_AUDIT.md`: records current Scripts exit criteria and compatibility decision.
- `src/garmin_fit/runner.py`: new interactive menu runner (replaces legacy `run.py`).

### Architecture
- `src/garmin_fit/` — canonical source (unchanged)
- `garmin_fit/` — bridge only (`__init__.py` extends `__path__`; no per-module files)
- `Scripts/` — compatibility layer, not part of installed package

---

## 2026-03-31 — v9.0 (Pydantic Validation, CI/CD, Documentation Overhaul)

### Added
- `src/garmin_fit/plan_schema.py`: Pydantic v2 schema layer — discriminated union models for all 9 canonical step types (`dist_hr`, `time_hr`, `dist_pace`, `time_pace`, `dist_open`, `time_step`, `open_step`, `repeat`, `sbu_block`) + `WorkoutSchema` + `WorkoutPlanSchema`.
- `WorkoutPlanSchema.model_json_schema()`: generates machine-readable JSON Schema for all step types — ready to embed directly in LLM prompts instead of text descriptions.
- `garmin_fit/plan_schema.py`, `Scripts/plan_schema.py`: alias and shim layers (follows three-copy pattern).
- `.github/workflows/ci.yml`: GitHub Actions CI pipeline — runs `ruff` lint + `pytest` on every push and PR to `main`.
- `pyproject.toml`: dev optional-dependencies group (`pydantic>=2.0`, `pytest>=8.0`, `pytest-asyncio>=0.23`, `ruff>=0.4`); `[tool.pytest.ini_options]` and `[tool.ruff]` config sections.
- `tests/test_plan_schema.py`: 38 new tests covering all step models, discriminated union dispatch, HR/pace ordering, duplicate filename detection, JSON Schema generation, and validator integration. Total test count: 60 → 98.

### Added (cont.)
- `llm/prompt.py` — `get_plan_json_schema()`: public function returning `WorkoutPlanSchema.model_json_schema()` for use in external tools (ChatGPT, Claude, etc.).
- `llm/prompt.py` — `_build_json_schema_section()`: compact step schema derived programmatically from Pydantic models (always in sync). Injected into prompt when `include_json_schema=True`.
- `create_system_prompt()` / `get_system_prompt()`: new `include_json_schema=False` parameter. Off by default to preserve token budget for local LLMs; enable for capable models (GPT-4, Claude API).
- `pyproject.toml`: duplicate `src.garmin_fit.llm` package-data key removed (was causing TOML parse error blocking ruff).
- `pyproject.toml`: ruff `ignore` extended with `W191`, `W291`, `W292`, `W293` (pre-existing tab/whitespace style); `per-file-ignores` for `Scripts/` and `garmin_fit/` shims (`F401`, `I001`, `E402`).
- `llm/__init__.py`: explicit re-export syntax (`X as X`) for public API symbols.
- `archive_manager.py`: `# noqa: E402` on post-logger imports (intentional pattern).

### Changed
- `plan_validator.py` — Pydantic structural pass (`_validate_with_pydantic`) prepended to `validate_plan_data_detailed()`; gracefully skipped if pydantic is unavailable.
- `README.md` split into two separate files: `README.md` (English only, shown by default on GitHub) and `README.ru.md` (Russian only), each with a link to the other.
- `user_profile.yaml` step removed from required workflow; documented as optional — only needed when the training plan uses zone names (Z2, easy) instead of explicit bpm values.
- `CLAUDE.md` — removed personal User profile section (HR zones, drill names in Russian).

### Documentation
- `docs/YAML_GUIDE.md`: added SBU / running drills definition (СБУ = Специальные Беговые Упражнения = running drills / form drills).
- `docs/LLM_CONNECTION_PROFILE.md`: reframed as example config (not personal settings); fixed corrupted code block (`\x08` backspace character).
- `docs/TELEGRAM_SETUP.md`: removed duplicate "Preferred Bot Command" / "Compatibility Note" sections; fixed broken code fences.
- `docs/README.md`: removed dead links (`YAML_VALIDATION.md`, `LLM_YAML_RULES.md`); removed duplicate appended sections.

---

## 2026-03-30 — v8.9 (LLM Workout Count, Structural Refactor, Bug Fixes)

### Added
- `--workouts N` flag in `Scripts/llm/request_cli.py`: explicit override for expected workout count, bypasses auto-detection entirely.
- Interactive fallback prompt in `request_cli.py`: when auto-detection returns 0 and `--workouts` is not set, user is asked "How many workouts does the plan contain?" before the LLM call.
- Phase-structured plan detection in `plan_processing.normalize_source_text()`: heuristic for Russian "ФАЗА / недели A–B / ### DayName" format (e.g. "16 weeks × 3 days = 48 workouts"). Used as auto-detection bonus; user prompt takes precedence when it fails.
- `SourceTextAnalysis.phase_weeks` and `days_per_week` fields: carry phase-plan metadata through to prompt builder.
- `generate_yaml_draft()` and `generate_yaml_from_plan()` now accept `workouts_hint: int = 0`: applied when `expected_workouts == 0` after source text analysis.
- Enhanced `_build_source_expectations_prompt()`: for phase-structured plans, adds explicit "generate ALL weeks" instruction to prevent LLM from stopping after one example per phase.
- New modules from structural refactor: `runtime_layout.py`, `plan_service.py`, `pipeline_runner.py`, `cli.py`, `legacy_cli.py`, `validate_cli.py`, `_shared_cli.py`, `bot.py`, `llm_cli.py`, `runtime_cli.py`.
- `GARMIN_FIT_RUNTIME_DIR` env var support in `config.py`: all mutable directories (Plan, Output_fit, Archive, etc.) now resolve relative to `RUNTIME_ROOT`, enabling isolated multi-instance deployments.
- Root `validate_yaml.py` shim for standalone YAML validation.
- 4 new test files: `test_config.py`, `test_runtime_layout.py`, `test_archive_manager.py`, `test_package_cli.py`.

### Fixed
- `plan_processing.py` — `REFERENCE_WEEK_YEAR` now uses `date.today().year` instead of hardcoded 2025.
- `plan_processing.py` — single-step workouts now get `intensity: active` instead of incorrectly receiving `warmup` or `cooldown`.
- `plan_validator.py` — added `pace_fast < pace_slow` ordering check (pace_fast must be a lower number = faster pace).
- `generate_from_yaml.py` — removed module-level `logging.basicConfig` (moved inside `__main__` block to avoid hijacking the root logger on import).
- `generate_from_yaml.py` / `orchestrator.py` / `workflow.py` — multiple YAML files in `Plan/` now prompt user to choose interactively instead of silently picking by mtime.

### Changed
- CLI split into primary (`cli.py`: `run`, `validate-yaml`, `validate-fit`, `doctor`, `archive`, `list-archives`, `restore`) and legacy (`legacy_cli.py`: `templates`, `build`, `compare`).
- Shared CLI utilities extracted to `_shared_cli.py` (`configure_logging`, `generate_run_id`).
- `Scripts/` shims now use copy-pattern (`globals()[name] = getattr(_impl, name)`) instead of `sys.modules` redirect for testability; `Scripts/config.py` additionally uses `reload` to support `importlib.reload()` in tests.

---

## 2026-03-18 — v8.8 (SBU Repeat Fix, ISO Week Numbering)

### Fixed
- `Scripts/build_from_plan.py` — added `_build_yaml_to_fit_index()` to translate YAML step indices to FIT runtime indices for `repeat` steps. Previously, `back_to_offset` was passed as-is to `repeat_step()`, causing the repeat to go back into the `sbu_block` body instead of the acceleration step. This is the **direct build path** (used by default in `workflow_full`).
- `Scripts/generate_from_yaml.py` — same YAML→FIT index translation applied to the legacy template-export path.
- `Scripts/plan_processing.py` — `_calendar_week_from_date()` now uses `date.isocalendar()[1]` (ISO Mon–Sun weeks) instead of the previous `((tm_yday - 1) // 7) + 1` formula that produced Thu–Wed boundaries when Jan 1 fell on Thursday.

### Details
- `sbu_block` expands into multiple FIT steps at build time (N drills × reps × 2). When a `repeat` step follows a `sbu_block`, the YAML step index for the repeat target (e.g. `back_to_offset: 2`) must be translated to the corresponding FIT runtime index (e.g. 17 for a standard 4-drill block starting at index 1). Both builders now do this via a pre-computed mapping.
- ISO week numbering means March 14 (Sat) = W11 and March 18 (Wed) = W12, matching real-world Mon–Sun calendar weeks.

---

## 2026-03-05 — v8 (SBU YAML Fixes, Intensity Prompting, Benchmark Expansion, Half-Marathon v3)

### Added
- `tests/fixtures/llm_benchmark/sbu_drills_suite.yaml` + `sbu_drills_2026_04.yaml`: SBU generate+existing benchmark (1/1 PASS).
- `tests/fixtures/llm_benchmark/half_marathon_2026_suite.yaml`: 44-workout existing-mode benchmark suite (13 checks).
- `LLM_input_test/sbu_benchmark/plan.txt`: SBU benchmark input plan (Russian, 6 km).
- `Plan/half_marathon_plan_FINAL_LT173_v3.yaml`: authoritative v3 YAML (correct Sat/Sun dates, `back_to_offset` fixed).

### Fixed
- `Scripts/llm/client.py` — `_sanitize_yaml_candidate`: regex `^(\s+)-` scoped to `^( {2,4})-` to avoid stripping drill list item prefixes.
- `Scripts/llm/client.py` — `_normalize_workout_yaml_indentation`: rewritten to preserve relative indentation within steps (previously flattened nested `sbu_block.drills` to step level).
- `Plan/plan_done/group_1.yaml`, `group_2.yaml`: added `intensity: warmup` on hills workout step[0].
- `Plan/half_marathon_plan_FINAL_LT173_v3.yaml`: fixed `back_to_offset: 17/25 → 2` (11 occurrences in archived YAML).

### Changed
- `Scripts/llm/prompt.py` FINAL INSTRUCTIONS: added explicit intensity rules (always set on dist_hr/dist_pace/time_hr/time_pace; first step → warmup; last non-repeat → cooldown).
- `Scripts/llm/llm_contract.yaml`: enhanced `sbu_block` notes with concrete wrong/correct YAML examples.
- `Scripts/llm/benchmark.py`: added `sys.stdout.reconfigure(encoding="utf-8")` for Windows cp1252 fix.

### Cleanup
- Removed superseded Plan files: `half_marathon_plan_FINAL.md`, `half_marathon_plan_final.yaml`, and 10 old interim YAML/MD drafts from `Plan/plan_done/`.
- Removed intermediate Build_artifacts: repaired YAMLs and comparison JSONs.

### Project renamed
- Root folder: `Garmin7` → `Garmin8`

---

## 2026-03-04 (LLM Contract, Segmented Generation, Benchmark)

### Added
- `Scripts/llm/llm_contract.yaml`: strict generation contract for YAML schema, enums, naming, and forbidden patterns.
- `Scripts/llm/strict_examples.yaml`: compact targeted few-shot examples for Russian plan text.
- `Scripts/llm/benchmark.py`: LLM quality benchmark runner with `existing`/`generate` modes.
- `tests/fixtures/llm_benchmark/plan_week_2026_03_02.yaml`: regression benchmark suite.
- `tests/test_llm_benchmark.py`: benchmark expectation tests.
- `docs/LLM_CONNECTION_PROFILE.md`: актуальный профиль подключения к модели и рабочие команды.

### Changed
- `Scripts/llm/prompt.py`: prompt переведен в contract-first формат с динамическим подбором примеров.
- `Scripts/llm/client.py`:
  - добавлены дополнительные sanitize-правила для completion-артефактов,
  - добавлен expected workout count контроль,
  - включена segmented generation (2-10 workout blocks -> generate per block -> merge).
- `Scripts/plan_processing.py`:
  - добавлен анализ source workout headers/blocks,
  - добавлены правила нормализации имени тренировки с календарной неделей,
  - поддержаны распространенные форматы дат (`01.12.2025`, `01.12.25`, `2.12`, `1 янв`, `8.03 (вс)` и др.).
- Обновлены `README.md`, `docs/README.md`, `docs/PROJECT_FLOW.md`,
  `docs/ARCHITECTURE_PROPOSALS.md`, `docs/LLM_YAML_IMPROVEMENTS.md`.

## 2026-03-04 (Direct Build, LLM Hardening, Docs Refresh)

### Added
- `build_from_plan.py`: direct `YAML/domain -> FIT` builder for the main pipeline.
- `plan_domain.py`, `plan_processing.py`, `plan_service.py`: shared domain model, input normalization/repair, and bot/service helpers.
- `plan_artifacts.py`: repaired YAML artifact and machine-readable `build_report.json`.
- `compare_build_modes.py`: isolated compare tool for `direct` vs `templates` parity checks.
- Structured validation issues and grouped retry feedback for LLM YAML generation.
- Archive fallback: if `Workout_templates/` is empty but a YAML plan exists, debug templates can be exported directly into the archive.
- Telegram ZIP fallback: the bot can include `templates/` exported from YAML on the fly when workspace templates are absent.
- `Build_artifacts/`: dedicated directory for generated `*.repaired.yaml` and `*.build_report.json`.
- `Build_artifacts/*.build_mode_compare.json`: diagnostics report for direct vs legacy builder comparison.
- Regression coverage for:
  - YAML normalization/repair,
  - structured validator categories,
  - direct FIT build,
  - archive template export fallback,
  - Telegram ZIP template export fallback.

### Changed
- Default generation flow is now `text -> YAML -> direct FIT build -> validation -> archive`.
- `orchestrator.py` now uses `build_mode="direct"` by default; template-based build remains available only as legacy/debug mode.
- `generate_from_yaml.py` now works from repaired plan data/domain objects and can export templates into an arbitrary target directory.
- `workflow.py`, `telegram_bot.py`, `README.md`, and docs now describe templates as optional debug artifacts instead of a required stage.
- Archive metadata now records `Templates source` so it is clear whether templates came from the workspace, were exported from YAML, or were absent.
- Pipeline now emits repaired YAML and JSON build reports and includes them in archives / Telegram ZIP bundles.
- `get_fit.py --compare-build-modes` now runs both build paths in isolated temp workspaces and compares decoded FIT output.
- `run_generation_pipeline()` result naming is standardized around `template_export_count` / `template_export_total_count`.

### Notes
- `python get_fit.py --templates-only` and `python get_fit.py --build-only` are preserved for debugging and backward compatibility.

## 2026-02-15 (Cross-platform & Bugfixes)

### Fixed
- `orchestrator.py` + `generate_from_yaml.py`: template stage now fails pipeline on partial generation (`generated != expected`).
- `archive_manager.py`: plan moves to `Plan/plan_done` now handle name collisions with suffixes (`_v2`, `_v3`, ...).
- `telegram_bot.py`: `/cancel` now cancels queued/active jobs via `cancel_requested` and prevents send/archive after cancellation.
- `state_manager.py`: cross-platform file locking â€” `msvcrt` on Windows, `fcntl` on Linux/macOS.
- `telegram_bot.py`: `run_id` now passed to `archive_current_plan()` for traceability.
- `telegram_bot.py`: SBU parse error no longer silently advances to `awaiting_confirm`;
  user stays in `awaiting_sbu_choice` and can retry or type "standard".
- `telegram_bot.py`: `BUILD_QUEUE` created inside event loop (`on_post_init`) instead of module level.
- `orchestrator.py`: `cleanup_runtime_dirs()` now removes `__pycache__` in `Workout_templates/`
  to prevent stale `.pyc` imports.
- `telegram_bot.py`: text and document handlers now reject input during active operations
  (`generating`/`queued`/`building`) to prevent accidental state reset.

### Added
- `tests/__init__.py` for proper test package discovery.
- `tests/test_archive_manager.py`: regression test for `plan_done` filename collision handling.
- `tests/test_orchestrator.py`: regression test for partial template generation failure.
- `tests/test_telegram_bot_cancel.py`: cancellation behavior tests (auto-skipped if Telegram deps are unavailable).

## 2026-02-14 (Reliability & Security Update)

### Added
- Telegram delivery modes:
  - up to 10 FIT files: single media-group message,
  - more than 10 FIT files: one ZIP bundle with `plan/`, `templates/`, `fit/`.
- Smarter archive naming:
  - timestamp down to seconds,
  - optional owner tag (Telegram user id),
  - automatic collision suffix (`_v2`, `_v3`, ...).
- FIT timestamp conversion helper:
  - `fit_timestamp_to_unix_ms()` in `state_manager`.

### Changed
- Pipeline success criteria tightened:
  - partial build or partial validation is now treated as failure.
- Full workflow now requires YAML plan files (`.yaml` / `.yml`).
- Validation failure now stops workflow before auto-archive.
- Windows temp handling in bot switched from hardcoded `/tmp` to system temp dir.
- YAML template generation hardened:
  - filename sanitization,
  - safe literal embedding for metadata,
  - unsafe output path guard,
  - latest YAML auto-selection when multiple files are present.

### Implemented in this iteration
- Added strict schema + semantic validator between LLM output and template generation.
- Added per-user bot state + build job queue + optional Telegram whitelist (`allowed_user_ids`).
- Added one shared orchestrator module used by both CLI full workflow and Telegram flow.
- Archive creation is now gated by complete successful validation.
- Added a very small `unittest` smoke suite:
  - `tests/test_plan_validator.py`
  - `tests/test_orchestrator.py`

## 2026-02-14

### Added
- Configurable SBU (Ð¡Ð‘Ð£) block â€” drills are no longer hardcoded.
  - `sbu_block.py`: `DEFAULT_DRILLS` constant + `drills` parameter in `sbu_block()`.
  - YAML format supports custom drills:
    ```yaml
    - type: sbu_block
      drills:
      - name: "Ð’Ñ‹Ð¿Ð°Ð´Ñ‹"
        seconds: 45
        reps: 3
    ```
  - `type: sbu_block` without `drills` key still uses the default set (backward compatible).
- Telegram bot SBU dialog:
  - New state `awaiting_sbu_choice` in bot flow.
  - When YAML contains `sbu_block`, bot asks user: standard drills or custom?
  - Custom drills accepted as free text, parsed by LLM into structured YAML.
- `llm_prompt.py`: added `SBU_DRILLS_PROMPT` for parsing user drill descriptions.
- `llm_client.py`: added `generate_custom()` method for secondary LLM calls.

### Changed
- `sbu_block.py`: replaced 5 hardcoded drill loops with one generic loop over `drills` list.
- `generate_from_yaml.py`: `sbu_block` handler passes `drills` to generated template code when present.
- `llm_prompt.py`: updated `SYSTEM_PROMPT` to document both default and custom `sbu_block` forms.

## 2026-02-08

### Added
- `run.py` interactive wrapper with menu options:
  - full workflow
  - templates-only
  - build-only
  - validate-only
  - archive/list/restore
- Validation mode switch in CLI:
  - `--validate-mode soft`
  - `--validate-mode strict`
- `run_id` traceability through workflow logs and archive metadata.
- Auto-template generation from YAML in full workflow when templates directory is empty.
- Auto-archive after successful full workflow.
- SBU step notes support (`notes`) in addition to step names.
- `PROJECT_FLOW.md` with current process documentation.

### Changed
- Main operational flow aligned to:
  - `MD -> YAML (LLM) -> templates -> FIT -> validation -> archive`
- Archive naming now prefers active YAML plan name (fallback to `.md`, then `plan`).
- Archive/restore now include plan files with extensions:
  - `.md`, `.yaml`, `.yml`
- Safer template module loading in FIT builder (spec/loader checks).

### Removed
- Deprecated generator entrypoint:
  - `Scripts/generate_templates.py`

### Validation
- Removed `Timestamp is very old` warning from FIT validation checks.

### Notes
- Recommended naming convention for logical watch ordering:
  - use identical `filename` and `name` in YAML
  - format example: `W0_01_Mon_Easy_6km`
