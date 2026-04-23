# TODO — FitWeaver

_Обновлено: 2026-04-20_

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
