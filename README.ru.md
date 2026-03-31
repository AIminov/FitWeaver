# Garmin FIT Workout Generator

> 🇬🇧 [English version](README.md)

Генерация тренировочных `.fit`-файлов для часов Garmin из текстовых планов с помощью локальной LLM.

---

## Pipeline

```
Текст плана  →  LLM  →  YAML  →  direct build  →  .fit  →  Garmin
```

Полный workflow не требует промежуточных Python-шаблонов.
Режимы `--templates-only` и `--build-only` сохранены как legacy/debug инструменты.

---

## Сценарии использования

### Сценарий 1 — Локальная LLM

Полностью локальный pipeline: план на естественном языке → LLM конвертирует в YAML → собираются FIT-файлы.

**Что потребуется:**
- [LM Studio](https://lmstudio.ai/) или [Ollama](https://ollama.com/) с загруженной моделью

**Шаги:**

**1.** Установите зависимости:
```bash
pip install -r requirements.txt
```

**2.** Напишите план в свободной форме и сохраните в `Plan/`:
```
Plan/my_plan.md
```

Пример содержимого:
```
10-недельный план бега. 3 тренировки в неделю.
Понедельник: лёгкий бег 40 мин, пульс 130–145
Среда: интервалы 6×800м, пульс 165–175, восстановление 2 мин
Суббота: длинный бег 60 мин, пульс 125–140
```

**4.** Запустите LLM-генерацию:

*LM Studio:*
```bash
python -m garmin_fit.llm.request_cli \
  --plan Plan/my_plan.md \
  --api openai \
  --url http://127.0.0.1:1234/v1 \
  --openai-mode completions \
  --timeout-sec 1800
```

*Ollama:*
```bash
python -m garmin_fit.llm.request_cli \
  --plan Plan/my_plan.md \
  --api ollama \
  --model llama3
```

> **Опционально:** Если в плане используются названия зон ("Z2", "лёгкий бег") вместо конкретных значений пульса,
> создайте `user_profile.yaml` чтобы LLM знала ваши личные зоны:
> ```bash
> cp user_profile.yaml.example user_profile.yaml
> ```

Если количество тренировок не определилось автоматически, скрипт спросит:
```
Could not auto-detect workout count from plan structure.
How many workouts does the plan contain? (Enter to skip): 30
```

Или укажите заранее:
```bash
python -m garmin_fit.llm.request_cli --plan Plan/my_plan.md --workouts 30 ...
```

**5.** Соберите FIT-файлы:
```bash
python -m garmin_fit.cli run
```

**6.** Подключите часы к компьютеру и скопируйте файлы из `Output_fit/`:

- Скопируйте `.fit`-файлы в папку **`/GARMIN/New files`** на часах
- Часы обработают файлы автоматически — они появятся в **`/GARMIN/Workouts`**

На часах:
выберите любой беговой режим → **Training → Workouts** → выберите нужную тренировку.

---

### Сценарий 2 — Готовый план от Claude / ChatGPT

Если у вас уже есть готовый YAML (сгенерированный Claude, ChatGPT или написанный вручную) — локальная LLM не нужна совсем.

**Шаги:**

**1.** Попросите Claude или ChatGPT сгенерировать YAML по шаблону:

Промпт:
```
Сгенерируй тренировочный план в формате YAML для проекта Garmin FIT Workout Generator.
Формат описан здесь: https://github.com/AIminov/FitWeaver/blob/main/docs/YAML_GUIDE.md
```

**2.** Сохраните полученный YAML в `Plan/`:
```
Plan/my_plan.yaml
```

**3.** Установите зависимости:
```bash
pip install -r requirements.txt
```

**4.** Опционально — провалидируйте план перед сборкой:
```bash
python -m garmin_fit.cli validate-yaml --plan Plan/my_plan.yaml
```

Валидатор проверит HR-диапазоны, форматы, уникальность имён и логику повторов.

**5.** Соберите FIT-файлы:
```bash
python -m garmin_fit.cli run
```

Или напрямую с указанием файла:
```bash
python get_fit.py --plan Plan/my_plan.yaml
```

**6.** Скопируйте файлы из `Output_fit/` на часы:

- Скопируйте `.fit`-файлы в папку **`/GARMIN/New files`** на часах
- Часы обработают файлы автоматически — они появятся в **`/GARMIN/Workouts`**

На часах:
выберите любой беговой режим → **Training → Workouts** → выберите нужную тренировку.

> **Совет:** Если YAML написан Claude или ChatGPT и не прошёл валидацию —
> покажи ошибки модели и попроси исправить. Обычно хватает одной итерации.

---

## Быстрый старт

**1.** Установите зависимости:
```bash
pip install -r requirements.txt
```

**2.** Положите план в папку:
```
Plan/plan.md   или   Plan/plan.txt
```

**4.** Сгенерируйте YAML через LLM (LM Studio):
```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --openai-mode completions
```

Если количество тренировок не определяется автоматически, укажите явно:
```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --workouts 48
```

Или можно написать YAML вручную по образцу из `docs/YAML_GUIDE.md`.

**5.** Соберите FIT-файлы:
```bash
python -m garmin_fit.cli run
```

**6.** Скопируйте на часы:

Файлы появятся в `Output_fit/`.

- Скопируйте `.fit`-файлы в папку **`/GARMIN/New files`** на часах
- Часы обработают их автоматически — тренировки появятся в **`/GARMIN/Workouts`**

Также доступен скрипт-обёртка:
```bash
run_pipeline.bat   # Windows
./run_pipeline.sh  # Linux / macOS
```

---

## Команды

### Основной CLI

```bash
python -m garmin_fit.cli run                          # Полный цикл
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml
python -m garmin_fit.cli validate-fit
python -m garmin_fit.cli doctor
python -m garmin_fit.cli doctor --llm --api openai --url http://127.0.0.1:1234/v1
python -m garmin_fit.cli archive
python -m garmin_fit.cli list-archives
python -m garmin_fit.cli restore <name>
```

### LLM-генерация

```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1
python -m garmin_fit.llm.request_cli --api ollama
python -m garmin_fit.llm.request_cli --workouts 48   # Явное число тренировок
```

### Legacy / Debug CLI

```bash
python -m garmin_fit.legacy_cli templates --plan Plan/plan.yaml
python -m garmin_fit.legacy_cli build
python -m garmin_fit.legacy_cli compare --plan Plan/plan.yaml
```

### Прочее

```bash
python run.py                        # Интерактивное меню
python -m garmin_fit.bot             # Telegram-бот
python validate_yaml.py              # Быстрая валидация
```

---

## Структура проекта

```
src/garmin_fit/      ← Основной исходный код
garmin_fit/          ← Alias-слой
Scripts/             ← Shims для обратной совместимости
Plan/                ← Сюда кладётся план
Output_fit/          ← Готовые FIT-файлы
Build_artifacts/     ← Отремонтированный YAML и отчёты
Archive/             ← Архивы предыдущих сборок
docs/                ← Документация
tests/               ← Тесты
sdk/py/              ← Vendored Garmin FIT Python SDK
examples/            ← Примеры шагов тренировки
```

---

## LLM — поддерживаемые бэкенды

| Бэкенд | Команда |
|--------|---------|
| LM Studio (OpenAI-совместимый) | `--api openai --url http://127.0.0.1:1234/v1` |
| Ollama | `--api ollama --url http://localhost:11434` |

Детали подключения: [`docs/LLM_CONNECTION_PROFILE.md`](docs/LLM_CONNECTION_PROFILE.md)

---

## Telegram-бот

Бот принимает текст плана, вызывает LLM и возвращает архив ZIP с FIT-файлами.

Настройка: [`docs/TELEGRAM_SETUP.md`](docs/TELEGRAM_SETUP.md)

```bash
cp bot_config.yaml.example bot_config.yaml
# Добавьте токен бота
python -m garmin_fit.bot
```

---

## Артефакты сборки

`Build_artifacts/` хранит:

- `*.repaired.yaml` — план после авто-исправлений
- `*.build_report.json` — machine-readable отчёт сборки
- `*.build_mode_compare.json` — сравнение direct и legacy сборщиков

---

## Документация

- [YAML Guide](docs/YAML_GUIDE.md)
- [Project Flow](docs/PROJECT_FLOW.md)
- [LLM Connection Profile](docs/LLM_CONNECTION_PROFILE.md)
- [Telegram Setup](docs/TELEGRAM_SETUP.md)
- [Changelog](docs/CHANGELOG.md)

---

## Тесты

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
