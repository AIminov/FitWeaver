# Гайд по YAML-формату тренировок

Справочник по созданию YAML-файлов тренировочных планов для генерации FIT-файлов Garmin.

---

## Основные концепции

### Что такое YAML файл тренировки?

Это структурированное описание тренировочного плана, которое система преобразует в файлы для Garmin.

```yaml
workouts:
  - filename: W07_02-18_Wed_Easy_Run
    name: W07_02-18_Wed_Easy_Run
    desc: "Easy 10km run"
    type_code: easy
    distance_km: 10.0
    estimated_duration_min: 60
    steps:
      - type: dist_hr
        km: 10.0
        hr_low: 130
        hr_high: 145
```

### Основная структура

```
workouts:                      # <- Корневой элемент (обязателен)
  - filename: ...             # <- Имя файла (должно быть уникальным)
    name: ...                 # <- Название тренировки
    desc: "..."              # <- Описание
    type_code: ...           # <- Тип тренировки
    distance_km: ...         # <- Общее расстояние
    estimated_duration_min: ... # <- Примерное время (минут)
    steps:                   # <- Список шагов тренировки
      - type: ...            # <- Тип шага
        ...                  # <- Параметры шага
```

---

## Все типы шагов

### 1. `dist_hr` -- По расстоянию в пульсовой зоне

**Используй для:** Аэробные и восстановительные тренировки на основе пульса

```yaml
- type: dist_hr
  km: 5.0
  hr_low: 145
  hr_high: 152
  intensity: active  # optional
```

**Параметры:**
- `km` -- расстояние (число)
- `hr_low` -- минимальный пульс (число)
- `hr_high` -- максимальный пульс (число)
- `intensity` -- [optional] warmup, active, cooldown, recovery

**Пример:**
```yaml
- type: dist_hr
  km: 10.0
  hr_low: 145
  hr_high: 152
```

---

### 2. `time_hr` -- По времени в пульсовой зоне

**Используй для:** Временные отрезки (интервалы, ускорения)

```yaml
- type: time_hr
  seconds: 300  # 5 минут
  hr_low: 175
  hr_high: 185
  intensity: active
```

**Параметры:**
- `seconds` -- время в секундах
- `hr_low` / `hr_high` -- пульсовая зона
- `intensity` -- [optional]

**Пример:**
```yaml
- type: time_hr
  seconds: 20    # 20 секунд
  hr_low: 175
  hr_high: 185
- type: time_hr
  seconds: 60    # 60 секунд восстановление
  hr_low: 130
  hr_high: 145
  intensity: recovery
```

---

## HR-форматы

Для шагов `dist_hr` и `time_hr` всегда нужна полноценная зона:

```yaml
- type: dist_hr
  km: 6.0
  hr_low: 130
  hr_high: 145
```

Правила:
- `hr_low` и `hr_high` должны быть числами;
- `hr_low` должен быть меньше `hr_high`;
- валидный диапазон: `30 <= hr_low < hr_high <= 240`;
- одиночная запись вроде `до 130 уд/мин`, `HR <= 130` или `не выше 130`
  достраивается как диапазон `80-130`.

Если в исходном текстовом плане указан только верхний порог:

```text
заминка 2 км (до 130)
```

то YAML должен быть:

```yaml
- type: dist_hr
  km: 2.0
  hr_low: 80
  hr_high: 130
  intensity: cooldown
```

Можно также явно задать другой диапазон, если он важен:

```text
заминка 2 км, пульс 115-130
```

LLM-промпт просит модель превращать одиночный верхний HR-порог в `80-<порог>`.
Repair-слой также исправляет типичный cooldown-ответ `hr_low: null` или
`hr_low >= hr_high`, чтобы такой шаг не вызывал retry.

---

### 3. `dist_pace` -- По расстоянию с темпом

**Используй для:** Темповые работы, интервалы (если работаешь по темпу, а не по пульсу)

```yaml
- type: dist_pace
  km: 5.0
  pace_fast: "4:50"
  pace_slow: "5:00"
  intensity: active
```

**Параметры:**
- `km` -- расстояние
- `pace_fast` -- быстрый темп в формате "MM:SS"
- `pace_slow` -- медленный темп в формате "MM:SS"
- `intensity` -- [optional]

**ВАЖНО:** Не смешивай `dist_pace` с `hr_low`/`hr_high`!

**Пример:**
```yaml
- type: dist_pace
  km: 1.0
  pace_fast: "4:20"
  pace_slow: "4:30"
```

---

### 4. `time_pace` -- По времени с темпом

**Используй для:** Временные интервалы с контролем по темпу

```yaml
- type: time_pace
  seconds: 120    # 2 минуты
  pace_fast: "4:30"
  pace_slow: "4:50"
  intensity: active
```

