"""Pure validation helpers used by the desktop workout builder."""

from __future__ import annotations

from typing import Any


def parse_builder_value(field_name: str, raw: str, value_type: type) -> tuple[Any, str | None]:
    """Parse one builder field and return ``(value, error_message)``.

    Empty fields remain optional and are represented by ``None``. The helper is
    deliberately independent of Tkinter so the user-facing validation rules
    can be tested without starting a GUI.
    """

    text = raw.strip()
    if not text:
        return None, None

    try:
        value = value_type(text)
    except (TypeError, ValueError):
        if value_type is int:
            return None, "Введите целое число."
        if value_type is float:
            return None, "Введите число, например 2.5."
        return None, "Проверьте значение поля."

    if field_name in {"hr_low", "hr_high"} and not 30 <= value <= 250:
        return None, "Пульс должен быть в диапазоне 30–250 уд/мин."
    if field_name == "km" and value <= 0:
        return None, "Расстояние должно быть больше нуля."
    if field_name == "seconds" and value <= 0:
        return None, "Длительность должна быть больше нуля."

    return value, None


def parse_repeat_count(raw: str) -> tuple[int | None, str | None]:
    """Validate the repeat count used by the builder editor."""

    text = raw.strip()
    try:
        count = int(text)
    except (TypeError, ValueError):
        return None, "Введите целое число повторов."
    if not 2 <= count <= 20:
        return None, "Количество повторов должно быть от 2 до 20."
    return count, None
