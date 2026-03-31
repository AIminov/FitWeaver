# Project Flow

## Актуальный end-to-end pipeline

1. Пользователь дает план в `.txt`, `.md` или сразу в `.yaml`.
2. LLM-пайплайн преобразует текст в YAML и сохраняет его в `Plan/*.yaml`.
3. Pipeline готовит build artifacts: repaired YAML и machine-readable build report.
4. Полный workflow `python get_fit.py` строит FIT напрямую из YAML/domain objects.
5. `check_fit.py` валидирует все файлы в `Output_fit/`.
6. При успехе выполняется автоархивация.

```text
 text/md -> YAML -> repaired YAML/report -> domain objects -> FIT -> validation -> archive
```

## Legacy / debug режимы

Python templates больше не обязательны для основного pipeline, но сохранены как дополнительный слой:

- `python get_fit.py --templates-only`
  - экспортирует debug templates из YAML в `Workout_templates/`
- `python get_fit.py --build-only`
  - legacy build path: `Workout_templates/*.py -> FIT`
- `python get_fit.py --compare-build-modes`
  - compare `direct` vs `templates` on one YAML and write `*.build_mode_compare.json`

Это нужно для:

- отладки
- сравнения output
- совместимости со старым workflow

## Validation и repair

До сборки FIT система использует:

- normalization source text
- deterministic YAML auto-repair
- schema validation
- semantic validation
- structured error categories for LLM retry

Примеры repair:

- синхронизация `filename` и `name`
- нормализация pace (`5.0` -> `5:00`, `6 00` -> `6:00`)
- нормализация step type (`distance_pace` -> `dist_pace`)
- default intensity для `dist_open`, `time_step`, `open_step`
- default `seconds` / `reps` для SBU drills

## LLM generation details

В актуальной версии генератор использует strict contract-first подход:

- системный промпт строится из `Scripts/llm/llm_contract.yaml`
- few-shot примеры берутся из `Scripts/llm/strict_examples.yaml`
- для OpenAI-compatible API поддержаны `auto/chat/completions` режимы
- в `auto` может быть fallback `chat -> completions`, если chat-ответ не содержит валидный YAML

Дополнительные меры устойчивости:

- sanitize ответа модели (`workouts:` root, отрезание reasoning-хвостов, нормализация отступов)
- проверка ожидаемого количества тренировок из source text
- structured retry feedback по категориям ошибок

Сегментированная генерация:

- если в тексте найдено 2-10 тренировочных блоков, каждый блок генерируется отдельно
- затем блоки объединяются в единый `workouts:` YAML
- это снижает ошибки длинного монолитного ответа

Нормализация имен тренировок:

- при явной дате используется формат `W{calendar_week}_{MM-DD}_...`
- календарная неделя = ISO week number (понедельник → воскресенье), вычисляется как `date.isocalendar()[1]`
- если даты нет, используется fallback-префикс `N{order}_...`
- поддерживаются даты вида `01.12.2025`, `01.12.25`, `2.12`, `02.12`, `1 Jan`, `1 January`, `1 янв`, `1 января`, `8.03 (вс)`

## Build modes

### Direct mode

Используется по умолчанию в:

- CLI full run
- `pipeline_runner.run_pipeline()`
- Telegram `/build`

Особенности:

- нет dynamic import generated templates
- меньше точек отказа
- проще тестировать

### Templates mode

Используется только когда это явно нужно:

- `--templates-only`
- `--build-only`
- `run_generation_pipeline(..., build_mode="templates")`

### Compare mode

Diagnostics-only path:

- `python get_fit.py --compare-build-modes`
- runs both `build_mode="direct"` and `build_mode="templates"` in isolated temp workspaces
- compares FIT filenames, workout metadata, and decoded step structures
- writes `Build_artifacts/*.build_mode_compare.json`

## Архивы и ZIP bundles

Архивы и Telegram ZIP больше не предполагают, что `Workout_templates/` уже заполнен.

Новое поведение:

- если templates есть в workspace, они архивируются как есть
- если templates нет, но есть YAML, система пытается экспортировать debug templates прямо в archive/ZIP
- если export невозможен, архив все равно создается без templates

В `archive_info.txt` пишется:

- `Templates archived`
- `Templates source`
- `Build artifacts archived`

Возможные значения `Templates source`:

- `workspace`
- `exported_from_yaml`
- `none`

## Telegram flow

```text
idle -> generating -> awaiting_sbu_choice -> awaiting_confirm -> queued -> building -> idle
```

Во время `generating` бот:

1. нормализует source text
2. генерирует YAML
3. применяет auto-repair
4. показывает preview с warnings/ambiguities

Во время `building` бот запускает:

```text
 YAML -> repaired YAML/report -> direct FIT build -> validate -> send -> archive
```

## Run traceability

Каждый запуск `get_fit.py` имеет `run_id`.

Он используется в:

- логах
- archive metadata
- Telegram archive naming

## Минимальный набор регрессионных тестов

- `tests/test_plan_validator.py`
- `tests/test_plan_processing.py`
- `tests/test_build_from_plan.py`
- `tests/test_orchestrator.py`
- `tests/test_archive_manager.py`
- `tests/test_compare_build_modes.py`
- `tests/test_direct_pipeline_e2e.py`
- `tests/test_telegram_bot_cancel.py`
- `tests/test_llm_prompt.py`
- `tests/test_llm_client.py`
- `tests/test_llm_benchmark.py`

Команда:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Package Status

- src/garmin_fit/ is the primary source tree
- garmin_fit/ contains local execution wrappers
- Scripts/ is a compatibility layer for legacy entry points

