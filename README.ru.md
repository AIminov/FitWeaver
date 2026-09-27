# FitWeaver — Генератор тренировок Garmin

> 🇬🇧 [English version](README.md)

Генерация структурированных тренировок Garmin из текстовых планов с помощью локальной LLM.
Доставка на часы через USB или напрямую в **Garmin Connect Calendar** — без кабеля.

---

## Десктопный GUI

`fitweaver_gui.py` — Tkinter-приложение, которое охватывает весь pipeline без командной строки.

Современная визуальная оболочка использует дополнительный пакет
`customtkinter`, но сохраняет fallback на обычный Tkinter для исходников.
Установка:

```bash
pip install -e ".[gui]"
```

```bash
python fitweaver_gui.py
```

**Что внутри:**

| Вкладка | Возможности |
|---------|-------------|
| **План** | Календарь локального YAML; выберите тренировку и нажмите «Изменить тренировку», чтобы открыть её в конструкторе. «Сохранить в YAML» сразу обновляет выбранный файл; дату также можно менять перетаскиванием |
| **LLM** | Подключить модель, вставить текст плана и сохранить сгенерированный YAML в локальный план |
| **Конструктор** | Создать тренировку из блоков и шаблонов; сохранить отдельный YAML, добавить в открытый план или отправить напрямую в Garmin |
| **Garmin Connect** | Календарь фактических назначений и библиотека тренировок; просмотр и удаление тренировок |

Выбор Garmin-профиля находится слева; пароль, HR-настройка и выход из аккаунта скрыты
в «Настройках профиля», расширенные сервисные команды доступны в экспертном режиме.
Итог последней операции показан внизу окна;
подробный журнал можно раскрыть и открыть как файл. GUI всегда выполняет выбранное действие
в Garmin Connect после явного подтверждения. Параметр `--dry-run` остаётся только в CLI.
Состояние сессии (email, путь к YAML, настройки LLM) сохраняется между запусками.

В GUI есть **Простой** и **Экспертный** режимы. В упакованной версии Windows `FitWeaver.exe`
работает самостоятельно; `garmin-fit-cli.exe` — необязательный консольный компаньон.

---

## Pipeline

```
Размеченный текст        →  парсер (без LLM) ───────┐
Типовая запись тренировки →  правила (без LLM) ─────┼→  YAML  →  сборка  ─┬─  .fit  →  USB  →  Часы
Свободный текст          →  LLM (по тренировке) ───┘                     └─  Garmin Connect Calendar
```

### Как подать план

1. **Размеченный формат** — надёжнее всего: разбирается мгновенно, повторы и индексы считает
   код. Формат: [docs/MARKED_PLAN_FORMAT.md](docs/MARKED_PLAN_FORMAT.md), пример —
   `examples/marked_plan_example.txt`.
2. **Обычная запись с датами** — тренировки вида
   `14.04 вт: р2(5.45-6.00) + 6х800 4.20-4.30 отд 400 + з1` или
   `Разминка: 2 км (5:45-6:00)` / `6x800м по 4:20-4:30, восстановление 400 м` разбираются
   правилами без LLM. Правила берут тренировку, только если понятна каждая строка и каждое число;
   остальные уходят в LLM.
3. **Свободный текст** — через LLM, по одной тренировке за запрос. Результат можно посмотреть
   как размеченный текст («Показать как текст»), поправить и собрать заново — уже без LLM.

Пульс «до 140» / «не выше 140» записывается как диапазон 60–140: часы предупредят о превышении.

---

## Варианты доставки

| Метод | Как | Для чего |
|-------|-----|----------|
| **USB** | Копировать `.fit` в `/GARMIN/NewFiles` | Отдельные тренировки, оффлайн |
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
pip install -e ".[garmin-calendar]"
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
  --openai-mode auto \
  --timeout-sec 1800
```

*Ollama:*
```bash
python -m garmin_fit.llm.request_cli \
  --plan Plan/my_plan.md \
  --api ollama \
  --model qwen3:8b
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

- Скопируйте `.fit`-файлы в папку **`/GARMIN/NewFiles`** на часах
- Часы обработают файлы автоматически — они появятся в **`/GARMIN/Workouts`**

На часах:
выберите любой беговой режим → **Training → Workouts** → выберите нужную тренировку.

---

### Сценарий 2 — План от Claude / ChatGPT

Локальная LLM не нужна: внешнюю модель удобнее просить не о YAML, а о **размеченном тексте**
— его приложение разбирает само, мгновенно и без ошибок в повторах, а человеку его легко
проверить.

**Шаги:**

**1.** Попросите Claude или ChatGPT переписать план в размеченный формат:

Промпт:
```
Перепиши мой план тренировок в размеченный формат FitWeaver. Правила формата:
https://github.com/AIminov/FitWeaver/blob/main/docs/MARKED_PLAN_FORMAT.md
Каждая тренировка начинается с «==== ТРЕНИРОВКА ==== ДД.ММ.ГГГГ (день) — Название»,
каждый шаг — с «**** ШАГ ****», повторы — «**** ПОВТОР: N РАЗ **** … **** КОНЕЦ ПОВТОРА ****».
Не додумывай значения, которых нет в плане. Вот план: …
```

