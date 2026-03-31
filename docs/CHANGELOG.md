# Changelog

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

