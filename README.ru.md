# FitWeaver — Генератор тренировок Garmin

> 🇬🇧 [English version](README.md)

Генерация структурированных тренировок Garmin из текстовых планов с помощью локальной LLM.
Доставка на часы через USB или напрямую в **Garmin Connect Calendar** — без кабеля.

---

## Pipeline

```
Текст плана  →  LLM  →  YAML  →  direct build  ─┬─  .fit  →  USB  →  Часы
                                                 └─  Garmin Connect Calendar  →  Синхронизация
```

Полный workflow не требует промежуточных Python-шаблонов.
Режимы `--templates-only` и `--build-only` сохранены как legacy/debug инструменты.

---

## Варианты доставки

| Метод | Как | Для чего |
|-------|-----|----------|
| **USB** | Копировать `.fit` в `/GARMIN/New files` | Отдельные тренировки, оффлайн |
| **Garmin Calendar** | Команда `garmin-calendar` | Целые планы, автоматическое расписание |

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

**3.** Запустите LLM-генерацию:

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

**4.** Соберите FIT-файлы:
```bash
python -m garmin_fit.cli run
```

**5.** Подключите часы к компьютеру и скопируйте файлы из `Output_fit/`:

- Скопируйте `.fit`-файлы в папку **`/GARMIN/New files`** на часах
- Часы обработают файлы автоматически — они появятся в **`/GARMIN/Workouts`**

На часах:
выберите любой беговой режим → **Training → Workouts** → выберите нужную тренировку.

---

### Сценарий 2 — Готовый план от Claude / ChatGPT

Если у вас уже есть готовый YAML (сгенерированный Claude, ChatGPT или написанный вручную) — локальная LLM не нужна.

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

**3.** Опционально — провалидируйте план перед сборкой:
```bash
python -m garmin_fit.cli validate-yaml --plan Plan/my_plan.yaml
```

Валидатор проверит HR-диапазоны, форматы, уникальность имён и логику повторов.

**4.** Соберите FIT-файлы:
```bash
python -m garmin_fit.cli run
```

Или напрямую с указанием файла:
```bash
python -m garmin_fit.cli run --plan Plan/my_plan.yaml
```

**5.** Скопируйте файлы из `Output_fit/` на часы:

- Скопируйте `.fit`-файлы в папку **`/GARMIN/New files`** на часах
- Часы обработают файлы автоматически — они появятся в **`/GARMIN/Workouts`**

На часах:
выберите любой беговой режим → **Training → Workouts** → выберите нужную тренировку.

> **Совет:** Если YAML написан Claude или ChatGPT и не прошёл валидацию —
> покажи ошибки модели и попроси исправить. Обычно хватает одной итерации.

---

### Сценарий 3 — Garmin Connect Calendar (без USB)

Загрузить весь план напрямую в Garmin Connect. Тренировки появятся на часах после следующей синхронизации — без кабеля.

**Требования:**
- Аккаунт Garmin Connect
- Имена воркаутов в формате `W{неделя}_{ММ-ДД}_{...}` (напр. `W11_03-14_Sat_Long_14km`) — дата извлекается автоматически

**Загрузить весь план:**
```bash
python -m garmin_fit.cli garmin-calendar \
  --plan Plan/my_plan.yaml \
  --email your@email.com \
  --password yourpassword \
  --year 2026
```

**Проверить без обращений к API:**
```bash
python -m garmin_fit.cli garmin-calendar --plan Plan/my_plan.yaml --dry-run
```

**Загрузить конкретный период:**
```bash
python -m garmin_fit.cli garmin-calendar \
  --plan Plan/my_plan.yaml \
  --email your@email.com \
  --password yourpassword \
  --year 2026 \
  --from-date 2026-06-01 \
  --to-date 2026-06-30
```

**Удалить загруженные тренировки за диапазон дат:**
```bash
python -m garmin_fit.cli garmin-calendar-delete \
  --email your@email.com \
  --password yourpassword \
  --year 2026 \
  --from-date 2026-06-01 \
  --to-date 2026-06-30 \
  --dry-run

python -m garmin_fit.cli garmin-calendar-delete \
  --email your@email.com \
  --password yourpassword \
  --year 2026 \
  --from-date 2026-06-01 \
  --to-date 2026-06-30 \
  --confirm
```

