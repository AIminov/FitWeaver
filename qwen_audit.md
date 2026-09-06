# Qwen audit — поиск несогласованностей (память между сессиями)

Формат: после каждого прохода — что нашёл, что это значит. Дата сессии: 2026-09-06.

---

## Проход 1 — верхние документы и упаковка (AGENTS/CLAUDE/version/TODO/pyproject/requirements)

### Найдено
1. **AGENTS.md «Next tasks» противоречит TODO.md по exe.** В AGENTS.md (журнал
   localhost-сессии) в Next tasks стоит «Пересобрать оба exe и выполнить GUI smoke»,
   а в TODO.md уже есть секция `✅ FIXED 2026-09-06 — финальные exe`: оба exe
   пересобраны, GUI жив 8 секунд, CLI --help успешен, 364 теста. В журнале AGENTS.md
   нет записи о сессии финальной пересборки.
2. **CLAUDE.md «Next tasks» устарели.** Там всё ещё LAN-ориентированные задачи
   (remote Plan API smoke и т.п.), хотя по AGENTS.md/TODO.md LAN больше не
   используется, канон — localhost LM Studio `http://127.0.0.1:1234`. Счётчик тестов
   в CLAUDE.md (313) датирован 2026-09-02 и допустим как исторический, но список
   задач не синхронизирован с TODO.md.
3. **requirements.txt — неполная копия зависимостей.** В нём только базовые
   зависимости (fit_tool, garmin-fit-sdk, pyyaml, python-telegram-bot>=20.0,
   requests, pydantic>=2.0, openai>=1.0); нет extras (garmin-calendar, api, build,
   gui) и dev. `pydantic>=2.0` дублируется в [project].dependencies и dev-extra
   pyproject.toml (вредного нет). Канонический источник — pyproject.toml; из
   документов это не выделено явно.
4. **CLAUDE.md Development Setup не упоминает extra `.[gui]`** (customtkinter), хотя
   README.md его документирует, а GUI имеет fallback на чистый Tkinter
   (`src/garmin_fit/gui_theme.py: load_customtkinter()`).
5. **`.gui_session.json` ссылается на чужой путь**: `yaml_path = C:/Users/Amir/Desktop/Garmin8.8/Plan/running_plan_2026_v8.yaml` —
   это машина пользователя Amir, а репо по version.txt переименовано в FitWeaver10.5;
   на текущем ПК (imino) такого пути нет. Остаток сессии с другой машины.

### Что это значит
- Пункты 1–2: два «канона» состояния проекта разошлись — при старте новой сессии
  агент/пользователь может решить, что exe устарели (AGENTS.md) или что LAN ещё в
  игре (CLAUDE.md). Нужно синхронизировать Next tasks и добавить запись о финальной
  пересборке в журнал.
- Пункт 3: `pip install -r requirements.txt` даёт неполное окружение без extras;
  стоит пометить pyproject как канон или дописать extras в requirements.
- Пункт 5: GUI при старте попробует открыть несуществующий YAML — пользователь увидит
  ошибку пути, хотя это просто старый session-state (файл gitignored).

### Проверено и согласовано (без замечаний)
- Версии: pyproject `10.5.0` == `src/garmin_fit/__init__.py __version__` == version.txt
  v10.5.0 == CLAUDE.md «Current version».
- Defaults LLM во всех точках кода совпадают: cli.py, runner.py, workflow.py,
  benchmark.py, request_cli.py, fitweaver_gui.py, api_config.yaml.example —
  `http://127.0.0.1:1234(/v1)` + `qwen3.8-27b@iq3_xxs`.
- Benchmark-fixture из README (`tests/fixtures/llm_benchmark/plan_week_2026_03_02.yaml`)
  существует.

---

## Проход 2 — режимы LLM (openai-mode) и примеры в README

### Найдено
1. **README.md / README.ru.md рекомендуют `--openai-mode completions`**, хотя:
   - код по умолчанию использует `auto` (`src/garmin_fit/llm/client.py:120`,
     `request_cli.py:78 default="auto"`);
   - GUI всегда шлёт `"openai_mode": "auto"` (fitweaver_gui.py:1916);
   - docs/LLM_CONNECTION_PROFILE.md рекомендует `--openai-mode auto`;
   - журнал AGENTS.md 2026-09-06 прямо говорит, что compatibility chat/completions
     игнорировал thinking flags и исчерпывал контекст — именно поэтому введён auto.
