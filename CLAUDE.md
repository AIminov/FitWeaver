# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See `version.txt` for project version history. See `TODO.md` for the full task backlog.

---

## ⚡ Правило для Claude: обновляй этот файл и TODO.md в конце каждой сессии

В конце каждой рабочей сессии (перед финальным коммитом):
1. Обнови раздел **«Журнал сессий»** ниже — что сделано, какие решения приняты, что отложено и почему.
2. Обнови раздел **«Next tasks»** — следующие приоритеты.
3. Обнови `TODO.md` — пометь выполненные пункты `✅ FIXED`, добавь новые идеи.
4. Закоммить оба файла вместе с остальными изменениями.

---

## Журнал сессий

### 2026-07-07 (продолжение) — Фаза E: упаковка GUI в standalone .exe
**Сделано:**
- Два фризед-безопасных фикса пути (предпосылка для exe): `config.py`'s `PROJECT_ROOT` и
  `fitweaver_gui.py`'s собственный `PROJECT_ROOT` теперь ветвятся на `getattr(sys, "frozen",
  False)` — в exe используют `Path(sys.executable).resolve().parent` (папку рядом с exe,
  стабильную между запусками), иначе прежнее поведение из исходников не тронуто.
- `_run()`/`_cli_command()`: сайдбар-кнопки ("Собрать FIT-файлы", "Загрузить/Удалить из
  Garmin", вся секция "ПРОДВИНУТЫЕ") звали `[sys.executable, "-m", "garmin_fit.cli", ...]` —
  во фризед exe `sys.executable` это сам GUI-exe, не интерпретатор, поэтому это не сработало
  бы. Теперь в frozen-режиме зовут exe-соседа `garmin-fit-cli.exe`. Плюс `CREATE_NO_WINDOW`,
  чтобы не мигало консольным окном при каждом клике.
- `packaging/` (новое): `cli_entry.py` (обёртка над `garmin_fit.cli:main` для второго exe),
  `fitweaver_gui.spec`/`fitweaver_cli.spec` (два отдельных spec-файла — важно, не два
  `Analysis`/`PYZ`-блока в одном: PyInstaller именует промежуточный `PYZ-01.pyz` одинаково
  внутри общей рабочей директории, и второй билд молча затирает архив первого на диске без
  ошибки сборки), `build.ps1`.
- **Ключевой найденный баг (не вручную, а через полноценный smoke-тест реального .exe):**
  собранный `FitWeaver.exe` падал с `ModuleNotFoundError: No module named
  'garmin_fit.workout_builder'` при открытии вкладки Конструктор. Причина: в корне репо
  лежит `garmin_fit/` — легаси compatibility-bridge пакет (см. архитектуру: "alias bridge
  layer, DO NOT edit directly"), который содержит только `__init__.py` + пустую `llm/`
  и добавляет `src/garmin_fit` в свой `__path__` ТОЛЬКО во время реального выполнения
  (`__path__.append(...)`). PyInstaller автоматически добавляет папку главного скрипта
  (`fitweaver_gui.py` лежит в корне репо) в свой путь поиска, и при разрешении *лениво*
  импортируемых модулей (а `fitweaver_gui.py` почти всё импортирует внутри методов, не на
  уровне модуля) статический анализ не выполняет `__init__.py` и видит только реальные файлы
  моста — которых там почти нет. Отсюда модули без одноимённого файла в мосте (`plan_store`,
  `workout_builder`, и по факту почти всё остальное, что не проверялось вручную) тихо
  выпадали из сборки без единой ошибки сборки. **Фикс:** `build.ps1` теперь собирает не из
  живого дерева исходников, а из изолированной копии-стейджинга (`build/stage/`: только
  `src/`, `fitweaver_gui.py`, `packaging/`) — без корневого `garmin_fit/`, однозначность
  разрешения пакета гарантирована. Проверено через `PyZ`-TOC (61 подмодуль вместо 2) и
  реальный запуск exe (Конструктор открывается, крэша нет).
- Ручной smoke-тест: собранный `garmin-fit-cli.exe` реально выполнил `validate-yaml` на
  тестовом YAML в чистой временной папке (без Python) — подтверждает, что весь путь
  GUI→CLI-subprocess рабочий, а не только "модуль присутствует в архиве".

**Решения/отказы:**
- Только GUI (не бот, не Plan API) — подтверждено вопросом пользователю.
- `onefile`, не `onedir` — безопасно, т.к. состояние резолвится через `sys.executable`,
  стабильный между запусками даже при переизвлечении onefile во временную папку.
- Установщик (Inno Setup/NSIS), подпись кода, авто-обновление — осознанно не делали, вне
  рамок задачи.

307 тестов (backend не тронут) по-прежнему проходят.

**Продолжение той же сессии — реальный пользовательский прогон exe вскрыл 3 проблемы:**
- `pyinstaller` не был на PATH → `build.ps1` падал на CLI-шаге молча оставляя старый .exe;
  фикс — вызывать через `python -m PyInstaller`.
- Два PyInstaller-вызова подряд в общий родительский `build\` ловили гонку блокировки файлов
  Windows (`FileNotFoundError` при создании `base_library.zip` второй сборки) — фикс:
  раздельные `--workpath` (`build\gui`, `build\cli`).
- **Два реальных краш-бага в CLI**, не связанных с упаковкой (воспроизводятся и в
  `python -m garmin_fit.cli` из исходников, просто раньше никто не передавал `--plan` с путём
  вне `ROOT`/`PLAN_DIR`): `workflow_validate_yaml()` падал с `ValueError` на
  `yaml_file.relative_to(ROOT)`, если план лежит вне корня — чисто косметическая строка лога
  роняла всю команду. `check_prerequisites()` игнорировал переданный `--plan` и всегда требовал
  хотя бы один YAML именно в `PLAN_DIR`, из-за чего `run --plan <путь>` фейлился на пустой
  `Plan/` рядом с exe, даже если план лежит в другом месте. Оба чинятся: новый
  `_shared_cli.display_path(path, root)` (relative-or-absolute-fallback, вместо голого
  `relative_to`) и `check_prerequisites(plan_path=None)` теперь проверяет конкретный файл,
  если он передан, вместо сканирования `PLAN_DIR`. 2 новых теста (`test_shared_cli.py`),
  309 итого.
- `doctor`'s `[FAIL] vendored sdk/py package not found` — НЕ баг, опциональная доп.проверка
  (`--no-sdk-python-check` уже существует), не блокирует сборку/валидацию/upload — те уже
  используют pip-пакет `garmin_fit_sdk`. Просто ожидаемое поведение в упакованном exe (папка
  `sdk/py` не бандлится и не должна).
- Найден (не исправлен, вне скоупа сессии) отдельный баг: `llm/benchmark.py` ссылается на
  необъявленное имя `ROOT` вместо импортированного `PROJECT_ROOT` — вызовет `NameError` при
  первом реальном запуске бенчмарка. Вынесен в отдельную задачу через spawn_task.

---

### 2026-07-07 — Фаза D: простой/экспертный режим интерфейса
**Сделано:**
- Новый `self.ui_mode` (`"simple"`/`"expert"`, по умолчанию `"simple"`) в `fitweaver_gui.py` —
  глобальная настройка (тот же уровень, что `llm_conn_mode`/`api_url`: описывает интерфейс
  машины, а не личные данные пользователя), персистится в `.gui_session.json` по образцу
  существующего `llm_conn_mode`-паттерна.
- Чекбокс "Экспертный режим" в сайдбаре, `_on_ui_mode_change()` скрывает/показывает три блока:
  секцию "ПРОДВИНУТЫЕ" в сайдбаре (Валидировать YAML/FIT, Диагностика, Архивировать и т.д.),
  панели подключения LLM (`_conn_own`/`_conn_api`) на вкладке LLM, поле "Лимит" на вкладке
  Garmin Connect.
- На вкладке LLM панель подключения в простом режиме скрыта за кнопкой "Настроить
  подключение" (не требует переключения в экспертный режим целиком для первичной настройки) —
  `_toggle_llm_conn_expanded()`/`self._llm_conn_expanded`.
- Попутно исправлена скрытая проблема с `pack()`/`pack_forget()`: повторный `pack()` без
  `before=` добавляет виджет в КОНЕЦ списка управляемых потомков, а не на прежнее место —
  при переключении режимов панель подключения LLM или поле "Лимит" могли бы визуально
  "уехать" после первого переключения. Все повторные `pack()`-вызовы в этой зоне используют
  `before=self._llm_check_row` / `before=self._gc_del_btn`, чтобы позиция была детерминирована.
- Конструктор и Календарь не тронуты — намеренно (см. решение в предыдущей сессии: слишком
  рискованно резать функциональность повторов/палитры блоков ради упрощения интерфейса).
- Ручной smoke-тест через headless-инстанс `App()` (`pack_info()` вместо `winfo_ismapped()`,
  т.к. скрытые вкладки `ttk.Notebook` не мапятся до выбора — обычный false negative для этой
  проверки) — переключение simple↔expert, экспандер, персистентность в `.gui_session.json`
  подтверждены. Нет автотестов на GUI (нет тестовой инфраструктуры для Tkinter в проекте — то
  же решение, что в Фазе C).

**Решения/отказы:**
- Область действия сознательно сужена до "лёгкого" варианта (подтверждено вопросом
  пользователю): сайдбар + LLM-подключение + Garmin-лимит. Не трогали Конструктор — упрощение
  палитры блоков/повторов лишило бы простой режим возможности собрать интервальную тренировку.

**Следующие задачи:** редактирование уже закоммиченных тренировок в Конструкторе;
реальный remote-хостинг Plan API (пока проверен только localhost).

---

### 2026-07-06 — Desktop GUI: SQLite-слой, мультипрофили, визуальный конструктор
**Сделано:**
- `plan_store.py` (новый) — SQLite как внутренний рабочий слой GUI. YAML остаётся единственным каноническим форматом для CLI/бота/сборки/Garmin-загрузки; `PlanStore` пишет обратно в YAML после каждой мутации. Уровень тренировок: `move_workout`, `duplicate_workout`, `delete_workout`, `rename_workout_filename`. Уровень шагов: `insert_step`, `delete_step` (отклоняет удаление anchor-шага repeat-группы), `move_step` (v1: отклоняет, если в тренировке уже есть repeat — безопасная переоценка только в черновике до коммита), `add_repeat_over_range` (вычисляет `back_to_offset` из позиций, GUI никогда не видит и не хранит индекс), `add_drill`/`delete_drill`/`move_drill`, `add_workout`.
- `profile_store.py` (новый) — мультипрофили по email на одном ПК: свой `plan.db`/`user_profile.yaml`/`session.json` на профиль. Слаг профиля переиспользует ту же md5-схему, что и кэш токенов Garmin (`workflow._resolve_garmin_token_dir` теперь делегирует туда же). Онбординг новых профилей: авто-миграция легаси `user_profile.yaml` (одноразовая, через маркер-файл — иначе `activate_user_profile()` заново "подсовывает" данные активного профиля следующему новому профилю) либо диалог с вводом HR (макс./покоя, зоны считаются автоматически, можно пропустить).
- `workout_builder.py` (новый) — визуальный конструктор тренировок без LLM. `BLOCK_DEFS` (палитра: разминка/актив-км/актив-мин/восстановление/заминка/СБУ), `TEMPLATES` (интервалы/темповый/длинный с ускорением), `compute_repeat_step()` (та же логика проверки диапазона, что и `PlanStore.add_repeat_over_range`, чтобы черновик и закоммиченный результат никогда не расходились), `validate_draft()`.
- `fitweaver_gui.py` — новая 4-я вкладка "🧱 Конструктор": палитра блоков → список шагов (клик + Shift+клик выделяет диапазон) → "Повторить ×N" (без ручного ввода `back_to_offset`) → редактор полей блока → "Добавить в план". Плюс переключатель профилей в сайдбаре (Combobox вместо Entry email), диалог первого запуска для HR-профиля.
- 251 тест (было 197 на начало сессии), полный набор проходит дважды подряд без утечек файлов.

**Баги, пойманные тестами (не мной вручную):**
- Числовые поля (`back_to_offset`, `km`, `hr_low`...) при чтении из SQLite возвращались строками — при экспорте попали бы в YAML в кавычках. Исправлено приведением типов на чтении.
- `tests/test_000_temp_bootstrap.py` подменяет `tempfile.TemporaryDirectory` на вариант с ленивым созданием папки (внутри `__enter__`) — новые тесты, вызывавшие класс без `with`, писали временные файлы в реальный корень проекта. Исправлено явным `__enter__`/`__exit__`.
- `activate_user_profile()` каждый раз кладёт данные активного профиля в общий глобальный `user_profile.yaml`-слот — из-за этого второй новый профиль ошибочно принимал этот слот за "легаси-данные" и крал чужой HR-профиль. Исправлено одноразовым маркер-файлом `profiles/.legacy_migrated`.
- Ручной смок-тест вкладки "Конструктор" по ошибке дописал тестовую тренировку в реальный `Plan/running_plan_2026_v8.yaml` — обнаружено и откачено точечным `Edit`, реальный файл подтверждённо восстановлен (97 тренировок, без изменений).

**Решения/отказы:**
- Визуальный конструктор v1 строит только НОВЫЕ тренировки, не редактирует уже закоммиченные (с уже существующими repeat-блоками) — самый рискованный случай (перемещение/удаление шага вокруг существующего repeat-anchor) явно отложен, но `PlanStore` спроектирован так, чтобы это можно было включить позже без переделки.
- LLM-настройки (URL/модель/таймаут) остаются общими на весь ПК, не per-профиль — это описание локального сервера, а не личные данные пользователя.
- Единый API над `plan_service.py` (чтобы GUI/бот не дублировали логику генерации) и рефакторинг Telegram-бота — обсуждены и одобрены, но отложены на следующую сессию.

**Продолжение той же сессии — Фаза A backlog cleanup:**
- TODO #6 (таймаут сессии бота), #7 (футер YAML-превью с /build+исправить+/cancel), закрыты
- `garmin_auth_manager.prompt_mfa_with_timeout()` — таймаут 120с на блокирующий `input()` вместо бесконечного ожидания
- Тесты error-путей (`load_plan_build_input`, `garmin_calendar_export` сетевые ошибки, `build_from_plan` ошибка записи) и вложенного `repeat` в `garmin_step_mapper` — 18 новых тестов, итого 279

**Продолжение той же сессии — Фаза B (GUI-фичи поверх `PlanStore`), всё закрыто:**
- Drag & drop тренировок между днями календаря (клик = открыть детали, драг = перенести)
- Ctrl+Drag = копия тренировки на другой день, с защитой от коллизии имён (`_copy`/`_copy2`)
- Недельный график объёма (км) в Календаре — canvas-бар-чарт, одна полоса на неделю месяца
- Toast-уведомления — автоматически из существующих `[OK]`/`[ERR]`/`[WARN]` префиксов в `_log()`, видны на любой вкладке
- Личная библиотека шаблонов в Конструкторе, per-профиль (`profiles/{slug}/templates.json`)
- Найден и исправлен реальный баг: `_prompt_hr_profile` падал для КАЖДОГО нового профиля без легаси `user_profile.yaml` (`pady=(16,4)`-кортеж в конструкторе `tk.Label` вместо `.pack()`) — не был пойман раньше, т.к. предыдущие тесты мокали этот диалог целиком

6 новых тестов на эту фазу, итого 286 проходят.

**Продолжение той же сессии — Фаза C: единый Plan API, всё закрыто:**
- Новый `src/garmin_fit/api/` (FastAPI) — тонкая HTTP-обёртка над `plan_service.py`:
  `/v1/generate-draft`, `/v1/apply-sbu-choice`, `/v1/health`. Никакой логики генерации не
  задублировано — маршруты только строят `UnifiedLLMClient` и вызывают уже существующие
  функции `plan_service.py`. Auth — заголовок `X-Api-Token` (`api_config.yaml` +
  `FITWEAVER_API_TOKEN` env override), rate limit — token bucket per-токен на `app.state`
  (изолирован между тестами). Новый extra `pip install -e ".[api]"`, entry point
  `garmin-fit-api`.
- `src/garmin_fit/api_client.py` (`PlanApiClient`/`PlanApiError`) — общий HTTP-клиент для
  бота и GUI.
- **`telegram_bot.py` — бот стал тонким клиентом API**, а не строит `UnifiedLLMClient`
  напрямую. Конечный автомат (`idle → generating → ...`), ZIP-доставка, все i18n-сообщения —
  не тронуты; изменились только два вызова (`_process_plan`/`_handle_sbu_choice`) и
  `_build_llm_client()`. Новые ключи `bot_config.yaml`: `plan_api_url`/`plan_api_token`,
  старые `llm_model`/`llm_url`/`llm_api_type` убраны из required_keys (бот их больше не
  использует). Новое i18n-сообщение `api_unreachable` для сбоя связи с API (отдельно от
  `llm_no_connect`, который проверяет LLM за API).
- **GUI: новый режим "LLM автора"** в LLM-вкладке — переключатель "Своя LLM"/"LLM автора",
  второй режим подключается к чужому хостед-инстансу Plan API вместо локальной LLM.
  Настройки (`api_url`/`api_token`/`llm_conn_mode`) в общем `SESSION_FILE`, как и остальные
  LLM-настройки — это описание сервера/сервиса, не профиля пользователя.
- Бот+API всегда общаются по HTTP, даже на одной машине — без флага для in-process
  обхода (обоснование: сетевой оверхед на loopback ничтожен по сравнению с временем
  инференса LLM; флаг потребовал бы дублировать оба пути вызова).
- Ручной smoke-тест: реальный `garmin-fit-api` через `python -m garmin_fit.api_cli`,
  проверено curl'ом — без токена 401, с неверным токеном 401, с верным `{"llm_connected":false}`
  (реальной LLM не было, это ожидаемо).

20 новых тестов (`test_plan_api.py`, `test_api_client.py`), итого 307 проходят.

**Следующие задачи:** редактирование уже закоммиченных тренировок в Конструкторе; drag&drop
между днями через реальный remote-хостинг API (сейчас только localhost проверен); простой/
экспертный режим интерфейса.

---

### 2026-04-23 (v10.4 / v10.4.1)
**Сделано:**
- `build_yaml_to_fit_index()` вынесен в `workout_utils.py` — теперь один источник правды для обоих билдеров
- Валидация pace и HR дедуплицирована: `_is_valid_pace`, `_check_pace_ordering`, `_pace_to_seconds` живут в `plan_schema.py`, импортируются в `plan_validator.py`
- HR поля ограничены `le=250` в Pydantic-схеме
- `logging_utils.setup_file_logging()` не добавляет дублирующий FileHandler при повторном вызове
- `garmin_calendar_export._date_in_range()` логирует warning вместо тихого включения при нечитаемой дате
- `plan_domain` логирует предупреждения при отброске не-Mapping элементов
- `build_from_plan.build_all_fits_from_plan()` перечисляет имена упавших тренировок в итоговом логе
- `Scripts/telegram_bot.py` — шим молчал (не вызывал `main()`), исправлено
- `test_config.py` — изоляция тестов через `setUp`/`tearDown`
- Локализация СБУ в Garmin Calendar: "Отдых"/"Recovery", "Упражнение N"/"Drill N"; язык берётся из выбора пользователя в боте
- `requires-python` понижен с `>=3.13` до `>=3.10`
- `runner.py` переписан: loop, 14 опций, читает `GARMIN_EMAIL`/`GARMIN_PASSWORD` из env

**Решения/отказы:**
- `pipeline_runner.py` НЕ удалять — `telegram_bot.py` импортирует `run_pipeline` и `save_yaml_to_plan_dir` напрямую
- `sbu_block.py DEFAULT_DRILLS` НЕ выносить в конфиг — избыточно, имена уже на русском
- Gemma-4 сломана с `enable_thinking: false` — рекомендован Qwen3

**Следующие задачи:** TODO #6 (session timeout), #7 (YAML preview UX footer)

---

## Session continuity

**This file is the primary context source across machines.** The user (Amir / GitHub: AIminov) works on multiple PCs. Always read this file and `TODO.md` at the start of a session.

**Current version:** v10.4.1 (2026-04-23) + Desktop GUI (2026-07-07)  
**Repo:** https://github.com/AIminov/FitWeaver.git  
**Git identity:** `git config --global user.email "iminov@gmail.com" && git config --global user.name "AIminov"`  
**Auth:** user uses `gh` CLI — already authenticated as AIminov. No need to configure tokens.

**Next tasks (agreed, start here):**
1. Editing an already-committed workout's steps in the Конструктор tab (currently v1-scoped to building new workouts only — see 2026-07-06 session log for why this was deferred).
2. Real remote-hosting smoke test of the Plan API: API on one machine, GUI/bot on another (only localhost verified so far).
3. See `TODO.md` for the full backlog.

**Working style preferences:**
- Communicate in Russian, code/commits in English
- No trailing summaries of what was just done — user can see the diff
- Commit and push after each logical unit of work
- When skipping a TODO item, explain why in one sentence
- Default language for bot strings and SBU drill labels: Russian (`language="ru"`)

---

## Development Setup

```bash
pip install -e ".[dev]"          # editable install with test/lint deps
pip install -e ".[garmin-calendar]"  # add Garmin Connect upload support
pip install -e ".[api]"          # add the Plan API (FastAPI+uvicorn) -- needed to run garmin-fit-api
pip install -e ".[build]"        # add PyInstaller -- needed to package the desktop GUI as .exe
```

## Common Commands

```bash
# Run all tests (251 passing as of the 2026-07-06 GUI session)
python3 -m pytest tests/