**Все параметры:**

| Флаг | По умолчанию | Описание |
|------|-------------|----------|
| `--plan` | авто | Путь к YAML-плану |
| `--email` | env `GARMIN_EMAIL` | Email Garmin Connect |
| `--password` | env `GARMIN_PASSWORD` | Пароль Garmin Connect |
| `--token-dir` | `~/.garminconnect` | Папка для хранения токенов |
| `--year` | текущий/следующий | Переопределить год |
| `--dry-run` | выкл | Собрать данные без вызовов API |
| `--no-schedule` | выкл | Загрузить без постановки в календарь |
| `--skip-past` | выкл | Пропустить тренировки с датой до сегодня |
| `--from-date` | нет | Загружать только с этой даты (YYYY-MM-DD) |
| `--to-date` | нет | Загружать только до этой даты (YYYY-MM-DD) |
| `--week-pause` | 3.0 с | Пауза между неделями (защита от rate limit) |

Токены кешируются после первого входа — повторные запуски авторизацию пропускают.

> **СБУ-блоки:** каждое упражнение получает свою группу повторений с именем дрила в примечании к шагу — на часах и в Garmin Connect отображается название упражнения (напр. "Высок.Бедро", "Захлёст").

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

**3.** Сгенерируйте YAML через LLM (LM Studio):
```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --openai-mode completions
```

Если количество тренировок не определяется автоматически, укажите явно:
```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --workouts 48
```

Или можно написать YAML вручную по образцу из `docs/YAML_GUIDE.md`.

**4.** Соберите FIT-файлы:
```bash
python -m garmin_fit.cli run
```

**5.** Скопируйте на часы:

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

### Garmin Calendar Upload

См. [Сценарий 3](#сценарий-3--garmin-connect-calendar-без-usb) для полного описания и всех флагов.

```bash
python -m garmin_fit.cli garmin-calendar --plan Plan/plan.yaml --dry-run
python -m garmin_fit.cli garmin-calendar --plan Plan/plan.yaml --year 2026
python -m garmin_fit.cli garmin-calendar --plan Plan/plan.yaml --from-date 2026-06-01 --to-date 2026-06-30
python -m garmin_fit.cli garmin-calendar --plan Plan/plan.yaml --skip-past --year 2026
```

### Garmin Calendar Delete

```bash
python -m garmin_fit.cli garmin-calendar-delete --email you@example.com --password yourpassword --year 2026 --from-date 2026-06-01 --to-date 2026-06-30 --dry-run
python -m garmin_fit.cli garmin-calendar-delete --email you@example.com --password yourpassword --year 2026 --from-date 2026-06-01 --to-date 2026-06-30 --confirm
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
python -m garmin_fit.runner          # Интерактивное меню (рекомендуется для локальной LLM)
python -m garmin_fit.bot             # Telegram-бот
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml  # Быстрая валидация
```

Интерактивное меню (`garmin_fit.runner`) охватывает полный локальный workflow в одном месте:
LLM-генерация → сборка → валидация → загрузка/удаление в Garmin Calendar → архив.

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

Бот принимает текст плана, вызывает LLM, показывает YAML-preview, собирает FIT-файлы
и предлагает выбрать ZIP-доставку или прямую загрузку в Garmin Calendar.

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
- [Garmin Payload Spec](docs/GARMIN_PAYLOAD_SPEC.md) — проверенные имена полей API (ID, targetValueOne/Two, description)
- [Garmin Calendar](docs/GARMIN_CALENDAR.md) — настройка и детали облачной загрузки
- [Project Flow](docs/PROJECT_FLOW.md)
- [LLM Connection Profile](docs/LLM_CONNECTION_PROFILE.md)
- [Telegram Setup](docs/TELEGRAM_SETUP.md)
- [Changelog](docs/CHANGELOG.md)

---

## Тесты

```bash
python -m pytest tests/
```