2. **Help-строка request_cli.py устарела**: «default: ... qwen3.8-27b for openai»,
   а фактический default `qwen3.8-27b@iq3_xxs` (request_cli.py:112).

### Что это значит
- Пользователь, следующий README, принудительно включает completions — тот самый путь,
  который по журналу был источником отказов/переполнения контекста на LM Studio.
  README нужно переключить на auto (или убрать явный флаг и описать дефолт).
- Help-строка вводит в заблуждение при выборе модели: без `@iq3_xxs` запрос уйдёт
  несуществующей модели, если в LM Studio загружен именно qwen3.8-27b@iq3_xxs.

---

## Следующие проходы (план)
- Проход 3: docs/*.md по одному — пути, версии, команды против кода.
- Проход 4: config-примеры (api_config/bot_config/user_profile) vs код; workflow defaults.
- Проход 5: прогон тестов и ruff — сверить с заявленными «364 passed / чистые».

---

## Статус исправлений (Claude, 2026-09-06)

Находки Проходов 1–2 проверены независимо и исправлены. После правок: `pytest` — 364
passed, `ruff check src/` — чисто.

### Проход 1
1. **AGENTS.md vs TODO.md по exe — частично неточно.** Запись о финальной пересборке
   в журнале AGENTS.md **есть** (`### 2026-09-06 — финальная пересборка exe`, самый
   верхний блок), и её «Next tasks» уже не содержат пересборку. Устаревшее упоминание
   «Пересобрать оба exe» находится в более раннем датированном блоке того же журнала —
   это легитимная историческая запись, не рассинхрон. AGENTS.md не менялся.
2. ✅ **ИСПРАВЛЕНО.** CLAUDE.md «Last session summary» и «Next tasks» переписаны под
   канон localhost LM Studio (`http://127.0.0.1:1234` + `qwen3.8-27b@iq3_xxs` +
   `--openai-mode auto`), счётчик тестов → 364, LAN-задачи убраны, пункт про min
   Python приведён к факту (`requires-python >=3.10` == ruff `target py310`).
3. ✅ **ИСПРАВЛЕНО.** В `requirements.txt` добавлена шапка: pyproject.toml —
   канонический источник, файл содержит только базовые runtime-зависимости, для
   extras/dev — `pip install -e ".[...]"`. Дубль `pydantic>=2.0` в pyproject оставлен
   (безвреден, `dev`-extra может ставиться отдельно).
4. ✅ **ИСПРАВЛЕНО.** В CLAUDE.md «Development Setup» добавлена строка
   `pip install -e ".[gui]"` с пояснением про fallback на чистый Tkinter.
5. ✅ **ИСПРАВЛЕНО (локально).** `.gui_session.json` → `yaml_path: ""` (файл
   gitignored, чужой путь с машины Amir убран; GUI стартует без ошибки пути).

### Проход 2
1. ✅ **ИСПРАВЛЕНО.** `--openai-mode completions` → `--openai-mode auto` в
   `README.md` (×2), `README.ru.md` (×2), `docs/README.md` (×3). В `docs/README.md`
   заодно `--model qwen3.8-27b` → `--model qwen3.8-27b@iq3_xxs`.
2. ✅ **ИСПРАВЛЕНО.** Help-строка `request_cli.py` (`--model`): теперь
   «qwen3.8-27b@iq3_xxs for openai». Заодно в docstring того же файла
   `--openai-mode completions` → `auto`.

### Дополнительно (вне Проходов 1–2, найдено при сверке)
- ✅ `bot_config.yaml` (локальный, gitignored): `llm_model` `qwen/qwen3.5-9b` →
  `qwen3.8-27b@iq3_xxs`. Поле, вероятно, рудиментарное — бот ходит через Plan API, —
  но приведено к канону.
- Не тронуто: `README*.md` таблица моделей со строкой `qwen3.8-27b` (это отсылка к
  семейству + «используйте точный ID из /v1/models», не команда);
  `docs/LLM_VALIDATION_SYSTEM.md:388` `--model qwen3.8-27b` (пример, не в списке
  Проходов) — кандидат для Прохода 3.