Вставьте ответ во вкладку LLM и нажмите «Генерировать YAML» — план разберётся без LLM. Или
сохраните текст в файл и соберите YAML командой:
```bash
python -m garmin_fit.cli parse-marked plan.txt --output Plan/my_plan.yaml
```

Можно попросить и готовый YAML по [YAML_GUIDE](https://github.com/AIminov/FitWeaver/blob/main/docs/YAML_GUIDE.md) —
тогда индексы повторов (`back_to_offset`) придётся проверять внимательнее.

**2.** Если получили YAML — сохраните его в `Plan/`:
```
Plan/my_plan.yaml
```

**3.** Установите зависимости:
```bash
pip install -e ".[garmin-calendar]"
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

- Скопируйте `.fit`-файлы в папку **`/GARMIN/NewFiles`** на часах
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
pip install -e ".[garmin-calendar]"
```

**2.** Запустите десктопный GUI:
```bash
python fitweaver_gui.py
```

**3.** Используйте GUI как основной рабочий сценарий:
- вставьте или откройте план во вкладке **LLM Генератор**
- сгенерируйте и проверьте YAML
- соберите FIT-файлы или загрузите план в Garmin Connect из GUI

Для CLI-автоматизации используйте пакетные команды ниже.

**Папка для CLI:** если вы не используете GUI, положите план в:
```
Plan/plan.md   или   Plan/plan.txt
```

**3.** Сгенерируйте YAML через LLM (LM Studio):
```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --openai-mode auto
```

Если количество тренировок не определяется автоматически, укажите явно:
```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --workouts 48
```

Или можно написать план в [размеченном формате](docs/MARKED_PLAN_FORMAT.md) и собрать YAML без LLM:
```bash
python -m garmin_fit.cli parse-marked plan.txt --output Plan/plan.yaml
```
Либо написать YAML вручную по образцу из `docs/YAML_GUIDE.md`.

**4.** Соберите FIT-файлы:
```bash
python -m garmin_fit.cli run
```

**5.** Скопируйте на часы:

Файлы появятся в `Output_fit/`.

- Скопируйте `.fit`-файлы в папку **`/GARMIN/NewFiles`** на часах
- Часы обработают их автоматически — тренировки появятся в **`/GARMIN/Workouts`**

---

## Команды

### Десктопный GUI

```bash
python fitweaver_gui.py              # Основной локальный сценарий
```

### Основной CLI

```bash
python -m garmin_fit.cli run                          # Полный цикл
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml
python -m garmin_fit.cli parse-marked plan.txt --output Plan/plan.yaml  # размеченный текст → YAML без LLM
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


### Прочее

```bash
python -m garmin_fit.runner          # Интерактивное меню (14 опций, терминал)
python -m garmin_fit.bot             # Telegram-бот
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml  # Быстрая валидация
```

---

## Структура проекта

```
src/garmin_fit/      ← Основной код для GUI и пакетных CLI
garmin_fit/          ← Локальный bridge для запуска из checkout
Scripts/             ← Legacy-shims для совместимости, не обычная точка входа
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

Работает любой OpenAI-совместимый сервер. Выставите **Тип = openai** и укажите адрес сервера — `/v1` добавляется автоматически.

| Бэкенд | Как запустить | URL в GUI / CLI |
|--------|--------------|----------------|
| **LM Studio** | Загрузить модель → Start server | `http://127.0.0.1:1234` |
| **llama.cpp** (`llama-server`) | См. ниже | `http://127.0.0.1:8080` |
| **Ollama** | `ollama serve` | `http://127.0.0.1:11434` (Тип = ollama) |
| **vLLM / любой OpenAI-compat** | Зависит от утилиты | `http://HOST:PORT` |

### Запуск через llama-server (llama.cpp)

```powershell
# Скачать и запустить модель напрямую с Hugging Face
llama-server -hf ggml-org/gemma-4-12B-it-GGUF:Q4_K_M `
  --host 127.0.0.1 `
  --port 8080 `
  -c 32768 `
  -np 1
```

Затем в GUI (вкладка **🤖 LLM Генератор**) или CLI:

| Поле | Значение |
|------|----------|
| URL | `http://127.0.0.1:8080` |
| Модель | Запустите `curl http://127.0.0.1:8080/v1/models` чтобы узнать точный ID, или используйте HF-путь |
| Тип | `openai` |

Эквивалент в CLI:
```bash
python -m garmin_fit.llm.request_cli \
  --api openai \
  --url http://127.0.0.1:8080 \
  --plan Plan/my_plan.md
```

### Рекомендации по моделям

| Модель | Заметки |
|--------|---------|
| `qwen3:8b` / Unsloth Qwen3 8B IQ4_XS | ✅ Цель проекта — ноутбук без GPU. На golden-наборе 6/10 и 8/10 строгих прохождений; ~45–200 с на тренировку |
| `qwen3.8-27b` | ✅ Точнее, но нужна мощная машина — используйте точный ID из `/v1/models` |
| `google/gemma-4-*` | ⚠️ **Избегать** — игнорирует `enable_thinking: false`; при повторной попытке входит в режим размышлений и зависает на 3000+ секунд |

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
- [Размеченный формат плана](docs/MARKED_PLAN_FORMAT.md) — ввод без LLM
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
