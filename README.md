# Garmin FIT Workout Generator

Генерация тренировочных `.fit`-файлов для часов Garmin из текстовых планов с помощью локальной LLM.

Generate Garmin `.fit` workout files from plain-text training plans using a local LLM.

---

## Pipeline

```
Текст плана / Plan text  →  LLM  →  YAML  →  direct build  →  .fit  →  Garmin
```

Полный workflow не требует промежуточных Python-шаблонов.
Режимы `--templates-only` и `--build-only` сохранены как legacy/debug инструменты.

The full workflow requires no intermediate Python templates.
`--templates-only` and `--build-only` modes are retained as legacy/debug tools.

---

## Быстрый старт / Quick Start

**1. Установка зависимостей / Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Настройте профиль / Configure your profile**

```bash
cp user_profile.yaml.example user_profile.yaml
# Отредактируйте значения пульсовых зон / Edit your HR zone values
```

**3. Положите план в папку / Place your plan in**

```
Plan/plan.md   или / or   Plan/plan.txt
```

**4. Сгенерируйте YAML через LLM / Generate YAML via LLM** (LM Studio)

```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --openai-mode completions
```

Если количество тренировок не определяется автоматически, укажите явно /
If workout count is not auto-detected, specify explicitly:

```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --workouts 48
```

Или можно написать YAML вручную по образцу из `docs/YAML_GUIDE.md`.
Or write the YAML manually using `docs/YAML_GUIDE.md` as a reference.

**5. Соберите FIT-файлы / Build FIT files**

```bash
python -m garmin_fit.cli run
```

**6. Скопируйте на часы / Copy to your Garmin watch**

Файлы появятся в `Output_fit/`.
Files will appear in `Output_fit/`.

Также доступен скрипт-обёртка / A wrapper script is also available:

```bash
run_pipeline.bat   # Windows
./run_pipeline.sh  # Linux / macOS
```

---

## Команды / Commands

### Основной CLI / Primary CLI

```bash
python -m garmin_fit.cli run                          # Полный цикл / Full workflow
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml
python -m garmin_fit.cli validate-fit
python -m garmin_fit.cli doctor
python -m garmin_fit.cli doctor --llm --api openai --url http://127.0.0.1:1234/v1
python -m garmin_fit.cli archive
python -m garmin_fit.cli list-archives
python -m garmin_fit.cli restore <name>
```

### LLM-генерация / LLM generation

```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1
python -m garmin_fit.llm.request_cli --api ollama
python -m garmin_fit.llm.request_cli --workouts 48   # Явное число тренировок / Explicit count
```

### Legacy / Debug CLI

```bash
python -m garmin_fit.legacy_cli templates --plan Plan/plan.yaml
python -m garmin_fit.legacy_cli build
python -m garmin_fit.legacy_cli compare --plan Plan/plan.yaml
```

### Прочее / Other

```bash
python run.py                        # Интерактивное меню / Interactive menu
python -m garmin_fit.bot             # Telegram-бот / Telegram bot
python validate_yaml.py              # Быстрая валидация / Quick validation
```

---

## Структура проекта / Project Structure

```
src/garmin_fit/      ← Основной исходный код / Canonical source
garmin_fit/          ← Alias-слой / Alias layer
Scripts/             ← Shims для обратной совместимости / Compatibility shims
Plan/                ← Сюда кладётся план / Place your plan here
Output_fit/          ← Готовые FIT-файлы / Generated FIT files
Build_artifacts/     ← Отремонтированный YAML и отчёты / Repaired YAML + reports
Archive/             ← Архивы предыдущих сборок / Previous build archives
docs/                ← Документация / Documentation
tests/               ← Тесты / Tests
sdk/py/              ← Vendored Garmin FIT Python SDK
examples/            ← Примеры шагов тренировки / Workout step examples
```

---

## LLM — поддерживаемые бэкенды / Supported backends

| Backend | Команда / Command |
|---------|-------------------|
| LM Studio (OpenAI-совместимый) | `--api openai --url http://127.0.0.1:1234/v1` |
| Ollama | `--api ollama --url http://localhost:11434` |

Детали подключения / Connection details: [`docs/LLM_CONNECTION_PROFILE.md`](docs/LLM_CONNECTION_PROFILE.md)

---

## Telegram-бот / Telegram Bot

Бот принимает текст плана, вызывает LLM и возвращает архив ZIP с FIT-файлами.
The bot accepts plan text, calls the LLM, and returns a ZIP archive with FIT files.

Настройка / Setup: [`docs/TELEGRAM_SETUP.md`](docs/TELEGRAM_SETUP.md)

```bash
cp bot_config.yaml.example bot_config.yaml
# Добавьте токен бота / Add your bot token
python -m garmin_fit.bot
```

---

## Артефакты сборки / Build Artifacts

`Build_artifacts/` хранит:
`Build_artifacts/` contains:

- `*.repaired.yaml` — план после авто-исправлений / plan after auto-repair
- `*.build_report.json` — machine-readable отчёт сборки / machine-readable build report
- `*.build_mode_compare.json` — сравнение direct и legacy сборщиков / comparison of direct vs legacy builders

---

## Документация / Documentation

- [Полная документация / Full docs](docs/README.md)
- [YAML Guide](docs/YAML_GUIDE.md)
- [Project Flow](docs/PROJECT_FLOW.md)
- [LLM Connection Profile](docs/LLM_CONNECTION_PROFILE.md)
- [Telegram Setup](docs/TELEGRAM_SETUP.md)
- [Changelog](docs/CHANGELOG.md)

---

## Тесты / Tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
