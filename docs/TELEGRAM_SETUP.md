# Telegram Bot Setup — FitWeaver

Telegram-бот принимает текстовый план тренировок, генерирует YAML через локальную LLM (LM Studio или Ollama), показывает preview, собирает FIT-файлы и предлагает два варианта доставки: ZIP-архив или прямую загрузку в Garmin Connect Calendar.

## Быстрый старт

### 1. Установите зависимости

```powershell
pip install -r requirements.txt
```

### 2. Настройте LLM-сервер

**Вариант A: LM Studio (рекомендуется)**

1. Скачайте [LM Studio](https://lmstudio.ai/)
2. Загрузите модель (например, `gemma-4-e4b` или `qwen2.5-9b-instruct`)
3. Запустите Local Server на порту 1234

**Вариант B: Ollama**

```powershell
ollama pull gemma2:2b
ollama serve
```

### 3. Создайте `bot_config.yaml`

**LM Studio:**

```yaml
telegram_bot_token: "YOUR_BOT_TOKEN"

llm_model: "gemma-4-e4b"
llm_url: "http://127.0.0.1:1234"
llm_api_type: "openai"

allowed_user_ids: []
```

**Ollama:**

```yaml
telegram_bot_token: "YOUR_BOT_TOKEN"

llm_model: "gemma2:2b"
llm_url: "http://localhost:11434"
llm_api_type: "ollama"

allowed_user_ids: []
```

| Параметр | Описание |
|----------|----------|
| `telegram_bot_token` | Токен от @BotFather |
| `llm_model` | Название модели |
| `llm_url` | URL LLM-сервера |
| `llm_api_type` | `"openai"` для LM Studio, `"ollama"` для Ollama |
| `allowed_user_ids` | Whitelist Telegram user ID (пустой = все) |

### 4. Запустите бота

```powershell
python -m garmin_fit.bot
```

При старте бот проверяет наличие `bot_config.yaml` и доступ на запись в директории `Plan/`, `Output_fit/`, `Archive/`, `Build_artifacts/`.

---

## Команды

### Основные

| Команда | Описание |
|---------|----------|
| `/start` | Выбор языка (🇷🇺 / 🇬🇧) + приветствие с примерами тренировок |
| `/help` | Список команд |
| `/howto` | Инструкция по загрузке тренировок на часы |
| `/status` | Текущее состояние (status, yaml_ready, fit_files, queue) |
| `/cancel` | Отмена текущей операции / сброс состояния |
| `/build` | Запуск сборки FIT после подтверждения YAML |

### Garmin Calendar (без USB)

| Команда | Описание |
|---------|----------|
| `/connect_garmin` | Войти в Garmin Connect (бот спросит email, затем пароль) |
| `/connect_garmin email password` | Войти одной командой |
| `/send_to_garmin` | Загрузить последний собранный план в Garmin Calendar |
| `/send_to_garmin 2026` | То же с явным указанием года |
| `/delete_workout` | Удалить последнюю загруженную группу тренировок |
| `/delete_workout list` | Список всех тренировок в Garmin Connect |
| `/delete_workout all` | Удалить ВСЕ тренировки из аккаунта |
| `/disconnect_garmin` | Выйти из Garmin Connect, удалить токены |

**Типичный Garmin-flow:**
1. `/connect_garmin` → бот спрашивает email, затем пароль (или MFA-код при 2FA)
2. Отправьте план → дождитесь `/build`
3. В диалоге доставки выберите **📅 Upload to Garmin Calendar**
4. Синхронизируйте часы → тренировки на часах

Токены кешируются в `~/.garminconnect/tg_{user_id}/` — повторные входы не требуют пароля.

---

## Полный диалоговый flow

```
/start
  └─→ [🇷🇺 Русский] / [🇬🇧 English]
        └─→ приветствие + 5 примеров тренировок (каждый отдельным сообщением)

Пользователь отправляет текст / .txt / .md
  ├─→ проверка cooldown (30 сек) и длины (макс 4000 симв.)
  ├─→ «Проверяю LLM...» → «Генерирую YAML...»
  ├─→ [если найден sbu_block без drills]
  │     └─→ вопрос: «стандарт» или свои упражнения
  ├─→ [если есть ambiguities и clarification ещё не проводился]
  │     └─→ уточняющий вопрос; ответ → перегенерация YAML (один раунд)
  │           или /build → продолжить как есть
  └─→ YAML preview + «Отправьте /build»

/build
  └─→ YAML → FIT build → validate → archive
        └─→ «✅ Сборка завершена! FIT-файлов: N»
              └─→ [📁 Отправить FIT-файлы (ZIP)] / [📅 Загрузить в Garmin Calendar]
                    ├─→ 📁 → ZIP в чат
                    └─→ 📅 → загрузка в Garmin Connect Calendar
                               (если не подключён → инструкция /connect_garmin)
```

**Файлы:**
- `.txt` / `.md` — текст плана → LLM генерирует YAML
- `.yaml` / `.yml` — готовый YAML-план → LLM пропускается, сразу `/build`

---

## Формат плана

Используйте **даты**, а не дни недели — так тренировки точно попадут в нужный день календаря.

```
2026-05-04 (Пн) — Лёгкий бег
Дистанция: 10 км, пульс 125–140 уд/мин

2026-05-06 (Ср) — Темп
Разминка: 2 км, основная часть: 5 км при пульсе 160–170, заминка: 2 км

2026-05-10 (Вс) — Длинный бег
22 км, пульс 120–135 уд/мин
```

Контекст необязателен, но помогает LLM:
- пульсовые зоны (`Z1 < 130, Z2 130–145, ...`)
- уровень подготовки и целевой старт
- специфика недели (восстановительная, ударная)

После `/start` бот пришлёт 5 готовых примеров — можно скопировать любой и сразу отправить.

---

## Rate Limiting

| Ограничение | Значение |
|-------------|----------|
| Cooldown между запросами | 30 секунд |
| Максимальная длина плана | 4000 символов |
| Таймаут LLM-генерации | 300 секунд (5 минут) |

---

## Загрузка тренировок на часы

Подробная инструкция: см. [`docs/HOW_TO_LOAD.md`](HOW_TO_LOAD.md)

Краткий список вариантов:
- **USB** — скопируйте `.fit` файлы в папку `Garmin/NewFiles/` на часах
- **Garmin Express** — официальное приложение garmin.com/express
- **Garmin Calendar** — `/connect_garmin` → `/build` → выбрать 📅 → синхронизировать телефон

## Структура ZIP-архива

```
YYYY/
  MM/
    decade-N/           # decade-1: 1–10, decade-2: 11–20, decade-3: 21–31
      input_plan.txt    # исходный текст плана (точно как прислал пользователь)
      *.fit             # файлы тренировок
```

---

## Локализация

Бот полностью двуязычный. Язык выбирается один раз при `/start` и сохраняется до следующего `/start`. Все сообщения бота — статусы сборки, ошибки, Garmin-команды, кнопки доставки — переведены на оба языка.

Повторный `/start` позволяет сменить язык в любой момент (рабочее состояние не сбрасывается).

---

## Архитектура

```
telegram_bot.py
    ├─→ llm/client.py              (YAML generation)
    ├─→ plan_service.py            (preview, SBU choice, ambiguities)
    ├─→ pipeline_runner.py
    │     └─→ orchestrator.py → build_from_plan.py
    ├─→ archive_manager.py
    └─→ garmin_auth_manager.py
          └─→ garmin_calendar_export.py  (Garmin Calendar upload)
```

Бот — тонкий adapter layer:
- принимает сообщения и файлы
- вызывает shared services
- управляет состоянием пользователя (`UserState`)
- отправляет preview, артефакты и кнопки доставки

**Состояния `UserState.status`:**

| Состояние | Описание |
|-----------|----------|
| `idle` | Ожидание нового плана |
| `generating` | LLM генерирует YAML |
| `awaiting_sbu_choice` | Ждёт выбора drills для SBU-блока |
| `awaiting_clarification` | Ждёт уточнения неоднозначностей |
| `awaiting_confirm` | YAML готов, ждёт `/build` |
| `queued` | Задача в очереди на сборку |
| `building` | Идёт сборка FIT |
| `awaiting_delivery_choice` | Ждёт выбора: ZIP или Garmin Calendar |
| `awaiting_garmin_email` | Ввод email для Garmin |
| `awaiting_garmin_password` | Ввод пароля для Garmin |
| `awaiting_garmin_mfa` | Ввод MFA-кода для Garmin |

---

## Troubleshooting

### `Empty response from LLM` / `Cannot connect to LLM server`

**LM Studio — частая причина:** неверный URL в `bot_config.yaml`.

LM Studio обслуживает API по пути `/v1/`. Бот автоматически добавляет `/v1` если его нет, поэтому оба варианта корректны:

```yaml
llm_url: "http://127.0.0.1:1234"       # /v1 будет добавлен автоматически
llm_url: "http://127.0.0.1:1234/v1"    # явно — тоже верно
```

Также проверьте:
- Local Server запущен и модель загружена в LM Studio?
- Порт 1234 (по умолчанию)?
- В логах LM Studio должно быть `POST /v1/chat/completions`, а не `POST /chat/completions`

**Ollama:**
```powershell
ollama serve
ollama list
```

### Бот не отвечает

- Проверьте `telegram_bot_token`
- Убедитесь, что бот запущен (`python -m garmin_fit.bot`)
- Если задан `allowed_user_ids` — проверьте, что ваш user ID есть в списке

### `Directory is not writable`

Нет прав на запись в директории проекта. Проверьте права доступа.

### LLM generation timed out

Генерация заняла более 5 минут. Причины:
- Слишком большой план
- Медленная модель
- Проблемы с LLM-сервером

Попробуйте более короткий план или более быструю модель.

### Garmin: `garmin-auth not installed`

```powershell
pip install garminconnect garmin-auth
```

### Garmin: ошибка 429

Garmin временно блокирует частые попытки входа. Подождите несколько минут — библиотека автоматически повторяет запрос.

### Garmin: MFA

После пароля бот попросит одноразовый код. Отправьте его в течение нескольких минут.

### Тренировки не появились на часах

Нажмите синхронизацию в приложении Garmin Connect на телефоне.

---

## Обратная совместимость

Старые ключи конфигурации (`ollama_model`, `ollama_url`) поддерживаются и автоматически маппятся на новые (`llm_model`, `llm_url`).

---

## Запуск

```powershell
python -m garmin_fit.bot
```
