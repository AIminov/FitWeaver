from garmin_fit.garmin_calendar_view import normalize_scheduled_workouts


def test_normalizes_garmin_schedule_list_and_nested_workout():
    payload = [
        {
            "workoutScheduleId": 42,
            "calendarDate": "2026-09-23",
            "workout": {"workoutId": 7, "workoutName": "Лёгкий бег"},
        }
    ]

    assert normalize_scheduled_workouts(payload) == [
        {
            "date": "2026-09-23",
            "name": "Лёгкий бег",
            "schedule_id": "42",
            "workout_id": "7",
        }
    ]


def test_normalizes_wrapped_and_date_keyed_schedule_items():
    payload = {
        "calendar": {
            "2026-09-24": [
                {"workoutScheduleId": 43, "workoutName": "Интервалы"}
            ]
        },
        "scheduledWorkouts": [
            {
                "workoutScheduleId": 42,
                "calendarDate": "2026-09-23T00:00:00.000",
                "workout": {"workoutName": "Лёгкий бег"},
            }
        ],
    }

    assert [(item["date"], item["name"]) for item in normalize_scheduled_workouts(payload)] == [
        ("2026-09-23", "Лёгкий бег"),
        ("2026-09-24", "Интервалы"),
    ]


def test_ignores_unrelated_items_and_duplicate_schedules():
    workout = {
        "workoutScheduleId": 42,
        "calendarDate": "2026-09-23",
        "workoutName": "Лёгкий бег",
    }

    assert normalize_scheduled_workouts(
        {"events": [{"calendarDate": "2026-09-23", "title": "Напоминание"}, workout, workout]}
    ) == [
        {"date": "2026-09-23", "name": "Лёгкий бег", "schedule_id": "42"}
    ]


def test_normalizes_flat_scheduled_workout_shape():
    assert normalize_scheduled_workouts(
        [{
            "scheduledDate": "2026-09-25",
            "workoutId": 81,
            "workoutName": "Восстановительный бег",
        }]
    ) == [
        {
            "date": "2026-09-25",
            "name": "Восстановительный бег",
            "schedule_id": "",
            "workout_id": "81",
        }
    ]
