# TODO — FitWeaver

_Обновлено: 2026-04-23_

---

## ✅ Закрыто 2026-04-20

### Retry-цикл → thinking mode
- `source_fact_mismatch` теперь демотируется после `_apply_source_fact_consistency_checks()`.
- Cooldown с одним HR-порогом (`до 130`) чинится в repair-слое: `hr_low = 80`.
- Добавлены тесты.

### Telegram UX / надёжность
- Стейл кнопки доставки после рестарта проверяют наличие ZIP.
- `/cancel` во время `generating` ставит флаг, бот останавливается после ответа LLM.
- `reset_state()` удаляет `pending_zip_path`.
- После Garmin-загрузки бот сразу переотправляет клавиатуру если ZIP жив.
- `/send_to_garmin` статус корректно зависит от `path.exists()`.
- Убран мёртвый i18n ключ `delivery_choice_busy`.

### Preview YAML
- YAML превью теперь 3 отдельных сообщения: статус / YAML / footer.
  YAML легко копируется в Telegram.

### Документация
- `docs/TELEGRAM_SETUP.md`, `docs/CHANGELOG.md` обновлены.

---

## ⚠️ Важно: совместимость моделей

### Gemma 4 несовместима с `enable_thinking: false`
`google/gemma-4-e4b` полностью игнорирует параметр `enable_thinking: false`.
При повторной попытке (retry) модель входит в режим размышлений (thinking mode)
и тратит 3000+ секунд вместо ответа.

**Решение:** использовать `qwen3.5-0.8b` или `qwen3.5-4b` в `bot_config.yaml`:
```yaml
llm_model: "qwen3.5-0.8b"
```
`enable_thinking: false` нативно поддерживается Qwen3.

---

## 🔴 Критические (влияют на корректность)

### ~~1. Дублирование `_build_yaml_to_fit_index()` в двух билдерах~~ ✅ FIXED
`build_from_plan.py` и `generate_from_yaml.py` содержат почти идентичные реализации.
CLAUDE.md предупреждает "BOTH must stay in sync" — это значит, что они разойдутся.
**Решение:** вынести в `workout_utils.py`.

### ~~2. `garmin_calendar_export.py`: тихий сбой при парсинге дат~~ ✅ FIXED
`_parse_date()` возвращает `None` на `ValueError`, а `_date_in_range()` трактует `None` как "всегда включать".
Воркаут с нечитаемой датой в имени файла попадёт в любой диапазон без предупреждения.

### ~~3. `logging_utils.py`: дублирование log handler-ов~~ ✅ FIXED
`setup_file_logging()` вызывает `addHandler()` на root logger без проверки на уже добавленный handler.
При повторном вызове в рамках одного процесса все логи пишутся дважды.

### ~~4. Дублирование валидации pace между модулями~~ ✅ FIXED
`_validate_pace()` в `plan_validator.py` и `_is_valid_pace()` в `plan_schema.py` делают одно и то же.
**Решение:** единый `_is_valid_pace()` в `plan_schema.py`, импортируется оттуда.

---

## 🟡 Важные (качество кода и надёжность)

### ~~5. `plan_schema.py`: нет верхней границы для HR~~ ✅ FIXED
`hr_high: int = Field(gt=0)` — Pydantic пропустит `hr_high=500`.
**Решение:** добавить `le=250` на все HR-поля.

### ~~6. `plan_domain.py`: тихое удаление данных~~ ✅ FIXED
`step_from_data()` и `workout_from_data()` молча выбрасывают не-dict элементы из списков без логирования.
При повреждённом YAML пользователь не узнает, что часть тренировок потеряна.

### ~~7. `build_from_plan.py`: нет отката при частичном сбое FIT~~ ✅ FIXED
~~Если FIT-генерация упала на тренировке N, тренировки 1..N-1 остаются в `Output_fit/`.~~
Финальный лог теперь перечисляет имена упавших тренировок и предупреждает о частичных результатах в Output_fit.

### 8. `sbu_block.py`: DEFAULT_DRILLS захардкожены в коде
Пять дефолтных упражнений СБУ вшиты прямо в Python.
**Решение:** вынести в `llm_contract.yaml` или отдельный конфиг-файл рядом с `sbu_block.py`.

### 9. `pipeline_runner.py` — лишняя обёртка
Содержит одну функцию, которая просто вызывает `run_generation_pipeline()` с фиксированными аргументами.
Все вызывающие могут обращаться напрямую к `orchestrator`.

---

## 🔵 Тесты (важные пробелы)

### 10. Error paths почти не тестируются
Все тесты — happy path. Нет тестов для:
- невалидный YAML → `load_plan_build_input()`
- сетевая ошибка → `garmin_calendar_export`
- ошибка записи файла → `build_from_plan`

### 11. Вложенные repeat не тестируются
`test_garmin_step_mapper.py` покрывает обычные repeat и SBU, но нет теста для `repeat внутри repeat`.

### ~~12. `test_config.py`: побочные эффекты между тестами~~ ✅ FIXED
~~`importlib.reload()` меняет глобальное состояние модуля.~~
Исправлено через `setUp`/`tearDown` с гарантированным `reload` и `os.environ.pop`.

---

## ⚪ Мелкие

- ~~`plan_schema.py`: `check_pace_ordering()` продублирована в `DistPaceStep` и `TimePaceStep` — вынести в `@staticmethod`.~~ ✅ FIXED
- `garmin_auth_manager.py`: `prompt_mfa` — блокирующий вызов без таймаута, CLI может зависнуть.
- ~~`llm/benchmark.py`: путь до фикстур захардкожен — сломается при перемещении `tests/`.~~ ✅ FIXED
- ~~`check_fit.py`: порог предупреждения о размере файла (1 МБ) захардкожен.~~ ✅ FIXED (вынесен в `_LARGE_FILE_BYTES`)

---

## 🟢 Оставшиеся улучшения

### 1. Показывать прогресс во время долгой генерации
Бот молчит 3–12 минут. Нужно: периодически слать «ещё генерирую...»
(`send_chat_action` typing каждые 4 сек, или явное сообщение каждые 60 сек).

### 2. Разрешить отправку плана по частям
Большой план (10+ тренировок) → 8–12 минут. Предупреждение «большой план, ожидайте ~N минут».

### 3. /status показывает технические детали
Сделать human-friendly вариант вывода.

### 4. SBU standard preview без repairs/warnings
В пути "стандарт" `state.yaml_text` показывается без блоков Auto-repair / Warnings.
Фикс: хранить `draft` в `state.pending_draft: Optional[GeneratedYamlResult]`.
Низкий приоритет — пользователь уже видел полное превью до вопроса про СБУ.

### 5. Тест: retry-цикл интеграционный
Подать план с "до 130 уд/мин", убедиться что retry не срабатывает и YAML валиден.