**Параметры:** то же, что `time_hr`, но с `pace_fast`/`pace_slow`

---

### 5. `dist_open` -- По расстоянию свободный темп

**Используй для:** Разминка, заминка, восстановление (без точных параметров)

```yaml
- type: dist_open
  km: 2.0
  intensity: warmup
```

**Параметры:**
- `km` -- расстояние
- `intensity` -- warmup, active, cooldown, recovery

---

### 6. `time_step` -- По времени с интенсивностью

**Используй для:** Временные отрезки без пульса/темпа

```yaml
- type: time_step
  seconds: 300
  intensity: recovery
```

---

### 7. `sbu_block` -- Специальные беговые упражнения (Running Drills)

> **СБУ** (Специальные Беговые Упражнения) — это набор упражнений для развития беговой техники.
> В англоязычной терминологии: **running drills** или **form drills**.
> Типичные упражнения: High Knees (высокое бедро), Butt Kicks (захлёст), Straight-Leg Run (прямые ноги), Bounding (многоскоки), A-Skip, B-Skip и др.

**Используй для:** Техничные упражнения (high knees, bounding, skipping и т.д.)

```yaml
- type: sbu_block
  drills:
    - name: "High Knees"
      seconds: 30
      reps: 2
    - name: "Bounding"
      seconds: 30
      reps: 2
    - name: "Skipping"
      seconds: 30
      reps: 2
```

**Параметры:**
- `drills` -- список упражнений
- `name` -- название упражнения (не более 12 символов для Garmin!)
- `seconds` -- длительность упражнения
- `reps` -- количество повторений

**ВАЖНО:** Имя упражнения не должно быть длиннее 12 символов!
- "High Knees" (11) -- OK
- "Straight Lg" (11) -- OK
- "Straight Legs" (13) -- слишком длинное!

Стандартный `sbu_block` без параметров использует набор по умолчанию:

```yaml
- type: sbu_block
```

---

### 8. `repeat` -- Повторить предыдущие шаги

**Используй для:** Интервалов и повторений

```yaml
- type: dist_pace
  km: 1.0
  pace_fast: "4:20"
  pace_slow: "4:30"
- type: dist_open
  km: 0.4
  intensity: recovery
- type: repeat
  back_to_offset: 0  # Повтори шаги начиная с индекса 0
  count: 5           # 5 повторений
```

**Параметры:**
- `back_to_offset` -- индекс шага в YAML-списке `steps` (0-based), с которого начинать повтор
- `count` -- количество повторений

**ВАЖНО:** `back_to_offset` — это YAML-индекс, не FIT runtime-индекс. Система автоматически переводит его в нужный FIT-индекс при сборке, в том числе при наличии `sbu_block` (который разворачивается в несколько FIT-шагов).

**Пример СБУ + ускорения:**
```yaml
steps:
  - type: dist_hr        # YAML индекс 0: разминка
    km: 2.0
    hr_low: 125
    hr_high: 142
    intensity: warmup
  - type: sbu_block      # YAML индекс 1: разворачивается в 16 FIT-шагов
    drills: [...]
  - type: time_hr        # YAML индекс 2: ускорение (FIT индекс 17)
    seconds: 30
    hr_low: 155
    hr_high: 168
  - type: time_step      # YAML индекс 3: восстановление (FIT индекс 18)
    seconds: 90
    intensity: recovery
  - type: repeat         # YAML индекс 4
    back_to_offset: 2    # <- указывает на YAML шаг 2 (ускорение), система сама вычислит FIT индекс 17
    count: 4
```

**Пример 5x800м:**
```yaml
steps:
  - type: dist_open
    km: 2.0
    intensity: warmup          # Индекс 0
  - type: dist_pace
    km: 0.8
    pace_fast: "4:10"
    pace_slow: "4:20"          # Индекс 1
  - type: dist_open
    km: 0.4
    intensity: recovery        # Индекс 2
  - type: repeat
    back_to_offset: 1          # Повтори с шага 1 (dist_pace)
    count: 5                   # 5 раз
  - type: dist_open
    km: 1.0
    intensity: cooldown
```

---

## Примеры реальных тренировок

### Пример 1: Аэробный бег (7 км)

**Используй для:** Основные аэробные тренировки, когда контролируешь пульс

```yaml
- filename: W06_02-10_Tue_Aerobic_7km
  name: W06_02-10_Tue_Aerobic_7km
  desc: "Transition aerobic run"
  type_code: aerobic
  distance_km: 7.0
  estimated_duration_min: 40
  steps:
    - type: dist_hr
      km: 7.0
      hr_low: 145
      hr_high: 158
```

