# Garmin FIT Workout Generator

Система преобразует текстовые планы тренировок в YAML и затем напрямую собирает FIT-файлы для Garmin.

## Актуальный pipeline

```text
Текстовый план (.txt/.md)
        |
        v
  [1] LLM -> YAML (Plan/*.yaml)
        |
        v
  [2] Direct build -> FIT (Output_fit/*.fit)
        |
        v
  [3] Validation -> archive
```

### Что изменилось

- Полный workflow `python get_fit.py` больше не зависит от `Workout_templates/*.py`.
- Python templates остались как optional debug/export слой:
  - `python get_fit.py --templates-only`
  - `python get_fit.py --build-only`
- Появился diagnostics-режим:
  - `python get_fit.py --compare-build-modes`
- Архивы и Telegram ZIP могут включать templates даже если в workspace их нет:
  система экспортирует их из YAML на лету.

## Основные сценарии

### 1. Полный workflow

```bash
python get_fit.py
```

Что делает:

1. Берет активный YAML-план из `Plan/`
2. Строит FIT напрямую из YAML/domain objects
3. Пишет build artifacts в `Build_artifacts/`
4. Валидирует `Output_fit/*.fit`
5. Архивирует план и артефакты при успехе

### 2. Генерация YAML через LLM

```bash
python -m Scripts.llm.request_cli
```

По умолчанию читает `Plan/plan.txt` или `Plan/plan.md` и пишет `Plan/plan.yaml`.

Рекомендованный профиль для LM Studio:

```bash
python -m Scripts.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --model qwen/qwen3.5-9b --openai-mode completions --timeout-sec 1800 --retries 3
```

Если план фазовый или свободной структуры — укажи число тренировок явно:

```bash
python -m Scripts.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --workouts 48
```

Если `--workouts` не передан и авто-детекция не сработала, скрипт спросит интерактивно.

Детали параметров: [LLM Connection Profile](LLM_CONNECTION_PROFILE.md)

### 3. Optional debug export templates

```bash
python get_fit.py --templates-only
```

Используйте только если нужны Python templates для отладки, сравнения или legacy совместимости.

### 4. Legacy build from templates

```bash
python get_fit.py --build-only
```

Этот режим читает `Workout_templates/*.py` и собирает FIT по старому пути.

### 5. Проверка FIT

```bash
python get_fit.py --validate-only
python get_fit.py --validate-mode strict
python Scripts/check_fit.py --strict Output_fit
python Scripts/check_fit.py --strict --no-sdk-python-check Output_fit
```

### 5b. Doctor (environment + optional LLM smoke check)

```bash
python get_fit.py --doctor
python get_fit.py --doctor --llm --api openai --url http://127.0.0.1:1234/v1 --model qwen/qwen3.5-9b --openai-mode completions --timeout-sec 120
```

### 6. Compare direct vs legacy build

```bash
python get_fit.py --compare-build-modes
```

Этот diagnostics-режим прогоняет один YAML по direct и legacy templates path,
сравнивает count/files/decoded FIT steps и пишет `*.build_mode_compare.json`
в `Build_artifacts/`.

### 7. LLM benchmark / regression

```bash
python -m Scripts.llm.benchmark --suite tests/fixtures/llm_benchmark/plan_week_2026_03_02.yaml --mode generate --api openai --url http://127.0.0.1:1234/v1 --model qwen/qwen3.5-9b --openai-mode completions --timeout-sec 1800
```

Отчет сохраняется в `Build_artifacts/*.llm_benchmark_report.json`.

## Архивы

```bash
python get_fit.py --archive
python get_fit.py --list-archives
python get_fit.py --restore <archive_name>
```

Архив содержит:

- **plan files** (.md + .yaml) — оба типа файлов
- **FIT files** — сгенерированные тренировки
- **build artifacts** (`*.repaired.yaml`, `*.build_report.json`, `*.build_mode_compare.json`) when available
- **templates** — если они были в workspace или могли быть экспортированы из YAML

В `archive_info.txt` теперь дополнительно фиксируется `Templates source`:

- `workspace`
- `exported_from_yaml`
- `none`

### Организация plan_done/

После успешного архивирования планы перемещаются в структурированную папку:

```
Plan/plan_done/
└── running_plan_2026_v2_20260315_124359/
    ├── running_plan_2026_v2.md      (исходный текст)
    └── running_plan_2026_v2.yaml    (сгенерированная конфигурация)
```

**Особенности:**
- Папка имеет то же имя, что и архив (с датой/временем)
- Содержит оба файла (.md и .yaml) для полноты истории
- Легко восстановить план для редактирования при необходимости
- `Plan/` остается чистой папкой, содержит только `plan_done/`

## Telegram-бот

```bash
python -m Scripts.telegram_bot
```

Бот:

1. принимает текст плана или `.txt/.md`
2. генерирует YAML через локальную LLM
3. показывает preview с auto-repair/warnings
4. после `/build` запускает direct pipeline `YAML -> FIT -> validate`
5. отправляет FIT файлами или ZIP bundle

Если FIT больше 10, бот отправляет ZIP с:

- `plan/`
- `artifacts/`
- `fit/`
- `templates/` if available or exported from YAML

## Ключевые каталоги

```text
Plan/                                    # исходные планы (остается чистой)
Plan/plan_done/
  └── {plan_name}_{YYYYmmdd_HHMMSS}/    # архивированные планы с датой/временем
      ├── *.md                          # исходный текст плана
      └── *.yaml                        # сгенерированная конфигурация
Output_fit/                              # итоговые FIT
Workout_templates/                       # optional debug/legacy templates
Build_artifacts/                         # repaired YAML and build reports
Archive/                                 # архивы запусков
  └── {plan_name}_{YYYYmmdd_HHMMSS}/    # полные архивы с артефактами
Logs/                                    # логи
Scripts/                                 # код проекта
tests/                                   # unit/regression tests
```

## Важные модули

```text
Scripts/orchestrator.py      # общий pipeline orchestration
Scripts/build_from_plan.py   # direct YAML/domain -> FIT builder
Scripts/plan_artifacts.py    # repaired YAML + build_report.json
Scripts/compare_build_modes.py # direct vs legacy compare tool
Scripts/generate_from_yaml.py# optional template export
Scripts/plan_domain.py       # domain objects and constants
Scripts/plan_processing.py   # normalization and auto-repair
Scripts/plan_validator.py    # schema + semantic validation
Scripts/plan_service.py      # shared app services for LLM/bot
Scripts/llm/prompt.py        # strict contract-first prompt builder
Scripts/llm/benchmark.py     # LLM quality benchmark runner
Scripts/telegram_bot.py      # thin Telegram adapter
Scripts/archive_manager.py   # archive/restore logic
```

## Тесты

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Смежные документы

- [YAML Guide](YAML_GUIDE.md)
- [LLM Validation System](LLM_VALIDATION_SYSTEM.md) — Три слоя валидации: контракт, примеры, runtime проверки
- [Project Flow](PROJECT_FLOW.md)
- [LLM Connection Profile](LLM_CONNECTION_PROFILE.md)
- [Telegram Setup](TELEGRAM_SETUP.md)
- [Changelog](CHANGELOG.md)
