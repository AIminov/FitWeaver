"""User-facing texts for the desktop GUI (no Tkinter): plural forms, error hints.

Kept out of fitweaver_gui.py so they can be tested without a display.
"""

from __future__ import annotations

import re


def ru_count(n: int, one: str, few: str, many: str) -> str:
    """'1 тренировка', '3 тренировки', '5 тренировок'."""
    n = int(n)
    tail = n % 100
    if 11 <= tail <= 14:
        word = many
    elif n % 10 == 1:
        word = one
    elif 2 <= n % 10 <= 4:
        word = few
    else:
        word = many
    return f"{n} {word}"


def ru_workouts(n: int) -> str:
    return ru_count(n, "тренировка", "тренировки", "тренировок")


# Friendly hints shown under recognised CLI/log error lines.
ERROR_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"YAML (plan|file) not found", re.I),
     "Проверьте путь к файлу — убедитесь, что он указан верно и файл существует."),
    (re.compile(r"No YAML training plan found in"),
     "В папке Plan рядом с программой нет ни одного .yaml-файла. "
     "Выберите план через «Обзор…» или сначала сохраните его."),
    (re.compile(r"Connection check failed|Cannot connect to (Ollama|OpenAI-compatible|API at)", re.I),
     "Не удаётся подключиться к LLM. Проверьте, что сервер запущен, "
     "и что адрес/порт в настройках подключения указаны верно."),
    (re.compile(r"Timeout waiting for.*response", re.I),
     "LLM слишком долго не отвечает. Попробуйте план покороче или проверьте, что модель загружена."),
    (re.compile(r"Authentication failed", re.I),
     "Не удалось войти в Garmin Connect — проверьте логин и пароль."),
    (re.compile(r"(garmin-auth|garminconnect) not installed", re.I),
     "Не хватает модуля для работы с Garmin Connect. Переустановите приложение "
     "или сообщите разработчику."),
    (re.compile(r"YAML validation errors found|VALIDATION ERRORS"),
     "В плане есть ошибки — прокрутите лог немного выше, там подробности по каждой."),
    (re.compile(r"No FIT files (found|generated)"),
     "FIT-файлы не были созданы. Проверьте, что план прошёл валидацию без ошибок."),
    (re.compile(r"temp directory is not writable"),
     "Нет прав на запись во временную папку Windows — проверьте права доступа."),
    (re.compile(r"already scheduled", re.I),
     "Тренировка уже стоит в календаре Garmin на эту дату — повторно не загружается."),
]


def hint_for_line(text: str) -> str | None:
    """Plain-language hint for a known error line, or None."""
    for pattern, hint in ERROR_HINTS:
        if pattern.search(text):
            return hint
    return None


def garmin_error_message(exc: object, action: str = "операцию") -> str:
    """Explain a Garmin Connect failure for the operation that caused it.

    ``action`` is the operation in the accusative ("удаление", "загрузку",
    "чтение календаря"), so messages read naturally for every caller instead
    of always talking about deletion.
    """
    msg = str(exc)
    low = msg.casefold()
    if "atp" in low and "400" in msg:
        return ("Тренировка привязана к плану Garmin (ATP) — через API это сделать нельзя.\n"
                "Сделайте это вручную в приложении Garmin Connect.")
    if "401" in msg or "403" in msg or "unauthorized" in low or "forbidden" in low:
        return "Garmin Connect не принял вход — проверьте email и пароль или войдите заново."
    if "429" in msg or "too many requests" in low:
        return "Garmin Connect временно ограничил запросы. Подождите несколько минут и повторите."
    if "timed out" in low or "timeout" in low or ("connection" in low and "error" in low):
        return "Нет связи с Garmin Connect. Проверьте подключение к интернету и повторите."
    if "400" in msg:
        return f"Garmin Connect отклонил {action} (400). Возможно, тренировка защищена или уже изменена."
    return f"Ошибка: {msg}"
