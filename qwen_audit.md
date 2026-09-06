 Qwen audit — поиск несогласованностей (память между сессиями)

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


---

# Re-audit 2026-09-06 (второй прогон, после исправлений из «Статус исправлений»)

## Проход A — верификация фиксов Проходов 1–2 + новые находки

### Верифицировано исправленным
- CLAUDE.md: Last session summary → 2026-09-06, 364 passed, localhost-канон, LAN retired;
  Next tasks переписаны (user smoke через exe, корпус планов, structured output, e2e calendar);
  Development Setup содержит `.[gui]`; requires-python == ruff py310 описано. ✅
- requirements.txt: шапка «pyproject.toml is the canonical dependency source». ✅
- .gui_session.json: yaml_path = "" (чужой путь убран). ✅
- README.md / README.ru.md / docs/README.md: `--openai-mode auto`, модель
  `qwen3.8-27b@iq3_xxs` в командах; таблица моделей оставлена как отсылка к семейству. ✅
- request_cli.py: help «qwen3.8-27b@iq3_xxs for openai», docstring `--openai-mode auto`. ✅

### Найдено (новое)
1. **GUI генерирует с `max_retries=1` — без исправляющего retry.**
   `fitweaver_gui.py:1964/1967` передают `max_retries=1`, тогда как CLI (`request_cli`)
   и бот используют `MAX_RETRIES = 2` (client.py:19, «initial + one correction»).
   Журнал AGENTS.md / TODO.md описывают «retry = 2 полных попытки; исправляющий запрос
   содержит предыдущий ответ» как общее поведение пайплайна — для GUI это неверно.
2. **README-примеры используют `--retries 3`** (README.md:60, README.ru.md аналогично),
   т.е. три полных попытки против канона «2 полные попытки» (MAX_RETRIES=2). Не ошибка,
   но пример расходит с задокументированным дефолтом и может вводить в заблуждение.

### Что это значит
- Пункт 1: пользователь GUI при первом битом YAML сразу получает «YAML не создан» без
  второй попытки — на той же модели, где по журналу IQ3_XXS/IQ4_XS нестабильны, GUI будет
  отказывать чаще CLI. Либо поднять max_retries=2 в GUI (с прогресс-статусом), либо явно
  задокументировать разницу («GUI — одна попытка ради скорости»).
- Пункт 2: привести примеры к `--retries 2` или пометить, что 3 — расширенный режим.

### Проверено и согласовано (без замечаний)
- `generate_yaml_draft` (client.py:167) действительно шлёт весь план одним запросом;
  retry-цикл содержит предыдущий YAML (`_build_retry_prompt(..., previous_yaml=...)`).
  Соответствует описанию в AGENTS.md/CLAUDE.md.

## Проход B — docs/*.md против кода (LLM_VALIDATION_SYSTEM, PROJECT_FLOW, TELEGRAM_SETUP, GARMIN_CALENDAR, HOW_TO_LOAD)

### Найдено
1. **TELEGRAM_SETUP.md описывает старую архитектуру бота (прямой LLM).**
   Гид велит в `bot_config.yaml` поля `llm_model`, `llm_url`, `llm_api_type`;
   troubleshooting тоже ссылается на `llm_url`. Но код (`telegram_bot.py:709`)
   требует ровно `["telegram_bot_token", "plan_api_url", "plan_api_token"]` и
   llm_*-поля не читает вовсе; канонический `bot_config.yaml.example` прямо пишет,
   что бот ходит через Plan API. Конфиг по гиду упадёт на старте (required_keys).
2. **LLM_VALIDATION_SYSTEM.md: «16-point validation checklist» отсутствует в коде.**
   В doc заявлено, что `prompt.py` добавляет чек-лист из 16 пунктов к финальным
   инструкциям; строки 'checklist' нет ни в одном .py/.yaml под src/garmin_fit.
3. **LLM_VALIDATION_SYSTEM.md: образец llm_contract.yaml не совпадает с реальным файлом.**
   В doc показаны `output.workout_keys_exact`, `naming.fallback_pattern`,
   `supported_source_date_forms`, `day_names_allowed` — их нет в настоящем контракте;
   allowed_type_codes в doc содержит `aerobic_drills` и не содержит `threshold`,
   а в реальном файле наоборот (`threshold` есть, `aerobic_drills` нет).
