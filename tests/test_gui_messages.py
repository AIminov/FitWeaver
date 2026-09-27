from garmin_fit.gui_messages import garmin_error_message, hint_for_line, ru_workouts


def test_plural_forms():
    assert [ru_workouts(n) for n in (1, 3, 5, 11, 21, 22, 112)] == [
        "1 тренировка", "3 тренировки", "5 тренировок", "11 тренировок",
        "21 тренировка", "22 тренировки", "112 тренировок",
    ]


def test_garmin_errors_name_the_actual_operation():
    assert "проверьте email и пароль" in garmin_error_message(RuntimeError("401 Unauthorized"), "чтение календаря")
    assert "отклонил чтение календаря" in garmin_error_message(RuntimeError("400 Bad Request"), "чтение календаря")
    assert "удаление" not in garmin_error_message(RuntimeError("400"), "загрузку тренировки")
    assert "ATP" in garmin_error_message(RuntimeError("400 ATP plan workout"), "удаление")
    assert "ограничил" in garmin_error_message(RuntimeError("429 Too Many Requests"))
    assert "интернет" in garmin_error_message(RuntimeError("Read timed out"))


def test_hint_for_known_error_line():
    assert "Garmin Connect" in hint_for_line("[FAIL] Authentication failed: bad creds")
    assert hint_for_line("all good") is None
