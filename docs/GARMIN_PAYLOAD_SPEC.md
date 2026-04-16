# Garmin Connect Workout-Service API — Payload Specification

> Reverse-engineered from `garminconnect` (cyberjunky) and `garmin-workouts` (mkuthan).
> Endpoint: `POST /proxy/workout-service/workout`

---

## Top-level workout object

```json
{
  "workoutName": "W11_03-14_Sat_Long_14km",
  "estimatedDurationInSecs": 3600,
  "description": "optional",
  "sportType": {
    "sportTypeId": 1,
    "sportTypeKey": "running",
    "displayOrder": 1
  },
  "author": {},
  "workoutSegments": [
    {
      "segmentOrder": 1,
      "sportType": { "sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1 },
      "workoutSteps": [ /* ExecutableStepDTO | RepeatGroupDTO */ ]
    }
  ]
}
```

**Sport type IDs:** 1=running, 2=cycling, 3=swimming, 4=walking, 7=hiking

**Omit on upload:** `workoutId`, `ownerId`, `stepId`, `createdDate`, `updatedDate`

---

## ExecutableStepDTO

```json
{
  "type": "ExecutableStepDTO",
  "stepOrder": 1,
  "stepType": {
    "stepTypeId": 1,
    "stepTypeKey": "warmup",
    "displayOrder": 1
  },
  "endCondition": {
    "conditionTypeId": 2,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": true
  },
  "endConditionValue": 300.0,
  "targetType": {
    "workoutTargetTypeId": 4,
    "workoutTargetTypeKey": "heart.rate.zone",
    "displayOrder": 4
  },
  "targetValueLow": 130,
  "targetValueHigh": 145
}
```

### stepType IDs

| stepTypeId | stepTypeKey | Used for |
|-----------|-------------|----------|
| 1 | warmup | разминка |
| 2 | cooldown | заминка |
| 3 | interval | рабочий шаг |
| 4 | recovery | восстановление |
| 5 | rest | пауза |
| 6 | repeat | (только в RepeatGroupDTO) |

### endCondition IDs

| conditionTypeId | conditionTypeKey | endConditionValue |
|----------------|-----------------|-------------------|
| 1 | **lap.button** | null — шаг до нажатия Lap |
| 2 | time | секунды (float), напр. 300.0 = 5 мин |
| 3 | distance | метры (float), напр. 1000.0 = 1 км |
| 7 | iterations | кол-во повторов (float) — только в RepeatGroupDTO |

> ⚠️ **conditionTypeId=1 это lap.button, НЕ distance!** Ошибка в ранней версии приводила к отображению всех шагов как "Нажатие кнопки Lap".

> `open_step` (до нажатия lap) — **не поддерживается** REST API. Замена: `time` 60.0 сек.

### targetType IDs

| workoutTargetTypeId | workoutTargetTypeKey | targetValueLow / targetValueHigh |
|--------------------|---------------------|----------------------------------|
| 1 | no.target | — (поля отсутствуют) |
| 4 | heart.rate.zone | номер зоны Garmin (1–5) — **НЕ bpm** |
| 5 | speed.zone | номер зоны скорости — **НЕ м/с** |
| 6 | **heart.rate** | raw bpm: 130 / 145 ← используем |
| 7 | **speed** | м/с: 1000/pace_seconds ← используем |

> ⚠️ `heart.rate.zone` (id=4) и `speed.zone` (id=5) — зонные таргеты Garmin, требуют номер зоны.
> Для кастомных диапазонов BPM/м/с нужны `heart.rate` (id=6) и `speed` (id=7).

### Конвертация темпа (pace → speed)

```python
# "5:00" → 1000 / 300 = 3.333 м/с (это targetValueHigh — быстрый темп = высокая скорость)
# "5:30" → 1000 / 330 = 3.030 м/с (это targetValueLow  — медленный темп = низкая скорость)

def pace_to_mps(pace_str: str) -> float:
    m, s = pace_str.split(":")
    return round(1000.0 / (int(m) * 60 + int(s)), 4)

# pace_fast (быстрее) → targetValueHigh
# pace_slow (медленнее) → targetValueLow
```

---

## RepeatGroupDTO

```json
{
  "type": "RepeatGroupDTO",
  "stepOrder": 2,
  "stepType": {
    "stepTypeId": 6,
    "stepTypeKey": "repeat",
    "displayOrder": 6
  },
  "numberOfIterations": 6,
  "endCondition": {
    "conditionTypeId": 7,
    "conditionTypeKey": "iterations",
    "displayOrder": 7,
    "displayable": false
  },
  "endConditionValue": 6.0,
  "smartRepeat": false,
  "workoutSteps": [
    /* ExecutableStepDTO objects — stepOrder is relative within the group */
  ]
}
```

**Важно:** `endConditionValue` должен совпадать с `numberOfIterations` как float.

---

## Полный пример: интервальная тренировка

```json
{
  "workoutName": "Threshold 4x1km",
  "estimatedDurationInSecs": 3000,
  "sportType": { "sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1 },
  "author": {},
  "workoutSegments": [{
    "segmentOrder": 1,
    "sportType": { "sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1 },
    "workoutSteps": [
      {
        "type": "ExecutableStepDTO",
        "stepOrder": 1,
        "stepType": { "stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1 },
        "endCondition": { "conditionTypeId": 1, "conditionTypeKey": "distance", "displayOrder": 1, "displayable": true },
        "endConditionValue": 2000.0,
        "targetType": { "workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4 },
        "targetValueLow": 130,
        "targetValueHigh": 145
      },
      {
        "type": "RepeatGroupDTO",
        "stepOrder": 2,
        "stepType": { "stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6 },
        "numberOfIterations": 4,
        "endCondition": { "conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": false },
        "endConditionValue": 4.0,
        "smartRepeat": false,
        "workoutSteps": [
          {
            "type": "ExecutableStepDTO",
            "stepOrder": 1,
            "stepType": { "stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3 },
            "endCondition": { "conditionTypeId": 1, "conditionTypeKey": "distance", "displayOrder": 1, "displayable": true },
            "endConditionValue": 1000.0,
            "targetType": { "workoutTargetTypeId": 5, "workoutTargetTypeKey": "speed.zone", "displayOrder": 5 },
            "targetValueLow": 3.226,
            "targetValueHigh": 3.448
          },
          {
            "type": "ExecutableStepDTO",
            "stepOrder": 2,
            "stepType": { "stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4 },
            "endCondition": { "conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": true },
            "endConditionValue": 120.0,
            "targetType": { "workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1 }
          }
        ]
      },
      {
        "type": "ExecutableStepDTO",
        "stepOrder": 3,
        "stepType": { "stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2 },
        "endCondition": { "conditionTypeId": 1, "conditionTypeKey": "distance", "displayOrder": 1, "displayable": true },
        "endConditionValue": 1000.0,
        "targetType": { "workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4 },
        "targetValueLow": 120,
        "targetValueHigh": 135
      }
    ]
  }]
}
```

---

## Scheduling

После загрузки тренировка получает `workoutId`. Ставим в календарь:

```
POST /proxy/workout-service/schedule/{workoutId}
Body: { "date": "2026-03-14" }
```

В библиотеке: `client.schedule_workout(workout_id, "2026-03-14")`

---

## Ограничения

- `open_step` (lap button) не поддерживается → заменяется на 60 сек recovery
- `sbu_block` представляется как repeat group из active (30 сек) + recovery (90 сек)
- Только running в первой итерации (sportTypeId=1)