---

### Пример 2: Интервалы 6x800м

**Используй для:** Скоростные интервалы с повторениями

```yaml
- filename: W08_02-20_Thu_Intervals_6x800
  name: W08_02-20_Thu_Intervals_6x800
  desc: "6x800m intervals"
  type_code: intervals
  distance_km: 10.0
  estimated_duration_min: 55
  steps:
    - type: dist_open
      km: 2.0
      intensity: warmup
    - type: dist_hr
      km: 0.8
      hr_low: 175
      hr_high: 185
      intensity: active
    - type: dist_hr
      km: 0.4
      hr_low: 130
      hr_high: 145
      intensity: recovery
    - type: repeat
      back_to_offset: 1
      count: 6
    - type: dist_hr
      km: 1.0
      hr_low: 130
      hr_high: 145
      intensity: cooldown
```

---

### Пример 3: СБУ + Заминка

**Используй для:** Техничные тренировки со специальными упражнениями

```yaml
- filename: W06_02-13_Fri_SBU_3_2km
  name: W06_02-13_Fri_SBU_3_2km
  desc: "Warmup + SBU + cooldown"
  type_code: easy_drills
  distance_km: 5.0
  estimated_duration_min: 50
  steps:
    - type: dist_hr
      km: 3.0
      hr_low: 130
      hr_high: 145
      intensity: warmup
    - type: sbu_block
    - type: dist_hr
      km: 2.0
      hr_low: 130
      hr_high: 145
      intensity: cooldown
```

---

### Пример 4: Длинный бег (20 км)

```yaml
- filename: W14_04-04_Sat_Long_20km
  name: W14_04-04_Sat_Long_20km
  desc: "Peak long run 20km, HR 145-152"
  type_code: long
  distance_km: 20.0
  estimated_duration_min: 120
  steps:
    - type: dist_hr
      km: 20.0
      hr_low: 145
      hr_high: 152
      intensity: active
```

---

## Чек-лист для валидации YAML

Перед запуском генератора проверьте:

- [ ] **Все тренировки в блоке `workouts:`** -- каждая начинается с `-`

- [ ] **Обязательные поля для каждой тренировки:**
  - `filename` -- уникальное имя (без пробелов, используй подчеркивание)
  - `name` -- название
  - `desc` -- описание
  - `type_code` -- тип (easy, aerobic, intervals, long, easy_drills и т.д.)
  - `distance_km` -- расстояние (число)
  - `estimated_duration_min` -- время в минутах (число)
  - `steps` -- массив шагов

- [ ] **Каждый шаг имеет требуемые поля:**
  - `type: dist_hr` -> `km`, `hr_low`, `hr_high`
  - `type: time_hr` -> `seconds`, `hr_low`, `hr_high`
  - `type: dist_pace` -> `km`, `pace_fast`, `pace_slow`
  - `type: dist_open` -> `km`, `intensity`
  - `type: sbu_block` -> `drills` опционально (если указаны, то с `name`, `seconds`, `reps`)
  - `type: repeat` -> `back_to_offset`, `count`

- [ ] **Формат пульса и темпа:**
  - Пульс: диапазон с двумя числами (`hr_low < hr_high`), например 130–145
  - Одиночный верхний порог (`до 130`) записывайте как `80–130`
  - Темп: строки в формате "MM:SS" ("4:50", "5:10")

- [ ] **Валидные значения intensity:**
  - `warmup` / `cooldown` / `active` / `recovery`

- [ ] **Имена упражнений:** не длиннее 12 символов

- [ ] **YAML синтаксис:** отступы = 2 пробела (не табуляция)

---

## Частые ошибки и как их избежать

### Ошибка 1: Смешивание пульса и темпа в одном шаге

```yaml
# НЕПРАВИЛЬНО (смешиваешь два подхода):
- type: dist_pace
  km: 5.0
  pace_fast: "4:50"
  pace_slow: "5:00"
  hr_low: 145      # <- Не смешивай пульс с темпом!
  hr_high: 152

# ПРАВИЛЬНО (один подход):
- type: dist_pace
  km: 5.0
  pace_fast: "4:50"
  pace_slow: "5:00"

# ИЛИ (другой подход):
- type: dist_hr
  km: 5.0
  hr_low: 145
  hr_high: 152
```

**Главное правило:** Выбирай ИЛИ пульс (`hr_low`/`hr_high`), ИЛИ темп (`pace_fast`/`pace_slow`), но не оба вместе!

---

### Ошибка 2: Неправильный формат темпа

```yaml
# НЕПРАВИЛЬНО:
pace_fast: 4:50      # <- Должны быть кавычки!
pace_slow: 5:00

# ПРАВИЛЬНО:
pace_fast: "4:50"
pace_slow: "5:00"
```

