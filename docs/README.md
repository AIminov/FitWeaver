# Garmin FIT Workout Generator

Canonical repository: `https://github.com/AIminov/FitWeaver`

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

- Полный workflow `python -m garmin_fit.cli run` строит FIT напрямую из YAML.
- Legacy-сборщик через Python templates удалён 2026-09-26: FIT строится только напрямую
  из YAML (`build_from_plan.py`).

## Основные сценарии

### 1. Полный workflow

```bash
python -m garmin_fit.cli run
```

Что делает:

1. Берет активный YAML-план из `Plan/`
2. Строит FIT напрямую из YAML/domain objects
3. Пишет build artifacts в `Build_artifacts/`
4. Валидирует `Output_fit/*.fit`
5. Архивирует план и артефакты при успехе

### 2. Генерация YAML через LLM

```bash
python -m garmin_fit.llm.request_cli
```

По умолчанию читает `Plan/plan.txt` или `Plan/plan.md` и пишет `Plan/plan.yaml`.

Рекомендованный профиль для LM Studio:

```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --model qwen3.8-27b@iq3_xxs --openai-mode auto --timeout-sec 1800
```

Если план фазовый или свободной структуры — укажи число тренировок явно:

```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --workouts 48
```

Если `--workouts` не передан и авто-детекция не сработала, скрипт спросит интерактивно.

Детали параметров: [LLM Connection Profile](LLM_CONNECTION_PROFILE.md)

### 5. Проверка FIT

```bash
python -m garmin_fit.cli validate-fit
python -m garmin_fit.cli validate-fit --validate-mode strict
python -m garmin_fit.check_fit --strict Output_fit
python -m garmin_fit.check_fit --strict --no-sdk-python-check Output_fit
```

### 5b. Doctor (environment + optional LLM smoke check)

```bash
python -m garmin_fit.cli doctor
python -m garmin_fit.cli doctor --llm --api openai --url http://127.0.0.1:1234/v1 --model qwen3.8-27b@iq3_xxs --openai-mode auto --timeout-sec 120
```

### 7. LLM benchmark / regression

```bash
python -m garmin_fit.llm.benchmark --suite tests/fixtures/llm_benchmark/plan_week_2026_03_02.yaml --mode generate --api openai --url http://127.0.0.1:1234/v1 --model qwen3.8-27b@iq3_xxs --openai-mode auto --timeout-sec 1800
```

Отчет сохраняется в `Build_artifacts/*.llm_benchmark_report.json`.

## Архивы

```bash
python -m garmin_fit.cli archive
python -m garmin_fit.cli list-archives
python -m garmin_fit.cli restore <archive_name>
```

Архив содержит:

- **plan files** (.md + .yaml) — оба типа файлов
- **FIT files** — сгенерированные тренировки
- **build artifacts** (`*.repaired.yaml`, `*.build_report.json`) when available

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
python -m garmin_fit.bot
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

## Ключевые каталоги

```text
Plan/                                    # исходные планы (остается чистой)
Plan/plan_done/
  └── {plan_name}_{YYYYmmdd_HHMMSS}/    # архивированные планы с датой/временем
      ├── *.md                          # исходный текст плана
      └── *.yaml                        # сгенерированная конфигурация
Output_fit/                              # итоговые FIT
Build_artifacts/                         # repaired YAML and build reports
Archive/                                 # архивы запусков
  └── {plan_name}_{YYYYmmdd_HHMMSS}/    # полные архивы с артефактами
Logs/                                    # логи
src/garmin_fit/                         # основной source tree
tests/                                   # unit/regression tests
```

## Важные модули

```text
src/garmin_fit/orchestrator.py      # общий pipeline orchestration
src/garmin_fit/build_from_plan.py   # direct YAML/domain -> FIT builder
src/garmin_fit/plan_artifacts.py    # repaired YAML + build_report.json
src/garmin_fit/plan_domain.py       # domain objects and constants
src/garmin_fit/plan_processing.py   # normalization and auto-repair
src/garmin_fit/plan_validator.py    # schema + semantic validation
src/garmin_fit/plan_service.py      # shared app services for LLM/bot
src/garmin_fit/llm/prompt.py        # strict contract-first prompt builder
src/garmin_fit/llm/benchmark.py     # LLM quality benchmark runner
src/garmin_fit/telegram_bot.py      # thin Telegram adapter
src/garmin_fit/archive_manager.py   # archive/restore logic
```

## Тесты

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Смежные документы

- [YAML Guide](YAML_GUIDE.md)
- [Как записать беговой план](PLAN_WRITING_GUIDE.md) — как писать план, чтобы он разбирался без LLM
- [Размеченный формат плана](MARKED_PLAN_FORMAT.md) — детерминированный разбор без LLM
- [LLM Validation System](LLM_VALIDATION_SYSTEM.md) — Три слоя валидации: контракт, примеры, runtime проверки
- [Project Flow](PROJECT_FLOW.md)
- [LLM Connection Profile](LLM_CONNECTION_PROFILE.md)
- [Telegram Setup](TELEGRAM_SETUP.md)
- [Changelog](CHANGELOG.md)
- [История TODO и журнала сессий](history/) — архив до 2026-09-26