# Run a single test file
python3 -m pytest tests/test_build_from_plan.py

# Run a single test by name
python3 -m pytest tests/test_plan_validator.py -k test_repeat_back_to_offset

# Lint (tabs are the project style — E501/W19x are intentionally ignored)
ruff check src/

# Desktop GUI (recommended for local users) — Calendar / LLM Generator / Конструктор / Garmin Connect
python fitweaver_gui.py

# Full workflow
python -m garmin_fit.cli run

# Validate YAML plan
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml

# LLM generation (LM Studio or Ollama)
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1

# Interactive menu (loop-based, 14 options)
python -m garmin_fit.runner

# Telegram bot
python -m garmin_fit.bot
# or from Scripts/ (shim, also works):
python3 Scripts/telegram_bot.py
```

---

## Pipeline

```
text/md → LLM → YAML (Plan/) → direct FIT build → validation → archive
                                                 ↘ Garmin Calendar upload (optional)
                                                 ↘ ZIP via Telegram bot (optional)
```

---

## LLM model compatibility

**Recommended:** `qwen3-27b` (or any Qwen3) — natively supports `enable_thinking: false`.  
**Broken:** `google/gemma-4-e4b` — ignores `enable_thinking: false`, enters thinking mode on retry, hangs 3000+ sec.  
Config: `bot_config.yaml` → `llm_model`.

---

## Two build paths — BOTH must stay in sync

| Path | Script | Used by |
|------|--------|---------|
| **Direct** (default) | `src/garmin_fit/build_from_plan.py` | `workflow_full`, Telegram bot |
| **Legacy/debug** | `src/garmin_fit/generate_from_yaml.py` + `src/garmin_fit/build_fits.py` | `--templates-only` / `--build-only` |

When adding new step types or fixing step generation logic, update **both** builders.

The canonical `build_yaml_to_fit_index()` lives in `workout_utils.py` and is imported by `build_from_plan.py`. `generate_from_yaml.py` has its own dict-handling version (legacy path, raw dicts not domain objects).

---

## back_to_offset — CRITICAL

`back_to_offset` in YAML is always a **YAML-level step index** (0-based position in the `steps` list).
Both builders call `build_yaml_to_fit_index()` to translate it to the correct FIT runtime index at build time, accounting for `sbu_block` expansion.

**Never** put FIT runtime indices directly in YAML — the validator will reject them (`back_to_offset >= s_idx`).

The desktop GUI's "🧱 Конструктор" tab (visual workout builder, `workout_builder.py` + `plan_store.py`) is the recommended way to avoid hand-computing this value: select a range of blocks and click "Повторить ×N" — `back_to_offset` is computed from the selection, never typed.

Example (SBU + accelerations):
```yaml
steps:
  - type: dist_hr        # YAML 0 → FIT 0
  - type: sbu_block      # YAML 1 → FIT 1–16  (4 drills × 2 reps × 2 steps)
  - type: time_hr        # YAML 2 → FIT 17
  - type: time_step      # YAML 3 → FIT 18
  - type: repeat
    back_to_offset: 2    # ← YAML index 2, system computes FIT 17 automatically
    count: 4