---

### Ошибка 3: Слишком длинные имена упражнений

```yaml
# НЕПРАВИЛЬНО:
- name: "Straight Legs"      # 13 символов

# ПРАВИЛЬНО:
- name: "Straight Lg"        # 11 символов
```

---

### Ошибка 4: back_to_offset указывает за границы

```yaml
# НЕПРАВИЛЬНО:
steps:
  - type: dist_open         # Индекс 0
    km: 2.0
  - type: repeat
    back_to_offset: 5       # <- Не существует!
    count: 6

# ПРАВИЛЬНО:
steps:
  - type: dist_open         # Индекс 0
    km: 2.0
  - type: dist_pace         # Индекс 1
    km: 0.8
    pace_fast: "4:20"
    pace_slow: "4:30"
  - type: dist_open         # Индекс 2
    km: 0.4
  - type: repeat
    back_to_offset: 1       # <- Существует!
    count: 5
```

---

## Лучшие практики

### 1. Выбирай между `dist_hr` и `dist_pace` в зависимости от подхода

**`dist_hr` -- если тренируешься по пульсу:**
```yaml
- type: dist_hr
  km: 10.0
  hr_low: 145
  hr_high: 158
```

**`dist_pace` -- если тренируешься по темпу:**
```yaml
- type: dist_pace
  km: 10.0
  pace_fast: "5:50"
  pace_slow: "6:10"
```

Оба подхода валидны. Выбирай то, что соответствует твоему плану.

### 2. Не добавляй лишние поля вне схемы

```yaml
- filename: W07_02-18_Tue_Aerobic_7km
  ...
  desc: "Aerobic run in HR 145-158 zone"
```

### 3. Пустой `sbu_block` -- это нормально

```yaml
# Стандартный подход (всегда работает):
- type: sbu_block

# Специализированный (используй редко):
- type: sbu_block
  drills:
    - name: "High Knees"
      seconds: 30
      reps: 2
```

### 4. Организуй план по неделям

```yaml
workouts:
# ========== НЕДЕЛЯ 1: БАЗОВАЯ ФАЗА (17-23 февраля) ==========
- filename: W01_02-17_Mon_...
  ...

# ========== НЕДЕЛЯ 2: РАЗВИВАЮЩАЯ ФАЗА (24-2 марта) ==========
- filename: W02_02-24_Mon_...
  ...
```

### 5. `dist_open` только для разминки/заминки

```yaml
# ПРАВИЛЬНО (нет пульса, просто бег):
- type: dist_open
  km: 2.0
  intensity: warmup
```

---

## Шпаргалка

### Основные типы шагов:

| Тип | Когда использовать | Пример |
|-----|---|---|
| **`dist_hr`** | Расстояние по **пульсу** | `km: 5.0, hr_low: 145, hr_high: 152` |
| **`dist_pace`** | Расстояние по **темпу** | `km: 5.0, pace_fast: "5:50", pace_slow: "6:10"` |
| `time_hr` | Время по пульсу | `seconds: 300, hr_low: 175, hr_high: 185` |
| `time_pace` | Время по темпу | `seconds: 300, pace_fast: "4:30", pace_slow: "4:50"` |
| `dist_open` | Разминка/заминка | `km: 2.0, intensity: warmup` |
| `sbu_block` | Спец. упражнения | (обычно без параметров) |
| `repeat` | Повторить шаги | `back_to_offset: 1, count: 6` |

### Валидные intensity значения:

```
warmup      -- Разминка
cooldown    -- Заминка
active      -- Активная работа
recovery    -- Восстановление
```

### Структура имени файла (рекомендуется):

```
W[неделя]_[дата]_[день]_[тип]_[описание]

Номер недели = ISO-неделя (понедельник — первый день, воскресенье — последний).
Python: date.isocalendar()[1]

Примеры:
- W07_02-18_Wed_Aerobic_7km
- W08_02-25_Wed_Intervals_6x800
- W12_03-18_Wed_Aerobic_SBU_10km  (18 марта 2026 = ISO неделя 12)
```

### Частые пульсовые зоны:

```
130-145 bpm  -- Восстановление, разминка
145-158 bpm  -- Аэробная зона (основная)
165-172 bpm  -- Пороговая зона (темповая)
175-185 bpm  -- Интервалы (VO2max)
```

---

## Дополнительные ресурсы

- `Scripts/llm/llm_contract.yaml` -- strict контракт генерации YAML
- `Scripts/llm/strict_examples.yaml` -- набор компактных few-shot примеров
- `docs/LLM_CONNECTION_PROFILE.md` -- параметры подключения к локальной модели
