# Telegram Bot Setup

Telegram-бот принимает текстовый план, генерирует YAML через локальную LLM (LM Studio или Ollama), показывает preview и после подтверждения собирает FIT-файлы.

## Быстрый старт

### 1. Установите зависимости

```powershell
pip install -r requirements.txt
```

### 2. Настройте LLM сервер

**Вариант A: LM Studio (рекомендуется)**

1. Скачайте [LM Studio](https://lmstudio.ai/)
2. Загрузите модель (например, `qwen2.5-9b-instruct`)
3. Запустите Local Server на порту 1234

**Вариант B: Ollama**

```powershell
ollama pull gemma2:2b
ollama serve
```

### 3. Создайте `bot_config.yaml`

**Для LM Studio:**

```yaml
telegram_bot_token: "YOUR_BOT_TOKEN"

# LLM settings
llm_model: "qwen2.5-9b-instruct"
llm_url: "http://127.0.0.1:1234"
llm_api_type: "openai"

allowed_user_ids: []
```

**Для Ollama:**

```yaml
telegram_bot_token: "YOUR_BOT_TOKEN"

# LLM settings
llm_model: "gemma2:2b"
llm_url: "http://localhost:11434"
llm_api_type: "ollama"

allowed_user_ids: []
```

| Параметр | Описание |
|----------|----------|
| `telegram_bot_token` | Токен от @BotFather |
| `llm_model` | Название модели |
| `llm_url` | URL LLM сервера |
| `llm_api_type` | `"openai"` для LM Studio, `"ollama"` для Ollama |
| `allowed_user_ids` | Whitelist Telegram user IDs (пустой = все) |

### 4. Запустите бота

```powershell
python -m garmin_fit.bot
```

При старте бот проверяет:
- Наличие `bot_config.yaml`
- Доступ на запись в директории `Plan/`, `Output_fit/`, `Archive/`, `Build_artifacts/`

## Команды

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие |
| `/help` | Список команд |
| `/status` | Текущее состояние (status, yaml_ready, queue_size) |
| `/cancel` | Отмена текущей операции / сброс состояния |
| `/build` | Запуск сборки FIT после подтверждения YAML |

## Rate Limiting

Бот имеет встроенные ограничения:

| Ограничение | Значение |
|-------------|----------|
| Cooldown между запросами | 30 секунд |
| Максимальная длина плана | 4000 символов |
| Таймаут LLM генерации | 300 секунд (5 минут) |

## Фактический flow

1. Отправляете текст или `.txt/.md` файл
2. Бот проверяет cooldown и длину текста
3. Бот делает `text -> YAML draft` (с таймаутом 5 мин)
4. Бот применяет auto-repair и показывает preview
5. Если найден `sbu_block` без drills, бот спрашивает: standard или custom
6. После выбора `standard` или custom drills бот при необходимости всё равно проверяет неоднозначности (`ambiguities`).
7. Если LLM вернул неоднозначности (`ambiguities`), бот задаёт уточняющий вопрос.
   - Ответьте текстом — YAML перегенерируется с учётом уточнения (один раунд)
   - Отправьте `/build` — продолжить с текущим YAML как есть
8. Если после этого отправить новый план, clarification-state сбрасывается и новый ambiguous-plan снова может пройти через шаг уточнения.
9. После `/build` запускается:

```text
YAML -> repaired YAML/report -> FIT -> validate -> ZIP -> archive
```

## Что видит пользователь

Preview может включать:

- `Auto-repair` — автоматические исправления
- `Ambiguities` — неоднозначности (при наличии бот задаст уточняющий вопрос)
- `Warnings` — предупреждения
- YAML preview

## Отправка результатов

Бот всегда отправляет ZIP-архив со структурой:

```text
YYYY/
  MM/
    decade-N/        # decade-1: 1–10, decade-2: 11–20, decade-3: 21–31
      input_plan.txt # Исходный текст плана от пользователя
      *.fit          # Файлы тренировок
```

`input_plan.txt` содержит исходный текст плана ровно в том виде, как его прислал пользователь.
Если пользователь проходил один раунд clarification, добавленный служебный текст используется только для повторной генерации YAML и не попадает в ZIP.

## Архитектура

```
telegram_bot.py
    ├─→ llm/client.py (YAML generation)
    ├─→ plan_service.py (preview, SBU choice)
    ├─→ pipeline_runner.py → orchestrator.py → build_from_plan.py
    └─→ archive_manager.py
```

Бот является тонким adapter layer:
- принимает сообщения
- вызывает shared services
- отправляет preview и артефакты обратно

## Troubleshooting

### `Cannot connect to LLM server`

**LM Studio:**
- Убедитесь, что Local Server запущен
- Проверьте порт (по умолчанию 1234)
- Убедитесь, что модель загружена

**Ollama:**
```powershell
ollama serve
ollama list
```

### Бот не отвечает

- Проверьте `telegram_bot_token`
- Убедитесь, что бот запущен
- Если задан `allowed_user_ids`, проверьте что ваш user id разрешен

### `Directory is not writable`

Бот не может записать файлы. Проверьте права доступа к директориям проекта.

### LLM generation timed out

Генерация заняла более 5 минут. Возможные причины:
- Слишком большой план
- Медленная модель
- Проблемы с LLM сервером

Попробуйте меньший план или более быструю модель.

## Обратная совместимость

Старые ключи конфигурации (`ollama_model`, `ollama_url`) поддерживаются для обратной совместимости и автоматически маппятся на новые (`llm_model`, `llm_url`).


## Запуск (предпочтительный способ)

```powershell
python -m garmin_fit.bot
```
