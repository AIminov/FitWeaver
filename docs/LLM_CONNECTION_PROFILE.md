# LLM Connection Profile

Актуально на **2026-03-04**.

Документ фиксирует рабочие параметры подключения к локальной модели для генерации YAML.

## Текущий рабочий профиль (рекомендованный)

- Provider: `LM Studio` (OpenAI-compatible API)
- URL: `http://127.0.0.1:1234/v1`
- Model: `qwen/qwen3.5-9b`
- API type: `openai`
- OpenAI mode: `completions`
- LLM timeout: `1800` секунд (30 минут, важно для CPU-ноутбуков)
- Retry count: `3`

## Рекомендуемая команда генерации YAML

```bash
python -m Scripts.llm.request_cli \
  --api openai \
  --url http://127.0.0.1:1234/v1 \
  --model qwen/qwen3.5-9b \
  --openai-mode completions \
  --timeout-sec 1800 \
  --retries 3
```

## Быстрая проверка benchmark-набора

```bash
python -m Scripts.llm.benchmark \
  --suite tests/fixtures/llm_benchmark/plan_week_2026_03_02.yaml \
  --mode generate \
  --api openai \
  --url http://127.0.0.1:1234/v1 \
  --model qwen/qwen3.5-9b \
  --openai-mode completions \
  --timeout-sec 1800
```

Отчет сохраняется в `Build_artifacts/plan_week_2026_03_02.llm_benchmark_report.json`.

## Что сейчас зашито по умолчанию в коде

- `Scripts/llm/request_cli.py`:
  - default `--api`: `ollama`
  - default URL для `openai`: `http://localhost:1234/v1`
  - default model для `openai`: `local-model`
  - default `--timeout-sec`: `1800`
- `Scripts/llm/benchmark.py`:
  - default `--api`: `openai`
  - default URL: `http://127.0.0.1:1234/v1`
  - default model: `qwen/qwen3.5-9b`
  - default `--openai-mode`: `completions`
  - default `--timeout-sec`: `1800`
- `Scripts/telegram_bot.py` использует `bot_config.yaml` и сейчас работает только в Ollama-режиме (`ollama_model`, `ollama_url`).

## Переключение на Ollama (если нужно)

```bash
python -m Scripts.llm.request_cli \
  --api ollama \
  --url http://localhost:11434 \
  --model gemma2:2b
```

Для Telegram-бота параметры берутся из `bot_config.yaml`.

## Doctor + LLM smoke check

```bash
python get_fit.py --doctor --llm \
  --api openai \
  --url http://127.0.0.1:1234/v1 \
  --model qwen/qwen3.5-9b \
  --openai-mode completions \
  --timeout-sec 120
```

Checks:
- Python dependencies
- writable temp directory
- vendored `sdk/py`
- LLM connectivity + one-shot YAML smoke generation

## Package-First Commands

Preferred commands:

`ash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --model qwen/qwen3.5-9b --openai-mode completions --timeout-sec 1800 --retries 3
python -m garmin_fit.llm.benchmark --suite tests/fixtures/llm_benchmark/plan_week_2026_03_02.yaml --mode generate --api openai --url http://127.0.0.1:1234/v1 --model qwen/qwen3.5-9b --openai-mode completions --timeout-sec 1800
python -m garmin_fit.cli doctor --llm --api openai --url http://127.0.0.1:1234/v1 --model qwen/qwen3.5-9b --openai-mode completions --timeout-sec 120
`

Scripts.* commands remain available for backward compatibility, but they are no longer the primary interface.