```

---

## sbu_block expansion

Each drill expands to `reps × 2` FIT steps (active + open recovery).
- Default block (5 drills, 2 reps each) = 24 FIT steps
- 4 drills × 2 reps = 16 FIT steps
- 2 drills × 2 reps = 8 FIT steps (deload)

`DEFAULT_DRILLS` in `sbu_block.py` are in Russian. `garmin_step_mapper.py` uses `language="ru"` by default for recovery/fallback labels ("Отдых" / "Упражнение N"). The Telegram bot passes `_lang(user_id)` to `GarminCalendarExporter(language=...)`.

---

## Telegram bot

**State machine:** idle → generating → awaiting_sbu_choice → awaiting_clarification → awaiting_confirm → building → idle

**Session timeout:** `UserState.last_active`/`onboarded` fields; `_enforce_session()` resets via `reset_state()` and re-prompts `/start` if the user skipped onboarding or has been idle past `session_timeout_sec` (`bot_config.yaml`, default 1200s). Wired into `handle_text_message`; `handle_lang_choice` (the real `/start` flow) marks `onboarded=True`.

**Plan generation is now via the Plan API, not a direct LLM connection.** `_build_llm_client()` returns a `PlanApiClient` (`src/garmin_fit/api_client.py`) pointed at `bot_config.yaml`'s `plan_api_url`/`plan_api_token` — a running `garmin-fit-api` instance (see "Plan API" section below). The bot calls `llm.build_plan_draft(plan_text)` / `llm.apply_custom_sbu_choice(yaml_data, user_text)` directly on that client (not the module-level `plan_service` functions) so `plan_service.py`'s repair/validation logic runs exactly once, inside the API process — never duplicated in the bot. `PlanApiError` subclasses `RuntimeError`, so the bot's existing broad `except Exception` clauses catch it with no changes; a dedicated `api_unreachable` message covers the new "API process down/unreachable" failure mode distinct from `llm_no_connect` (which checks the LLM behind the API, not the API itself).

**Language:** stored in `UserState.language` ("ru" / "en"). Set via `/start` → inline keyboard. `_lang(user_id)` returns it. `_m(user_id, key)` looks up `MSG[lang][key]`.

**Running the bot:** `python -m garmin_fit.bot` from project root (needs a running `garmin-fit-api` instance — see below). The `Scripts/telegram_bot.py` shim also works (fixed — now calls `main()`).

---

## Plan API (`src/garmin_fit/api/`)

Thin FastAPI+uvicorn facade over `plan_service.py` — the one place `build_plan_draft`/
`apply_custom_sbu_choice` actually run. Both the Telegram bot and the GUI's "LLM автора" mode
are HTTP clients of this (`src/garmin_fit/api_client.py`'s `PlanApiClient`); the GUI's "Своя
LLM" mode still talks to `UnifiedLLMClient` directly and does not need this running.

**Setup:** `pip install -e ".[api]"`, `cp api_config.yaml.example api_config.yaml`, fill in
`api_token` (or set `FITWEAVER_API_TOKEN` env var instead) and `llm_url`/`llm_model`/
`llm_api_type`. Run with `garmin-fit-api` (or `python -m garmin_fit.api_cli` if the entry
point isn't on `PATH`).

**Endpoints:** `POST /v1/generate-draft`, `POST /v1/apply-sbu-choice`, `GET /v1/health` — all
require an `X-Api-Token` header matching `api_config.yaml`'s `api_token`. Rate-limited via an
in-memory token bucket (`rate_limit_per_minute`/`rate_limit_burst` in `api_config.yaml`),
keyed per token, state on `app.state` (not a module global — each `create_app()` call gets
isolated bucket state, this matters for tests).

**Security note:** never expose the raw LLM server (`llm_url`) directly to the internet —
always go through this API, which is what the auth token and rate limiter protect. This is
mandatory, not optional, if the API's port is ever reachable from outside localhost.

---

## Desktop packaging (.exe)

GUI-only (not the bot or Plan API — those stay Python-run services). `packaging/` has:
`cli_entry.py` (wraps `garmin_fit.cli:main` for a second exe), `fitweaver_gui.spec` /
`fitweaver_cli.spec` (two separate PyInstaller spec files — deliberately not two
`Analysis`/`PYZ` blocks in one spec, see the docstring in `fitweaver_gui.spec` for why that
silently corrupts one of the two onefile exes), and `build.ps1`.

**Build:** `powershell packaging/build.ps1` (or manually: `pip install -e
".[garmin-calendar,build]"`, then build from an isolated staging copy — see below — with
`pyinstaller packaging/fitweaver_gui.spec` and `pyinstaller packaging/fitweaver_cli.spec`).
Produces `dist/FitWeaver.exe` + `dist/garmin-fit-cli.exe`, which **must ship together in the
same folder** — the GUI shells out to the CLI exe as a sibling process for every sidebar
action ("Собрать FIT-файлы", Garmin upload/delete, the whole "ПРОДВИНУТЫЕ" section), since a
frozen exe can't be re-run with `-m` like a real Python interpreter (`_cli_command()` in
`fitweaver_gui.py` branches on `getattr(sys, "frozen", False)`).

**Portable folder, not `%APPDATA%`:** writable state (`Plan/`, `profiles/`,
`.gui_session.json`, `Output_fit/`, `Archive/`) resolves from `sys.executable`'s parent
directory when frozen (`config.py`'s `PROJECT_ROOT`, `fitweaver_gui.py`'s own `PROJECT_ROOT`)
— stable across onefile's per-launch temp extraction, and matches the existing
"run-from-a-git-checkout" mental model users already have.

**Why the build must happen from an isolated staging copy, not the live source tree:** the
repo root also has a `garmin_fit/` compatibility bridge package (see Architecture below) that
contains only `__init__.py` + an empty `llm/` dir and extends its `__path__` to
`src/garmin_fit` via `__path__.append(...)` — but only at real runtime. PyInstaller
auto-adds the main script's own directory (the repo root, since `fitweaver_gui.py` lives
there) to its search path, and when resolving the *lazily* imported `garmin_fit` submodules
that make up almost all of `fitweaver_gui.py`'s own imports (inside method bodies, not at
module level), its static analysis doesn't execute `__init__.py` and so never sees the
appended path — it silently resolves against the near-empty bridge directory instead,
dropping modules like `plan_store`/`workout_builder` from the frozen build with **no
build-time error or warning**. `build.ps1` copies `src/`, `fitweaver_gui.py`, and
`packaging/` into `build/stage/` (no root-level `garmin_fit/` present there at all) and
builds from there instead, removing the ambiguity entirely.

Out of scope for now: packaging the bot/API as exes, a real installer (Inno
Setup/NSIS)/code signing, auto-update.

---

## Garmin Calendar localization

`GarminCalendarExporter(client, language="ru")` — language flows to `map_workout()` → `map_steps()` → `_map_sbu_block()`. Recovery step label and unnamed drill fallback are localized. Bot passes user language automatically.

---

## Week numbering

ISO weeks (Monday start): `date.isocalendar()[1]`  
Filename pattern: `W{iso_week}_{MM-DD}_{Day}_{Type}_{Details}`

---

## Architecture (src/garmin_fit is canonical)

```
src/garmin_fit/   ← canonical source — ALL edits go here
garmin_fit/       ← alias bridge layer — DO NOT edit directly
Scripts/          ← compatibility shims — DO NOT edit directly
```

Key modules:
- `config.py` — paths; `GARMIN_FIT_RUNTIME_DIR` env var overrides `RUNTIME_ROOT`
- `cli.py` / `legacy_cli.py` / `validate_cli.py` / `runtime_cli.py` — CLI entry points
- `_shared_cli.py` — `configure_logging()`, `generate_run_id()`
- `plan_schema.py` — Pydantic v2 schema; `_is_valid_pace()`, `_pace_to_seconds()`, `_check_pace_ordering()` are shared with `plan_validator.py`
- `plan_validator.py` — semantic validation (imports helpers from `plan_schema.py`)
- `plan_domain.py` — domain objects (`WorkoutStep`, `Workout`, `WorkoutPlan`, `Drill`); logs warnings on dropped non-Mapping items
- `plan_processing.py` — YAML repair, name normalization
- `plan_service.py` — service layer (LLM draft, SBU custom drills, preview)
- `workout_utils.py` — FIT step builders + canonical `build_yaml_to_fit_index()`
- `build_from_plan.py` — direct YAML→FIT builder (default path)
- `generate_from_yaml.py` — legacy template-based builder (debug path)
- `sbu_block.py` — SBU FIT step generator; `DEFAULT_DRILLS` in Russian
- `garmin_step_mapper.py` — maps domain objects to Garmin Calendar API payloads; `map_workout(workout, language="ru")`
- `garmin_calendar_export.py` — `GarminCalendarExporter(client, language="ru")`; upload/schedule/delete
- `garmin_auth_manager.py` — token caching for Garmin Connect auth
- `logging_utils.py` — `setup_file_logging()` guards against duplicate FileHandler
- `pipeline_runner.py` — wrapper used by `telegram_bot.py`; do not remove (it's imported)
- `runner.py` — interactive menu, 14 options, loop-based
- `bot.py` / `telegram_bot.py` — Telegram bot entry point and async state machine
- `llm/request_cli.py` — LLM generation CLI; `--workouts N` overrides expected count
- `llm/benchmark.py` — LLM quality benchmark; `DEFAULT_SUITE` uses `PROJECT_ROOT`
- `check_fit.py` — FIT file validator; large file threshold in `_LARGE_FILE_BYTES`
- `plan_store.py` — SQLite staging layer for the desktop GUI only; YAML stays canonical everywhere else. `PlanStore` writes back to the loaded YAML file after every mutation
- `profile_store.py` — per-user (email-keyed) GUI state: plan session, personal HR profile, onboarding/legacy-migration; reuses the same email slug as `workflow._resolve_garmin_token_dir`
- `workout_builder.py` — pure-Python support for the GUI's visual workout builder (no Tkinter/SQLite): `BLOCK_DEFS`, `TEMPLATES`, `compute_repeat_step()`, `validate_draft()`
- `api/` — FastAPI facade over `plan_service.py` (`app.py`/`auth.py`/`rate_limit.py`/`schemas.py`/`config.py`); `api_cli.py` is the `garmin-fit-api` entry point
- `api_client.py` — `PlanApiClient`/`PlanApiError`, the shared HTTP client the bot and the GUI's "LLM автора" mode both use to reach `api/`

`packaging/` (repo root, not under `src/garmin_fit/`) — PyInstaller packaging for the desktop
GUI: `cli_entry.py`, `fitweaver_gui.spec`/`fitweaver_cli.spec`, `build.ps1`. See "Desktop
packaging (.exe)" above.

---

## JSON Schema (Pydantic)

`WorkoutPlanSchema.model_json_schema()` generates machine-readable schema for all step types.
Use `get_plan_json_schema()` from `garmin_fit.llm.prompt` for external tools.
Compact version injected into prompt with `get_system_prompt(include_json_schema=True)`.

---

## LLM workout count detection

`normalize_source_text()` auto-detects expected workout count:
1. Dated headers (`12.03`, `12.03.2026`) or numbered headers (`Тренировка N`)
2. Phase-structured plans (`## ФАЗА N (недели A–B)` + `### DayName` sections)
3. If both fail → interactive prompt or `--workouts N` CLI flag

---

## Docs

- `docs/YAML_GUIDE.md` — full YAML reference
- `docs/CHANGELOG.md` — version history
- `docs/PROJECT_FLOW.md` — pipeline details
- `docs/TELEGRAM_SETUP.md` — bot setup and troubleshooting
- `docs/GARMIN_CALENDAR.md` — Garmin Connect Calendar upload guide
