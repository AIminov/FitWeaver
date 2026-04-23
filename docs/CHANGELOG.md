# Changelog

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