4. **PROJECT_FLOW.md «Сегментированная генерация» устарела.** Описано: 2–10 блоков
   генерируются отдельными запросами и склеиваются. Факт: `generate_yaml_draft`
   (client.py:167) шлёт весь план одним запросом; парсинг заголовков блоков остался
   только для подсказок/фактов (`_extract_workout_facts_from_source_text`).
5. **Разное имя папки на часах.** README/README.ru: `/GARMIN/New files`;
   HOW_TO_LOAD.md, TELEGRAM_SETUP.md, `telegram_bot.py` (сообщения бота),
   `workflow.py`: `NewFiles`. Реальная папка Garmin — «Garmin\New Files».
   В пользовательских сообщениях бота путь без пробела.
6. **GARMIN_CALENDAR.md:24** предлагает `pip install "garmin-fit-generator[garmin-calendar]"`
   — пакет не опубликован в PyPI; для source-checkout корректно
   `pip install -e ".[garmin-calendar]"` (как в README).
7. **CHANGELOG.md не содержит записей 2026-09-04/06** (auto-режим, localhost-канон,
   пересборка exe) — верхняя запись v10.5.0 от 2026-09-02; в журнале AGENTS.md эти
   сессии есть. Либо «unreleased»-секция, либо новый номер версии.

### Что это значит
- Пункт 1 — критично для нового пользователя бота: единственный setup-гайд ведёт к
  гарантированному падению на старте (нет plan_api_url/plan_api_token). Нужно переписать
  TELEGRAM_SETUP.md под Plan API-архитектуру (запустить `garmin-fit-api`, заполнить
   plan_api_*), либо вернуть боту прямой LLM-режим — но тогда это должно быть в коде.
- Пункты 2–3: LLM_VALIDATION_SYSTEM.md продаёт механизм самопроверки модели, которого
  нет; при этом контракт в doc расписан неверно (aerobic_drills vs threshold). Документ
  нужно сверить с prompt.py/llm_contract.yaml и убрать вымышленный чек-лист.
- Пункт 4: PROJECT_FLOW.md учит «сегментированную генерацию» как актуальное поведение —
  противоречит канону «один запрос на весь план» (AGENTS.md/CLAUDE.md).
- Пункт 5: пользователь, копирующий .fit по инструкции бота, может не найти папку
  `NewFiles` (её нет) или наоборот. Привести все места к одному имени.
- Пункт 6: свежий клон + `pip install "garmin-fit-generator[...]"` упадёт с
  «no such package»; заменить на editable-форму.
- Пункт 7: changelog отстаёт от журнала; не критично, но ломает «changelog = история».

### Проверено и согласовано (без замечаний)
- strict_examples.yaml: 10 correct + 11 failure — совпадает с doc («10» / «10+»).
- ALLOWED_INTENSITY (plan_domain.py) == allowed_intensity контракта.
- GUI_UX_REVIEW.md помечен датой как baseline-снимок (2026-07-10) — допустимо.

## Проход C — config-примеры против кода

### Найдено
1. **api_config.yaml.example: устаревшая перекрёстная ссылка.** Комментарий «The LLM this API
   proxies to (same shape as bot_config.yaml's llm_* keys)» — но в bot_config.yaml больше нет
   llm_*-ключей (бот ходит через plan_api_url/plan_api_token). Форма совпадает с ApiSettings,
   а не с bot_config.

### Проверено и согласовано (без замечаний)
- api_config.yaml.example ↔ `src/garmin_fit/api/config.py`: все поля и дефолты совпадают
  (api_token + env FITWEAVER_API_TOKEN, host 0.0.0.0, port 8008, llm_url/model/api_type/timeout,
  rate_limit_per_minute=6 / burst=2). GUI-дефолт api_url `http://127.0.0.1:8008` совпадает. ✅
- user_profile.yaml.example ↔ profile_store.write_user_profile / prompt.py (hr_zones):
  формат и поля совпадают; max_hr/resting_hr/hr_zones zone1..5. ✅

## Проход D — прогон тестов, Ruff, compileall

### Найдено
1. **Полный pytest: 363 passed + 1 ERROR** (не «364 passed»). Ошибка детерминированна в трёх
   полных прогонах: `test_llm_pipeline_regressions.py::test_cli_does_not_promote_detected_headers_to_explicit_count`
   падает на setup `tmp_path`: `PermissionError [WinError 5] Access is denied: .tmp_runtime_tests\pytest-of-imino`.
   Механизм: `tests/test_000_temp_bootstrap.py` перенаправляет TMP/TEMP в `.tmp_runtime_tests`,
   а OneDrive (репо лежит под OneDrive) блокирует каталог во время синхронизации; в .gitignore
   это не помогает — OneDrive его не читает. В отдельном прогоне того же файла: 35 passed,
   ошибки нет. Это окружение (OneDrive-лок), а не сбой ассертов.
2. **Остатки tmp-каталогов**: в `.tmp_runtime_tests` ~19 каталогов `tmp*` от прерванных прогонов
   (cleanup только при нормальном выходе) — усиливают давление синхронизации/локов.

### Что это значит
- Заявка «364 passed» верна только когда OneDrive не держит лок; на этой машине полный прогон
  даёт 363+1 error. Варианты: исключить `.tmp_runtime_tests` из синхронизации OneDrive, либо
   bootstrap-тесту использовать каталог вне репо (например %TEMP%), либо чистить остатки.
- Для CI/локальных проверок стоит фиксировать «364 collected» и допускать 1 environment-error
  с пометкой, иначе каждый прогон на OneDrive-машине будет «красным».

### Проверено и согласовано (без замечаний)
- `ruff check src/ fitweaver_gui.py Scripts/ garmin_fit/ tests/` — All checks passed ✅
  (совпадает с заявкой; pyproject ruff target py310, ignore E501/W19x/E701).
- `python -m compileall src fitweaver_gui.py Scripts garmin_fit` — чисто. ✅

## Проход E — packaging, CI, examples, прочее

### Найдено
1. **.gitignore ссылается на несуществующий `packaging/fitweaver.spec`.** Реальные спеки —
   `packaging/fitweaver_gui.spec` и `packaging/fitweaver_cli.spec`; комментарий в .gitignore
   устарел (имя до разделения на два spec).
2. **CI тестирует только Python 3.13.** `requires-python = ">=3.10"`, ruff target py310,
   рабочий venv — 3.12.10; нижняя граница 3.10 в CI не покрывается (ранее был специфичный
   3.10-баг asyncio.to_thread, который фиксировался под тесты). Риск: регрессия на 3.10/3.11
   не будет видна из CI.

### Что это значит
- Пункт 1: косметика — поправить комментарий в .gitignore (или убрать строку, если /dist/ и
  /build/ уже покрывают артефакты).
- Пункт 2: либо добавить matrix [3.10, 3.12, 3.13] в ci.yml, либо официально поднять
  requires-python до 3.11/3.12 и зафиксировать решение (в CLAUDE.md задача «решить min Python»
  закрыта синхронизацией py310, но CI-покрытие границы отсутствует).

### Проверено и согласовано (без замечаний)
- packaging/*.spec: onefile, datas=llm yaml/txt + customtkinter, hiddenimports=все подмодули
  garmin_fit; раздельные spec-файлы обоснованы (коллизия PYZ). build.ps1 + cli_entry.py на месте. ✅
- CI: `ruff check .` и `pytest -q` с `.[dev]`; fastapi/garminconnect не ставятся → часть тестов
  skip — ожидаемо. ✅
- examples/*.py используют root-мост `garmin_fit.workout_utils` (корректно для source-checkout,
  соответствует LEGACY_COMPAT.md). ✅
- docs/README.md: команды приведены к auto + qwen3.8-27b@iq3_xxs (×3). ✅
- state.json — счётчик FIT serial/timestamp (локальное состояние), противоречий нет. ✅

---

## Итог re-audit 2026-09-06 (второй прогон)

Критичное: TELEGRAM_SETUP.md (бот через Plan API, а не прямой LLM — конфиг по гиду не
запустится). Значимое: GUI max_retries=1 против канона 2; PROJECT_FLOW «сегментация» и
LLM_VALIDATION_SYSTEM чек-лист/контракт устарели; имя папки часов `NewFiles` vs `New files`;
GARMIN_CALENDAR.md pip-install неопубликованного пакета. Окружение: полный pytest на этой
OneDrive-машине = 363 passed + 1 PermissionError (test_000_temp_bootstrap → .tmp_runtime_tests,
лок OneDrive); в отдельном прогоне файл проходит. Всё остальное согласовано; фиксы Проходов
1–2 подтверждены.

---

## Статус исправлений re-audit (Claude, 2026-09-07)

Все находки Проходов A–E проверены независимо. После правок: `pytest` — **366 passed**
(364 + 2 новых регресс-теста), `ruff check src/ fitweaver_gui.py tests/` — чисто.

### Проход A
1. ✅ **ИСПРАВЛЕНО, находка была шире.** Расхождение не двойное, а четверное:
   `client.MAX_RETRIES=2` (CLI), `plan_service.py:23`=3, `api_client.py:46`=3,
   `api/schemas.py:20`=3 (то есть **бот через Plan API получал 3**, чего аудит не
   заметил), `fitweaver_gui.py:1964/1967`=1 в обеих ветках. Всё сведено к `MAX_RETRIES`;
   хардкод в GUI убран. Добавлены два регресс-теста:
   `test_all_entry_points_share_one_retry_budget` и
   `test_gui_does_not_hardcode_a_retry_budget`.
2. ✅ **ИСПРАВЛЕНО, но ссылка была неверной.** `--retries 3` встречался только в
   `docs/README.md:60`; в `README.md` / `README.ru.md` его нет вовсе. Убран.

### Проход B
1. ✅ **ИСПРАВЛЕНО (критичное подтверждено).** `docs/TELEGRAM_SETUP.md` переписан под
   Plan API: новый шаг 3 (`pip install -e ".[api]"` → `api_config.yaml` →
   `garmin-fit-api`), таблица ключей приведена к фактическим
   `telegram_bot_token`/`plan_api_url`/`plan_api_token` (+ необязательные
   `allowed_user_ids`/`session_timeout_sec`), troubleshooting разделён на «не отвечает
   Plan API» (`api_unreachable`) и «не отвечает LLM за ним» (`llm_no_connect`), секция
   «Обратная совместимость» заменена на «Миграция со старых версий».
2. ✅ **ИСПРАВЛЕНО.** Раздел «Layer 4» переписан: чек-листа в коде нет, правила живут в
   `llm_contract.yaml`. Добавлено историческое пояснение — см. ниже.
3. ✅ **ИСПРАВЛЕНО.** Образец контракта в doc приведён к реальному файлу:
   `workout_keys_exact` → указано, что ключи проверяет `plan_schema.WorkoutSchema`;
   `fallback_pattern`/`supported_source_date_forms`/`day_names_allowed` → указано, что
   они в `plan_processing.py`; `allowed_type_codes` перечислен как в файле
   (`threshold` есть, `aerobic_drills` нет).
4. ✅ **ИСПРАВЛЕНО.** `PROJECT_FLOW.md` — блок «Сегментированная генерация» заменён на
   «Один запрос на весь план» с указанием, почему от сегментации отказались.
5. ⏳ **ОТЛОЖЕНО (нужен пользователь).** `NewFiles` vs `New files` — расхождение реально
   (`NewFiles` в HOW_TO_LOAD/TELEGRAM_SETUP/examples/`telegram_bot.py:263,440`/
   `workflow.py:392`; `New files` в README×4, README.ru×2). Какое имя верное — из
   репозитория не проверяется, у Garmin оно различается между MTP и mass-storage.
   Нужно посмотреть на самих часах.
6. ✅ **ИСПРАВЛЕНО.** `GARMIN_CALENDAR.md` → `pip install -e ".[garmin-calendar]"` с
   пояснением, что пакет не опубликован в PyPI.
7. ⏳ **ОТЛОЖЕНО (P3).** CHANGELOG за 2026-09-04/06.

### Проход C
1. ✅ **ИСПРАВЛЕНО.** Комментарий в `api_config.yaml.example` больше не ссылается на
   несуществующие `llm_*` в `bot_config.yaml`.

### Проход D
1. ⚠️ **ДИАГНОЗ УТОЧНЁН — не детерминизм, и причина другая.** Полный `pytest tests/`
   даёт **366 passed** во всех прогонах этой сессии (до правок — 364). Реальная причина:
   каталог `C:\Users\imino\AppData\Local\Temp\pytest-of-imino` (создан 2026-09-06 23:05)
   повреждён — не читается даже `Get-Acl`. При **полном** прогоне
   `test_000_temp_bootstrap.py` уводит TMP в `.tmp_runtime_tests`, и битый каталог не
   задевается; при запуске **одного файла** бутстрап не отрабатывает, pytest идёт в
   системный temp и падает с `PermissionError`. То есть дело не в локе OneDrive на
   `.tmp_runtime_tests`, а в конкретном сломанном каталоге в системном temp.
   Лечится `rmdir /s /q` по этому пути; сам не удалял — содержимое нечитаемо.
2. ⏳ **ОТЛОЖЕНО (P3).** 19 остаточных `tmp*` в `.tmp_runtime_tests`; отдельный вопрос —
   стоит ли вообще держать TMP внутри OneDrive-репозитория.

### Проход E
1. ⏳ **ОТЛОЖЕНО (P3).** `.gitignore` про `packaging/fitweaver.spec`.
2. ⏳ **ОТЛОЖЕНО (P3).** CI только на 3.13 при `requires-python >=3.10`.

---

## Сверка с прошлой итерацией проекта (Claude, 2026-09-07)

По просьбе пользователя прочитана v8.4 в `C:\Users\imino\OneDrive\Desktop\Garmin8.7\Garmin8.4`
на предмет потерянного функционала. **Существенных потерь нет** — текущая версия строгая
надстройка: те же 9 типов шагов и 4 intensity, все 10 `workflow_*` функций (+2 Garmin
Calendar), все 12 старых тест-файлов (+18 новых), все 7 категорий правил из старого
`LLM_YAML_RULES.md` проверяются, лимит имени drill 12 символов на том же месте,
`restore_from_archive` побайтово идентична. Вложенные `repeat` в v8.4 были запрещены —
сейчас поддерживаются.

Удалённое безопасно: `generate_marathon_templates.py` (генератор шаблонов эпохи v1),
`regenerate_v3_yaml.py` (одноразовая миграция с захардкоженными датами),
`_make_unique_file_destination` (**был определён, но никогда не вызывался**),
`load_hr_zones` (свёрнут в `load_user_profile`), `run_pipeline.bat/.sh` (обёртка вокруг
legacy-пути; `cli run` делает это одной командой), 4 документа-плана, все пункты которых
помечены выполненными.

**Это объясняет происхождение находок B2 и B4 — доки не выдуманы, а перенесены из v8.4
без правки:**
- 16-point checklist **реально существовал**: старый `Scripts/llm/prompt.py:201-217`
  содержал буквально пункты 1–16. Заменён `llm_contract.yaml` (правил стало больше).
- Сегментация **реально работала**: старый `docs/LLM_YAML_IMPROVEMENTS.md` →
  «Приоритет 3: Сегментация ✅ ЗАКРЫТО (Session 2)». Убрана осознанно 2026-09-06.

**Новая находка из сверки (не было ни в одном проходе):** `prompt.py:355` и
`llm_contract.yaml` (`repeat_block`, `forbidden_patterns`) запрещают модели вложенные
`repeat` — это пункт 16 старого чек-листа, — тогда как `plan_validator.py:464` их
поддерживает и отвергает только пересечение без вложенности. Промпт строже системы.
Поведение не менял: ограничение для нестабильной локальной модели при более свободном
валидаторе для GUI-Конструктора выглядит осмысленным. Асимметрия задокументирована в
`LLM_VALIDATION_SYSTEM.md`; если она непреднамеренна — снять запрет в контракте.