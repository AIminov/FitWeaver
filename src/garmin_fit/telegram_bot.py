"""
Telegram Bot for Garmin FIT Generator.
Accepts plan text -> generates YAML via LLM (LM Studio/Ollama) -> builds FIT files.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
from typing import Dict, List, Optional
from zipfile import ZIP_DEFLATED, ZipFile

import yaml
from telegram import Document, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .archive_manager import archive_current_plan, get_archive_name
from .config import ARCHIVE_DIR, ARTIFACTS_DIR, BOT_CONFIG_FILE, OUTPUT_DIR, PLAN_DIR
from .garmin_auth_manager import is_available as _garmin_auth_available
from .llm.client import UnifiedLLMClient
from .pipeline_runner import run_pipeline, save_yaml_to_plan_dir
from .plan_service import (
    apply_custom_sbu_choice,
    build_plan_draft,
    count_workouts,
    format_plan_preview,
    has_default_sbu_block,
)

# Rate limiting constants
REQUEST_COOLDOWN_SEC = 30
LLM_TIMEOUT_SEC = 300
MAX_PLAN_TEXT_LENGTH = 4000

# ---------------------------------------------------------------------------
# i18n — all user-visible strings in one place
# ---------------------------------------------------------------------------

_EXAMPLE_WORKOUTS_RU = [
    """\
📋 Пример 1 — Лёгкий бег

2026-05-04 (Пн) — Лёгкий бег
Дистанция: 10 км, пульс 125–140 уд/мин
""",
    """\
📋 Пример 2 — Темповый бег

2026-05-06 (Ср) — Темп
Разминка: 2 км лёгкий бег
Основная часть: 6 км при пульсе 160–170 уд/мин
Заминка: 2 км лёгкий бег
""",
    """\
📋 Пример 3 — Интервалы

2026-05-07 (Чт) — Интервальная тренировка
Разминка: 2 км лёгкий бег
Интервалы: 6 × 800 м при пульсе 175–185 уд/мин, отдых 90 сек трусцой
Заминка: 1.5 км лёгкий бег
""",
    """\
📋 Пример 4 — Длинный бег

2026-05-10 (Вс) — Длинный бег
Дистанция: 22 км, пульс 120–135 уд/мин
Темп разговорный, ровный
""",
    """\
📋 Пример 5 — Неделя с контекстом и СБУ

Подготовка к полумарафону, 8 недель до старта
Уровень: средний
ЧСС макс: 185 уд/мин
Зоны: Z1 < 130, Z2 130–145, Z3 146–160, Z4 161–175, Z5 > 175

05.05.2026 (Пн) — Лёгкий бег + СБУ
8 км, Z2; СБУ: высокое бедро, захлёст голени, прыжки на месте, ускорения 4×80 м

07.05.2026 (Ср) — Темповый бег
Разминка 2 км (Z1), основная часть 5 км (Z3), заминка 2 км (Z1)

09.05.2026 (Пт) — Восстановление
6 км, Z1, очень лёгкий темп

11.05.2026 (Вс) — Длинный бег
20 км, Z2, ровный темп, гель на 10-м км
""",
]

_EXAMPLE_WORKOUTS_EN = [
    """\
📋 Example 1 — Easy Run

2026-05-04 (Mon) — Easy run
Distance: 10 km, HR 125–140 bpm
""",
    """\
📋 Example 2 — Tempo Run

2026-05-06 (Wed) — Tempo
Warm-up: 2 km easy
Main: 6 km at HR 160–170 bpm
Cool-down: 2 km easy
""",
    """\
📋 Example 3 — Intervals

2026-05-07 (Thu) — Interval workout
Warm-up: 2 km easy
Intervals: 6 × 800 m at HR 175–185 bpm, 90 sec jog recovery
Cool-down: 1.5 km easy
""",
    """\
📋 Example 4 — Long Run

2026-05-10 (Sun) — Long run
Distance: 22 km, HR 120–135 bpm
Conversational pace, steady effort
""",
    """\
📋 Example 5 — Full week with context & drills

Half-marathon prep, 8 weeks to race
Level: intermediate
Max HR: 185 bpm
Zones: Z1 < 130, Z2 130–145, Z3 146–160, Z4 161–175, Z5 > 175

2026-05-05 (Mon) — Easy run + drills (SBU)
8 km, Z2; drills: high knees, butt kicks, jumps, 4 × 80 m strides

2026-05-07 (Wed) — Tempo run
Warm-up 2 km (Z1), main 5 km (Z3), cool-down 2 km (Z1)

2026-05-09 (Fri) — Recovery
6 km, Z1, very easy

2026-05-11 (Sun) — Long run
20 km, Z2, steady, gel at km 10
""",
]

MSG: dict[str, dict[str, str]] = {
    "ru": {
        # /start
        "choose_lang": "Выберите язык / Choose language:",
        "welcome": (
            "🏃 FitWeaver — генератор тренировок для Garmin\n\n"
            "Отправьте план тренировок текстом или файлом .txt / .md и я:\n"
            "1. Разберу план через LLM → создам структурированный YAML\n"
            "2. Покажу превью для подтверждения\n"
            "3. Соберу FIT-файлы, готовые для Garmin\n\n"
            "💡 Советы:\n"
            "• Указывайте даты (не «Понедельник») — тренировки привяжутся к конкретным дням\n"
            "• Контекст помогает: ваши пульсовые зоны, уровень, целевой старт — но всё необязательно\n"
            "• Готовый YAML? Отправьте .yaml файл — пропустим LLM-генерацию\n\n"
            "📦 Варианты доставки (после сборки):\n"
            "• 📁 FIT-файлы в ZIP — загрузите через Garmin Express или USB\n"
            "• 📅 Garmin Calendar — тренировки прямо в приложение, синхронизируются на часы без USB\n\n"
            "Ниже — примеры тренировок, которые можно скопировать и отправить 👇"
        ),
        "examples_intro": "📌 Примеры тренировок — скопируйте любой и отправьте боту:",
        # /help
        "help": (
            "Команды:\n"
            "/start  /help  /status  /cancel\n"
            "/build — собрать FIT-файлы из подтверждённого YAML\n"
            "\n"
            "Принимаемые файлы:\n"
            "  .txt / .md  — текст плана тренировок (LLM генерирует YAML)\n"
            "  .yaml / .yml — готовый YAML-план (LLM пропускается, сразу /build)\n"
            "\n"
            "Garmin Calendar (без USB):\n"
            "/connect_garmin [email password] — войти в Garmin Connect\n"
            "/send_to_garmin [год]            — загрузить последний план в календарь\n"
            "/delete_workout                  — удалить последнюю загруженную группу\n"
            "/delete_workout list             — список всех тренировок в Garmin Connect\n"
            "/delete_workout all              — удалить ВСЕ тренировки из аккаунта\n"
            "/disconnect_garmin               — выйти из Garmin Connect\n"
            "\n"
            "Сменить язык: /start"
        ),
        # Status messages
        "generating": "Генерирую YAML (таймаут: {timeout}s)...",
        "checking_llm": "Проверяю подключение к LLM...",
        "llm_no_connect": "Не удаётся подключиться к LLM серверу.",
        "llm_timeout": "Генерация LLM прервана по таймауту ({timeout} сек). Попробуйте более короткий план или проверьте LLM сервер.",
        "yaml_failed": "Не удалось сгенерировать корректный YAML.\n{details}",
        "yaml_ready_sbu": "YAML готов. Тренировок: {count}.\n\n{preview}\n\nНайден блок СБУ. Ответьте:\n• «стандарт» — оставить упражнения по умолчанию\n• текст с упражнениями — сгенерировать свои",
        "yaml_ready_ambig": "YAML готов. Тренировок: {count}.\n\n{preview}\n\nНайдены неоднозначности:\n{ambig}\n\nОтветьте уточнением и я перегенерирую, или /build чтобы продолжить как есть.",
        "yaml_ready": "YAML готов. Тренировок: {count}.\n\n{preview}\n\nЕсли всё верно — отправьте /build",
        "build_queued": "Задача поставлена в очередь. Позиция: {pos}",
        "build_running": "Запускаю: YAML → прямая сборка FIT → валидация",
        "build_done": "✅ Сборка завершена!\nFIT-файлов: {count}  (корректных {valid}/{total})",
        "build_failed": "Сборка завершилась с ошибкой:\n{errors}",
        "build_no_files": "Сборка завершена, но FIT-файлы не созданы.",
        "delivery_ask": "Как вы хотите получить тренировки?",
        "delivery_fit_btn": "📁 Отправить FIT-файлы (ZIP)",
        "delivery_garmin_btn": "📅 Загрузить в Garmin Calendar",
        "delivery_sending": "📁 Отправляю FIT-файлы...",
        "delivery_sent_hint": "Готово! Загрузите ZIP через Garmin Express или скопируйте .fit файлы на часы.",
        "delivery_garmin_uploading": "📅 Загружаю в Garmin Connect Calendar...",
        "delivery_garmin_not_connected": (
            "Вы не подключены к Garmin Connect.\n\n"
            "1. Используйте /connect_garmin для входа\n"
            "2. Затем /send_to_garmin чтобы загрузить план\n\n"
            "FIT-файлы готовы — план сохранён."
        ),
        "delivery_garmin_not_installed": (
            "Интеграция с Garmin не установлена.\n"
            "Запустите: pip install garminconnect garmin-auth\n\n"
            "Используйте /build и выберите «Отправить FIT-файлы»."
        ),
        "garmin_hint_connect": "\n\nСовет: /connect_garmin → /send_to_garmin — следующий раз загрузит прямо в календарь.",
        "delivery_choice_busy": "Пожалуйста, выберите вариант доставки выше (📁 или 📅),\nили /cancel чтобы отменить и начать заново.",
        "op_in_progress": "Операция выполняется (статус: {status}).\nДождитесь завершения или отправьте /cancel.",
        "cooldown": "Пожалуйста, подождите ещё {sec} сек перед отправкой нового плана.",
        "plan_too_long": "Текст плана слишком длинный ({chars} симв.). Максимум: {max} симв.",
        "plan_too_short": "Текст плана слишком короткий. Пожалуйста, добавьте больше деталей.",
        "cancelled": "Состояние сброшено.",
        "cancel_building": "Запрос на отмену отправлен. Текущая задача будет остановлена.",
        "cancel_garmin": "Вход в Garmin отменён.",
        "no_yaml": "Нет подтверждённого YAML-плана. Сначала отправьте план.",
        "already_queued": "Задача уже в очереди.",
        "sbu_expired": "Состояние СБУ истекло. Отправьте план заново.",
        "sbu_using_standard": "Используем стандартный СБУ.\n\n{preview}\n\nОтправьте /build",
        "sbu_custom_parsing": "Разбираю пользовательские упражнения...",
        "sbu_custom_added": "Пользовательские упражнения добавлены.\n\n{preview}\n\nОтправьте /build",
        "sbu_error": "Ошибка обработки СБУ: {err}\nПопробуйте снова или отправьте «стандарт».",
        "clarif_expired": "Контекст истёк. Пожалуйста, отправьте план заново.",
        "garmin_connecting": "Подключаюсь к Garmin Connect...",
        "garmin_connected": "Подключено к Garmin Connect.\nИспользуйте /send_to_garmin после сборки плана.",
        "garmin_auth_failed": "Ошибка аутентификации Garmin: {err}",
        "garmin_mfa_required": "Требуется двухфакторная аутентификация.\nОтправьте код из приложения:",
        "garmin_mfa_failed": "MFA не прошло: {err}\nИспользуйте /connect_garmin чтобы попробовать снова.",
        "garmin_mfa_expired": "Сессия MFA истекла. Используйте /connect_garmin чтобы начать заново.",
        "garmin_disconnected": "Сессия Garmin удалена. Используйте /connect_garmin для повторного входа.",
        "garmin_not_connected": "Не подключено к Garmin Connect.\nСначала используйте /connect_garmin.",
        "garmin_not_available": "garmin-auth не установлен.\nЗапустите: pip install garminconnect garmin-auth",
        "garmin_no_files": "Нет FIT-файлов от последней сборки.\nСначала используйте /build.",
        "garmin_no_plan": "Не найден собранный план. Сначала используйте /build.",
        "garmin_upload_start": "Загружаю в Garmin Connect Calendar...",
        "garmin_upload_done": "Загрузка в Garmin Calendar завершена.\n{summary}{sync_hint}",
        "garmin_upload_error": "Ошибка загрузки в Garmin Calendar: {err}",
        "garmin_sync_hint": "\n\nСинхронизируйте часы чтобы увидеть тренировки.",
        "garmin_ask_email": "Войти в Garmin Connect.\nОтправьте email вашего аккаунта Garmin:",
        "garmin_ask_password": "Отправьте пароль аккаунта Garmin:",
        "garmin_bad_email": "Это не похоже на корректный email. Попробуйте ещё раз:",
        "garmin_empty_password": "Пароль не может быть пустым. Попробуйте ещё раз:",
        "delete_no_recent": "Нет недавней загрузки.\nИспользуйте /delete_workout list или /delete_workout all.",
        "delete_deleting": "Удаляю {n} тренировку(-и) из последней загрузки...",
        "delete_done": "Готово. Удалено: {deleted}, ошибок: {failed}.",
        "delete_none": "Нет тренировок для удаления.",
        "delete_list_header": "Тренировки в Garmin Connect ({n}):",
        "delete_list_empty": "Тренировок в Garmin Connect не найдено.",
        "delete_all_start": "Удаляю {n} тренировок(и) из Garmin Connect...",
        "delete_error": "Ошибка: {err}",
        "yaml_loaded": "YAML-план загружен из {fname}.\n\nОтправьте /build для генерации FIT-файлов.",
        "file_format_error": "Поддерживаемые форматы: .txt, .md (текст плана) или .yaml/.yml (готовый план).",
        "file_read_error": "Ошибка чтения файла: {err}",
        "plan_error": "Ошибка обработки плана: {err}",
        "build_error": "Ошибка сборки: {err}",
        "zip_not_found": "ZIP-файл не найден. Используйте /build для повторной сборки.",
        "access_denied": "Доступ запрещён.",
        "status_msg": "статус={status}\nyaml_готов={yaml}\nfit_файлов={fits}\nочередь={queue}",
    },
    "en": {
        # /start
        "choose_lang": "Выберите язык / Choose language:",
        "welcome": (
            "🏃 FitWeaver — Garmin Workout Generator\n\n"
            "Send your training plan as text or a .txt / .md file and I will:\n"
            "1. Parse it via LLM → generate structured YAML\n"
            "2. Show a preview for confirmation\n"
            "3. Build FIT files ready for Garmin\n\n"
            "💡 Tips:\n"
            "• Use dates (not just 'Monday') — workouts map to exact calendar days\n"
            "• Context helps: your HR zones, fitness level, goal race — but all optional\n"
            "• Have a ready YAML? Send a .yaml file to skip LLM generation\n\n"
            "📦 Delivery options (after build):\n"
            "• 📁 FIT files in ZIP — load via Garmin Express or USB\n"
            "• 📅 Garmin Calendar — upload directly to the app, sync to watch without USB\n\n"
            "Example workouts to copy & send are below 👇"
        ),
        "examples_intro": "📌 Example workouts — copy any one and send it to the bot:",
        # /help
        "help": (
            "Commands:\n"
            "/start  /help  /status  /cancel\n"
            "/build — build FIT files from confirmed YAML\n"
            "\n"
            "Files accepted:\n"
            "  .txt / .md  — training plan text (LLM generates YAML)\n"
            "  .yaml / .yml — ready-made YAML plan (skip LLM, go straight to /build)\n"
            "\n"
            "Garmin Calendar (no USB):\n"
            "/connect_garmin [email password] — log in to Garmin Connect\n"
            "/send_to_garmin [year]           — upload last built plan to calendar\n"
            "/delete_workout                  — delete last uploaded batch\n"
            "/delete_workout list             — list all workouts in Garmin Connect\n"
            "/delete_workout all              — delete ALL workouts from account\n"
            "/disconnect_garmin               — clear Garmin session\n"
            "\n"
            "Change language: /start"
        ),
        "generating": "Generating YAML (timeout: {timeout}s)...",
        "checking_llm": "Checking LLM connection...",
        "llm_no_connect": "Cannot connect to LLM server.",
        "llm_timeout": "LLM generation timed out after {timeout} seconds. Try a shorter plan or check LLM server.",
        "yaml_failed": "Failed to generate valid YAML.\n{details}",
        "yaml_ready_sbu": "YAML ready. Workouts: {count}.\n\n{preview}\n\nSBU block found. Reply with:\n• 'standard' to keep default drills\n• custom drill text to generate your own",
        "yaml_ready_ambig": "YAML ready. Workouts: {count}.\n\n{preview}\n\nAmbiguities found:\n{ambig}\n\nReply with clarification and I'll regenerate, or /build to proceed as-is.",
        "yaml_ready": "YAML ready. Workouts: {count}.\n\n{preview}\n\nIf correct, send /build",
        "build_queued": "Build queued. Position: {pos}",
        "build_running": "Running: YAML → direct FIT build → validate",
        "build_done": "✅ Build done!\nFIT files: {count}  (valid {valid}/{total})",
        "build_failed": "Build failed:\n{errors}",
        "build_no_files": "Build finished but no FIT files generated.",
        "delivery_ask": "How would you like to receive your workouts?",
        "delivery_fit_btn": "📁 Send FIT files (ZIP)",
        "delivery_garmin_btn": "📅 Upload to Garmin Calendar",
        "delivery_sending": "📁 Sending FIT files...",
        "delivery_sent_hint": "Done! Load the ZIP via Garmin Express or copy .fit files to your watch.",
        "delivery_garmin_uploading": "📅 Uploading to Garmin Connect Calendar...",
        "delivery_garmin_not_connected": (
            "You are not connected to Garmin Connect.\n\n"
            "1. Use /connect_garmin to log in\n"
            "2. Then /send_to_garmin to upload the plan\n\n"
            "FIT files are ready — the plan is still available."
        ),
        "delivery_garmin_not_installed": (
            "Garmin integration not installed.\n"
            "Run: pip install garminconnect garmin-auth\n\n"
            "Use /build and choose 'Send FIT files' instead."
        ),
        "garmin_hint_connect": "\n\nTip: /connect_garmin → /send_to_garmin uploads directly to calendar next time.",
        "delivery_choice_busy": "Please choose a delivery option above (📁 or 📅),\nor send /cancel to discard and start over.",
        "op_in_progress": "Operation in progress (status: {status}).\nWait for it to finish, or send /cancel to reset.",
        "cooldown": "Please wait {sec} more seconds before sending another plan.",
        "plan_too_long": "Plan text is too long ({chars} chars). Maximum: {max} chars.",
        "plan_too_short": "Plan text is too short. Please send more details.",
        "cancelled": "Current plan state reset.",
        "cancel_building": "Cancellation requested. Current build job will be stopped.",
        "cancel_garmin": "Garmin login cancelled.",
        "no_yaml": "No confirmed YAML plan. Send plan text first.",
        "already_queued": "Build job is already queued.",
        "sbu_expired": "SBU state expired. Send plan again.",
        "sbu_using_standard": "Using standard SBU.\n\n{preview}\n\nSend /build",
        "sbu_custom_parsing": "Parsing custom drills...",
        "sbu_custom_added": "Custom drills added.\n\n{preview}\n\nSend /build",
        "sbu_error": "SBU processing error: {err}\nTry again or send 'standard' for default drills.",
        "clarif_expired": "Context expired. Please send the plan again.",
        "garmin_connecting": "Connecting to Garmin Connect...",
        "garmin_connected": "Connected to Garmin Connect.\nUse /send_to_garmin after building a plan.",
        "garmin_auth_failed": "Garmin authentication failed: {err}",
        "garmin_mfa_required": "Two-factor authentication required.\nReply with your MFA code:",
        "garmin_mfa_failed": "MFA failed: {err}\nUse /connect_garmin to try again.",
        "garmin_mfa_expired": "MFA session expired. Use /connect_garmin to start again.",
        "garmin_disconnected": "Garmin session cleared. Use /connect_garmin to reconnect.",
        "garmin_not_connected": "Not connected to Garmin Connect.\nUse /connect_garmin first.",
        "garmin_not_available": "garmin-auth not installed.\nRun: pip install garminconnect garmin-auth",
        "garmin_no_files": "No FIT files from last build.\nUse /build first.",
        "garmin_no_plan": "No built plan found. Use /build first.",
        "garmin_upload_start": "Uploading to Garmin Connect Calendar...",
        "garmin_upload_done": "Garmin Calendar upload complete.\n{summary}{sync_hint}",
        "garmin_upload_error": "Garmin Calendar upload error: {err}",
        "garmin_sync_hint": "\n\nSync your watch to see the scheduled workouts.",
        "garmin_ask_email": "Garmin Connect login.\nReply with your Garmin account email:",
        "garmin_ask_password": "Reply with your Garmin account password:",
        "garmin_bad_email": "That doesn't look like a valid email. Try again:",
        "garmin_empty_password": "Password cannot be empty. Try again:",
        "delete_no_recent": "No recent upload found.\nUse /delete_workout list or /delete_workout all.",
        "delete_deleting": "Deleting {n} workout(s) from last upload...",
        "delete_done": "Done. Deleted {deleted}, failed {failed}.",
        "delete_none": "No workouts to delete.",
        "delete_list_header": "Workouts in Garmin Connect ({n}):",
        "delete_list_empty": "No workouts found in Garmin Connect.",
        "delete_all_start": "Deleting {n} workout(s) from Garmin Connect...",
        "delete_error": "Error: {err}",
        "yaml_loaded": "YAML plan loaded from {fname}.\n\nSend /build to generate FIT files.",
        "file_format_error": "Supported formats: .txt, .md (plan text) or .yaml/.yml (ready plan).",
        "file_read_error": "File read error: {err}",
        "plan_error": "Plan processing error: {err}",
        "build_error": "Build execution error: {err}",
        "zip_not_found": "ZIP file not found. Use /build to rebuild.",
        "access_denied": "Access denied for this Telegram user.",
        "status_msg": "status={status}\nyaml_ready={yaml}\nfit_files={fits}\nqueue_size={queue}",
    },
}


def _lang(user_id: int) -> str:
    """Return stored language for user ('ru' or 'en')."""
    state = USER_STATES.get(user_id)
    return getattr(state, "language", "en") if state else "en"


def _m(user_id: int, key: str, **kwargs) -> str:
    """Get localised message string for user."""
    lang = _lang(user_id)
    template = MSG[lang].get(key) or MSG["en"].get(key, key)
    return template.format(**kwargs) if kwargs else template


def _examples(user_id: int) -> list[str]:
    return _EXAMPLE_WORKOUTS_RU if _lang(user_id) == "ru" else _EXAMPLE_WORKOUTS_EN


def check_required_directories() -> None:
    """Check that required directories exist and are writable."""
    dirs = [PLAN_DIR, OUTPUT_DIR, ARCHIVE_DIR, ARTIFACTS_DIR]
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
            test_file = d / ".write_test"
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            raise RuntimeError(f"Directory {d} is not writable: {e}")


@dataclass
class UserState:
    yaml_text: Optional[str] = None
    yaml_path: Optional[Path] = None
    # idle/generating/awaiting_sbu_choice/awaiting_clarification/awaiting_confirm/
    # queued/building/awaiting_garmin_email/awaiting_garmin_password/awaiting_garmin_mfa
    status: str = "idle"
    generated_at: Optional[datetime] = None
    fit_files: List[Path] = field(default_factory=list)
    pending_sbu_yaml_data: Optional[dict] = None
    original_plan_text: Optional[str] = None       # exact user input, preserved for ZIP
    active_plan_text: Optional[str] = None         # current generation input, may include clarification
    pending_ambiguities: List[str] = field(default_factory=list)
    pending_clarification: Optional[str] = None    # ambiguity questions shown to user
    clarification_attempted: bool = False          # prevent re-asking after one clarification
    cancel_requested: bool = False
    last_request_time: Optional[datetime] = None
    language: str = "en"
    # Delivery choice (after build)
    pending_zip_path: Optional[Path] = None
    # Garmin Calendar fields
    garmin_client: object = None                   # authenticated garminconnect.Garmin client
    garmin_manager: object = None                  # GarminAuthManager instance (for MFA resume)
    garmin_email: Optional[str] = None             # stored for token-dir lookup only
    garmin_pending_email: Optional[str] = None     # temporary during connect flow
    last_garmin_workout_ids: List[str] = field(default_factory=list)  # IDs from last upload


@dataclass
class BuildJob:
    chat_id: int
    user_id: int


USER_STATES: Dict[int, UserState] = {}
BUILD_QUEUE: Optional[asyncio.Queue] = None  # created in on_post_init inside event loop
BOT_CONFIG: Dict[str, object] = {}


def load_bot_config() -> Dict[str, object]:
    """Load bot configuration from bot_config.yaml."""
    config_path = BOT_CONFIG_FILE

    if not config_path.exists():
        raise FileNotFoundError(
            f"bot_config.yaml not found at {config_path}\n"
            "Please create it with Telegram token and LLM settings."
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # Backward compatibility: map old keys to new keys
    if "ollama_model" in config and "llm_model" not in config:
        config["llm_model"] = config["ollama_model"]
    if "ollama_url" in config and "llm_url" not in config:
        config["llm_url"] = config["ollama_url"]
    if "llm_api_type" not in config:
        config["llm_api_type"] = "ollama"  # default for backward compatibility

    required_keys = ["telegram_bot_token", "llm_model", "llm_url"]
    for key in required_keys:
        if not config.get(key):
            raise ValueError(f"Missing required config key: {key}")

    allowed_user_ids = config.get("allowed_user_ids")
    if allowed_user_ids is None:
        config["allowed_user_ids"] = []
    elif isinstance(allowed_user_ids, list):
        normalized = []
        for value in allowed_user_ids:
            try:
                normalized.append(int(value))
            except Exception:
                raise ValueError("allowed_user_ids must contain integer values")
        config["allowed_user_ids"] = normalized
    else:
        raise ValueError("allowed_user_ids must be a list of Telegram user ids")

    return config


def get_state(user_id: int) -> UserState:
    """Get or create state for Telegram user."""
    if user_id not in USER_STATES:
        USER_STATES[user_id] = UserState()
    return USER_STATES[user_id]


def reset_state(user_id: int) -> None:
    old = USER_STATES.get(user_id)
    lang = old.language if old else "en"
    if old and old.pending_zip_path:
        old.pending_zip_path.unlink(missing_ok=True)
    new = UserState()
    new.language = lang
    USER_STATES[user_id] = new


def user_is_allowed(user_id: int) -> bool:
    allowed = BOT_CONFIG.get("allowed_user_ids", [])
    if not allowed:
        return True
    return user_id in allowed


async def ensure_user_allowed(update: Update) -> bool:
    user = update.effective_user
    message = update.message
    if user is None or message is None:
        return False

    if user_is_allowed(user.id):
        return True

    await message.reply_text(_m(user.id, "access_denied"))
    return False


def _build_llm_client() -> UnifiedLLMClient:
    return UnifiedLLMClient(
        model=str(BOT_CONFIG["llm_model"]),
        base_url=str(BOT_CONFIG["llm_url"]),
        api_type=str(BOT_CONFIG.get("llm_api_type", "ollama")),
    )


def _decade_label(day: int) -> str:
    if day <= 10:
        return "decade-1"
    elif day <= 20:
        return "decade-2"
    else:
        return "decade-3"


def _create_plan_zip(
    zip_path: Path,
    plan_text: Optional[str],
    fit_files: List[Path],
    now: Optional[datetime] = None,
) -> None:
    """Create ZIP with user plan text and FIT files, organized by year/month/decade."""
    if now is None:
        now = datetime.now()
    folder = f"{now.year}/{now.month:02d}/{_decade_label(now.day)}"

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        if plan_text:
            archive.writestr(f"{folder}/input_plan.txt", plan_text)
        for fit_file in fit_files:
            archive.write(fit_file, arcname=f"{folder}/{fit_file.name}")


def _garmin_token_dir(user_id: int) -> Path:
    """Per-user token storage directory under ~/.garminconnect/."""
    return Path.home() / ".garminconnect" / f"tg_{user_id}"


# ---------------------------------------------------------------------------
# Garmin Calendar helpers
# ---------------------------------------------------------------------------

async def _garmin_upload_and_report(
    application,
    chat_id: int,
    user_id: int,
    year: int | None = None,
) -> None:
    """Upload the last built plan to Garmin Calendar and send a result message."""
    state = get_state(user_id)

    if not state.garmin_client:
        await application.bot.send_message(
            chat_id=chat_id, text=_m(user_id, "garmin_not_connected")
        )
        return

    if not state.yaml_path or not state.yaml_path.exists():
        await application.bot.send_message(
            chat_id=chat_id, text=_m(user_id, "garmin_no_plan")
        )
        return

    await application.bot.send_message(chat_id=chat_id, text=_m(user_id, "garmin_upload_start"))

    try:
        import yaml as _yaml
        from .garmin_calendar_export import GarminCalendarExporter
        from .plan_domain import plan_from_data

        plan_data = _yaml.safe_load(state.yaml_path.read_text(encoding="utf-8"))
        plan = plan_from_data(plan_data)

        exporter = GarminCalendarExporter(state.garmin_client)
        result = await asyncio.to_thread(
            exporter.upload_plan, plan, True, False, year
        )

        # Store uploaded IDs so /delete_workout can reference them
        state = get_state(user_id)
        state.last_garmin_workout_ids = [
            r.workout_id for r in result.results if r.workout_id
        ]

        sync_hint = _m(user_id, "garmin_sync_hint") if result.uploaded > 0 else ""
        await application.bot.send_message(
            chat_id=chat_id,
            text=_m(user_id, "garmin_upload_done", summary=result.summary(), sync_hint=sync_hint),
        )
    except Exception as exc:
        await application.bot.send_message(
            chat_id=chat_id,
            text=_m(user_id, "garmin_upload_error", err=exc),
        )


# ---------------------------------------------------------------------------
# Garmin Calendar command handlers
# ---------------------------------------------------------------------------

async def connect_garmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /connect_garmin — start Garmin Connect auth flow.

    Usage:
      /connect_garmin                → bot asks for email then password
      /connect_garmin email password → connect directly (password visible in chat)
    """
    if not await ensure_user_allowed(update):
        return

    if not _garmin_auth_available():
        await update.message.reply_text(_m(update.effective_user.id, "garmin_not_available"))
        return

    user_id = update.effective_user.id
    state = get_state(user_id)

    # Allow /connect_garmin email password as a single command for convenience
    if context.args and len(context.args) >= 2:
        email = context.args[0].strip()
        password = context.args[1].strip()
        await _do_garmin_connect(update, context, user_id, state, email, password)
        return

    # Two-step interactive flow
    state.status = "awaiting_garmin_email"
    state.garmin_pending_email = None
    await update.message.reply_text(_m(update.effective_user.id, "garmin_ask_email"))


async def disconnect_garmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /disconnect_garmin — clear stored Garmin session and tokens.
    """
    if not await ensure_user_allowed(update):
        return

    user_id = update.effective_user.id
    state = get_state(user_id)
    state.garmin_client = None
    state.garmin_manager = None
    state.garmin_email = None
    state.garmin_pending_email = None

    # Remove token directory so next connect re-authenticates fully
    token_dir = _garmin_token_dir(user_id)
    if token_dir.exists():
        import shutil
        shutil.rmtree(token_dir, ignore_errors=True)

    await update.message.reply_text(_m(update.effective_user.id, "garmin_disconnected"))


async def send_to_garmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /send_to_garmin [year] — upload the last built plan to Garmin Connect Calendar.
    """
    if not await ensure_user_allowed(update):
        return

    user_id = update.effective_user.id
    state = get_state(user_id)

    year: int | None = None
    if context.args:
        try:
            year = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Usage: /send_to_garmin [year]  e.g. /send_to_garmin 2026")
            return

    if not state.garmin_client:
        await update.message.reply_text(_m(user_id, "garmin_not_connected"))
        return

    if not state.fit_files:
        await update.message.reply_text(_m(user_id, "garmin_no_files"))
        return

    await _garmin_upload_and_report(
        context.application, update.effective_chat.id, user_id, year=year
    )


async def delete_workout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /delete_workout        — delete the last uploaded batch of workouts
    /delete_workout list   — list all workouts stored in Garmin Connect
    /delete_workout all    — delete ALL workouts from the account (asks confirmation)
    """
    if not await ensure_user_allowed(update):
        return

    user_id = update.effective_user.id
    state = get_state(user_id)

    if not state.garmin_client:
        await update.message.reply_text(_m(user_id, "garmin_not_connected"))
        return

    subcommand = (context.args[0].lower() if context.args else "last")

    # ── list ──────────────────────────────────────────────────────────────
    if subcommand == "list":
        try:
            workouts = await asyncio.to_thread(state.garmin_client.get_workouts, 0, 30)
            if not workouts:
                await update.message.reply_text(_m(user_id, "delete_list_empty"))
                return
            lines = [_m(user_id, "delete_list_header", n=len(workouts))]
            for w in workouts:
                lines.append(f"  {w['workoutId']}  {w.get('workoutName','?')}")
            await update.message.reply_text("\n".join(lines))
        except Exception as exc:
            await update.message.reply_text(_m(user_id, "delete_error", err=exc))
        return

    # ── all ───────────────────────────────────────────────────────────────
    if subcommand == "all":
        try:
            workouts = await asyncio.to_thread(state.garmin_client.get_workouts, 0, 200)
            if not workouts:
                await update.message.reply_text(_m(user_id, "delete_none"))
                return
            await update.message.reply_text(_m(user_id, "delete_all_start", n=len(workouts)))
            deleted, failed = 0, 0
            for w in workouts:
                try:
                    await asyncio.to_thread(state.garmin_client.delete_workout, w["workoutId"])
                    deleted += 1
                except Exception:
                    failed += 1
            state.last_garmin_workout_ids = []
            await update.message.reply_text(_m(user_id, "delete_done", deleted=deleted, failed=failed))
        except Exception as exc:
            await update.message.reply_text(_m(user_id, "delete_error", err=exc))
        return

    # ── last (default) ────────────────────────────────────────────────────
    ids = state.last_garmin_workout_ids
    if not ids:
        await update.message.reply_text(_m(user_id, "delete_no_recent"))
        return

    await update.message.reply_text(_m(user_id, "delete_deleting", n=len(ids)))
    deleted, failed = 0, 0
    for wid in ids:
        try:
            await asyncio.to_thread(state.garmin_client.delete_workout, wid)
            deleted += 1
        except Exception:
            failed += 1
    state.last_garmin_workout_ids = []
    await update.message.reply_text(_m(user_id, "delete_done", deleted=deleted, failed=failed))


# ---------------------------------------------------------------------------
# Internal: complete Garmin auth after email + password are known
# ---------------------------------------------------------------------------

async def _do_garmin_connect(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    state: UserState,
    email: str,
    password: str,
) -> None:
    from .garmin_auth_manager import GarminAuthManager

    state.status = "idle"
    await update.message.reply_text(_m(user_id, "garmin_connecting"))

    token_dir = _garmin_token_dir(user_id)
    token_dir.mkdir(parents=True, exist_ok=True)

    try:
        manager = GarminAuthManager(
            email=email,
            password=password,
            token_dir=token_dir,
            return_on_mfa=True,
        )
        result = await asyncio.to_thread(manager.connect)

        if result == "needs_mfa":
            state.garmin_manager = manager
            state.garmin_email = email
            state.status = "awaiting_garmin_mfa"
            await update.message.reply_text(_m(user_id, "garmin_mfa_required"))
            return

        state.garmin_client = result
        state.garmin_manager = manager
        state.garmin_email = email
        await update.message.reply_text(_m(user_id, "garmin_connected"))

    except Exception as exc:
        state.status = "idle"
        await update.message.reply_text(_m(user_id, "garmin_auth_failed", err=exc))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
    ]])
    await update.message.reply_text(
        "Выберите язык / Choose language:",
        reply_markup=keyboard,
    )


async def handle_lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle language selection inline keyboard."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    user_id = query.from_user.id
    if not user_is_allowed(user_id):
        await query.edit_message_text("Access denied.")
        return

    lang = (query.data or "").split(":", 1)[1]  # "ru" or "en"
    state = get_state(user_id)
    state.language = lang

    await query.edit_message_text(
        "🇷🇺 Выбран русский язык." if lang == "ru" else "🇬🇧 English selected."
    )
    # Send welcome message
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=_m(user_id, "welcome"),
    )
    # Send example workouts as separate messages (easy to copy-paste)
    for example in _examples(user_id):
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=example.strip(),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return
    await update.message.reply_text(_m(update.effective_user.id, "help"))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return
    user_id = update.effective_user.id
    state = get_state(user_id)
    if state.status in {"queued", "building"}:
        state.cancel_requested = True
        await update.message.reply_text(_m(user_id, "cancel_building"))
        return

    if state.status in {"awaiting_garmin_email", "awaiting_garmin_password", "awaiting_garmin_mfa"}:
        garmin_client = state.garmin_client
        garmin_manager = state.garmin_manager
        garmin_email = state.garmin_email
        reset_state(user_id)
        new_state = get_state(user_id)
        new_state.garmin_client = garmin_client
        new_state.garmin_manager = garmin_manager
        new_state.garmin_email = garmin_email
        await update.message.reply_text(_m(user_id, "cancel_garmin"))
        return

    reset_state(user_id)
    await update.message.reply_text(_m(user_id, "cancelled"))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return

    user_id = update.effective_user.id
    state = get_state(user_id)
    await update.message.reply_text(
        _m(user_id, "status_msg",
           status=state.status,
           yaml="yes" if state.yaml_text else "no",
           fits=len(state.fit_files),
           queue=BUILD_QUEUE.qsize() if BUILD_QUEUE else 0)
    )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return

    if update.message is None or update.message.text is None:
        return
    if update.message.text.startswith("/"):
        return

    user_id = update.effective_user.id
    state = get_state(user_id)
    text = update.message.text

    if state.status == "awaiting_garmin_email":
        await _handle_garmin_email(update, context, text)
        return

    if state.status == "awaiting_garmin_password":
        await _handle_garmin_password(update, context, text)
        return

    if state.status == "awaiting_garmin_mfa":
        await _handle_garmin_mfa(update, context, text)
        return

    if state.status == "awaiting_sbu_choice":
        await _handle_sbu_choice(update, context, text)
        return

    if state.status == "awaiting_clarification":
        await _handle_clarification(update, context, text)
        return

    if state.status in ("generating", "queued", "building"):
        await update.message.reply_text(_m(user_id, "op_in_progress", status=state.status))
        return

    if state.status == "awaiting_delivery_choice":
        await update.message.reply_text(_m(user_id, "delivery_choice_busy"))
        return

    # Rate limiting: cooldown between requests
    if state.last_request_time:
        elapsed = (datetime.now() - state.last_request_time).total_seconds()
        if elapsed < REQUEST_COOLDOWN_SEC:
            remaining = int(REQUEST_COOLDOWN_SEC - elapsed)
            await update.message.reply_text(_m(user_id, "cooldown", sec=remaining))
            return

    # Rate limiting: max text length
    if len(text) > MAX_PLAN_TEXT_LENGTH:
        await update.message.reply_text(
            _m(user_id, "plan_too_long", chars=len(text), max=MAX_PLAN_TEXT_LENGTH)
        )
        return

    if len(text.strip()) < 20:
        await update.message.reply_text(_m(user_id, "plan_too_short"))
        return

    state.clarification_attempted = False
    state.pending_ambiguities = []
    state.pending_clarification = None
    state.pending_sbu_yaml_data = None
    state.original_plan_text = text
    state.active_plan_text = text
    state.last_request_time = datetime.now()
    await _process_plan(update, context, text)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return

    if update.message is None or update.message.document is None:
        return

    user_id = update.effective_user.id
    state = get_state(user_id)

    if state.status in ("generating", "queued", "building"):
        await update.message.reply_text(_m(user_id, "op_in_progress", status=state.status))
        return

    if state.status == "awaiting_delivery_choice":
        await update.message.reply_text(_m(user_id, "delivery_choice_busy"))
        return

    document: Document = update.message.document
    fname = document.file_name or ""
    is_plan_text = fname.endswith((".txt", ".md"))
    is_yaml = fname.endswith((".yaml", ".yml"))
    if not is_plan_text and not is_yaml:
        await update.message.reply_text(_m(user_id, "file_format_error"))
        return

    # Rate limiting: cooldown between requests
    if state.last_request_time:
        elapsed = (datetime.now() - state.last_request_time).total_seconds()
        if elapsed < REQUEST_COOLDOWN_SEC:
            remaining = int(REQUEST_COOLDOWN_SEC - elapsed)
            await update.message.reply_text(_m(user_id, "cooldown", sec=remaining))
            return

    try:
        tmp_dir = Path(gettempdir())
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = Path(document.file_name).name
        file_path = tmp_dir / f"tg_{update.effective_user.id}_{ts}_{safe_name}"

        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive(file_path)
        plan_text = file_path.read_text(encoding="utf-8")
        file_path.unlink(missing_ok=True)

        # Rate limiting: max text length
        if len(plan_text) > MAX_PLAN_TEXT_LENGTH:
            await update.message.reply_text(
                _m(user_id, "plan_too_long", chars=len(plan_text), max=MAX_PLAN_TEXT_LENGTH)
            )
            return

        if is_yaml:
            # YAML plan — skip LLM, go straight to build
            import yaml as _yaml
            try:
                _yaml.safe_load(plan_text)  # validate it parses
            except Exception as ye:
                await update.message.reply_text(f"Invalid YAML: {ye}")
                return
            state.yaml_text = plan_text
            state.yaml_path = None
            state.original_plan_text = plan_text
            state.active_plan_text = plan_text
            state.generated_at = datetime.now()
            state.pending_ambiguities = []
            state.pending_clarification = None
            state.pending_sbu_yaml_data = None
            state.last_request_time = datetime.now()
            state.status = "awaiting_confirm"
            await update.message.reply_text(_m(user_id, "yaml_loaded", fname=fname))
            return

        state.clarification_attempted = False
        state.pending_ambiguities = []
        state.pending_clarification = None
        state.pending_sbu_yaml_data = None
        state.original_plan_text = plan_text
        state.active_plan_text = plan_text
        state.last_request_time = datetime.now()
        await _process_plan(update, context, plan_text)

    except Exception as e:
        await update.message.reply_text(_m(user_id, "file_read_error", err=e))


async def _process_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)

    try:
        state.status = "generating"
        state.active_plan_text = plan_text

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        llm = _build_llm_client()

        await update.message.reply_text(_m(user_id, "checking_llm"))
        is_connected = await asyncio.to_thread(llm.check_connection)
        if not is_connected:
            await update.message.reply_text(_m(user_id, "llm_no_connect"))
            state.status = "idle"
            return

        await update.message.reply_text(_m(user_id, "generating", timeout=LLM_TIMEOUT_SEC))
        try:
            draft = await asyncio.wait_for(
                asyncio.to_thread(build_plan_draft, llm, plan_text),
                timeout=LLM_TIMEOUT_SEC
            )
        except asyncio.TimeoutError:
            await update.message.reply_text(_m(user_id, "llm_timeout", timeout=LLM_TIMEOUT_SEC))
            state.status = "idle"
            return

        if not draft.yaml_text or not isinstance(draft.data, dict):
            details = "\n".join(draft.validation_errors[:5]) or ""
            await update.message.reply_text(_m(user_id, "yaml_failed", details=details))
            state.status = "idle"
            return

        yaml_data = draft.data
        workout_count = count_workouts(yaml_data)
        preview = format_plan_preview(draft)

        state.yaml_text = draft.yaml_text
        state.generated_at = datetime.now()
        state.pending_ambiguities = list(draft.ambiguities)
        state.pending_clarification = None

        if has_default_sbu_block(yaml_data):
            state.pending_sbu_yaml_data = yaml_data
            state.status = "awaiting_sbu_choice"
            await update.message.reply_text(
                _m(user_id, "yaml_ready_sbu", count=workout_count, preview=preview)
            )
            return

        if draft.ambiguities and not state.clarification_attempted:
            state.pending_clarification = "\n".join(f"• {a}" for a in draft.ambiguities[:5])
            state.status = "awaiting_clarification"
            await update.message.reply_text(
                _m(user_id, "yaml_ready_ambig",
                   count=workout_count, preview=preview, ambig=state.pending_clarification)
            )
            return

        state.status = "awaiting_confirm"
        await update.message.reply_text(
            _m(user_id, "yaml_ready", count=workout_count, preview=preview)
        )

    except Exception as e:
        state.status = "idle"
        await update.message.reply_text(_m(user_id, "plan_error", err=e))


async def _handle_garmin_email(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)
    email = text.strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text(_m(user_id, "garmin_bad_email"))
        return
    state.garmin_pending_email = email
    state.status = "awaiting_garmin_password"
    await update.message.reply_text(_m(user_id, "garmin_ask_password"))


async def _handle_garmin_password(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)
    password = text.strip()
    if not password:
        await update.message.reply_text(_m(user_id, "garmin_empty_password"))
        return
    email = state.garmin_pending_email or ""
    state.garmin_pending_email = None
    await _do_garmin_connect(update, context, user_id, state, email, password)


async def _handle_garmin_mfa(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)
    mfa_code = text.strip()
    manager = state.garmin_manager

    if manager is None:
        state.status = "idle"
        await update.message.reply_text(_m(user_id, "garmin_mfa_expired"))
        return

    try:
        client = await asyncio.to_thread(manager.resume, mfa_code)
        state.garmin_client = client
        state.status = "idle"
        await update.message.reply_text(_m(user_id, "garmin_connected"))
    except Exception as exc:
        state.status = "idle"
        state.garmin_manager = None
        await update.message.reply_text(_m(user_id, "garmin_mfa_failed", err=exc))


async def _handle_sbu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)
    yaml_data = state.pending_sbu_yaml_data

    if not isinstance(yaml_data, dict):
        state.status = "idle"
        state.pending_sbu_yaml_data = None
        await update.message.reply_text(_m(user_id, "sbu_expired"))
        return

    if user_text.strip().lower() in ("standard", "default", "1", "стандарт"):
        state.pending_sbu_yaml_data = None
        if state.yaml_text is None:
            state.status = "idle"
            await update.message.reply_text(_m(user_id, "sbu_expired"))
            return

        preview = state.yaml_text[:1500] + "..." if state.yaml_text and len(state.yaml_text) > 1500 else state.yaml_text
        ambiguities = state.pending_ambiguities[:5]
        if ambiguities and not state.clarification_attempted:
            state.pending_ambiguities = list(ambiguities)
            state.pending_clarification = "\n".join(f"• {a}" for a in ambiguities)
            state.status = "awaiting_clarification"
            await update.message.reply_text(
                _m(user_id, "yaml_ready_ambig",
                   count="?", preview=preview, ambig=state.pending_clarification)
            )
            return

        state.pending_clarification = None
        state.status = "awaiting_confirm"
        await update.message.reply_text(_m(user_id, "sbu_using_standard", preview=preview))
        return

    try:
        llm = _build_llm_client()
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await update.message.reply_text(_m(user_id, "sbu_custom_parsing"))

        draft = await asyncio.to_thread(apply_custom_sbu_choice, llm, yaml_data, user_text)
        state.yaml_text = draft.yaml_text
        state.pending_sbu_yaml_data = None
        state.pending_ambiguities = list(draft.ambiguities)

        preview = format_plan_preview(draft)
        if draft.ambiguities and not state.clarification_attempted:
            state.pending_clarification = "\n".join(f"• {a}" for a in draft.ambiguities[:5])
            state.status = "awaiting_clarification"
            await update.message.reply_text(
                _m(user_id, "yaml_ready_ambig",
                   count="?", preview=preview, ambig=state.pending_clarification)
            )
            return

        state.pending_clarification = None
        state.status = "awaiting_confirm"
        await update.message.reply_text(_m(user_id, "sbu_custom_added", preview=preview))

    except Exception as e:
        await update.message.reply_text(_m(user_id, "sbu_error", err=e))


async def _handle_clarification(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)

    if not state.active_plan_text:
        state.status = "idle"
        await update.message.reply_text(_m(update.effective_user.id, "clarif_expired"))
        return

    state.clarification_attempted = True
    clarified_text = state.active_plan_text + f"\n\nUser clarification: {user_text}"
    await _process_plan(update, context, clarified_text)


async def build(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return

    user_id = update.effective_user.id
    state = get_state(user_id)

    if state.status == "awaiting_clarification":
        state.status = "awaiting_confirm"

    if state.status not in {"awaiting_confirm", "queued"}:
        await update.message.reply_text(_m(user_id, "no_yaml"))
        return

    if state.status == "queued":
        await update.message.reply_text(_m(user_id, "already_queued"))
        return

    state.cancel_requested = False
    state.status = "queued"
    await BUILD_QUEUE.put(BuildJob(chat_id=update.effective_chat.id, user_id=user_id))
    await update.message.reply_text(_m(user_id, "build_queued", pos=BUILD_QUEUE.qsize()))


async def _execute_build_job(application: Application, job: BuildJob) -> None:
    state = get_state(job.user_id)
    if state.status != "queued":
        return
    uid = job.user_id
    if state.cancel_requested:
        state.status = "idle"
        state.cancel_requested = False
        await application.bot.send_message(chat_id=job.chat_id, text=_m(uid, "cancelled"))
        return

    if not state.yaml_text:
        state.status = "idle"
        await application.bot.send_message(chat_id=job.chat_id, text=_m(uid, "no_yaml"))
        return

    state.status = "building"

    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        yaml_filename = f"plan_u{job.user_id}_{ts}.yaml"
        yaml_path = save_yaml_to_plan_dir(state.yaml_text, yaml_filename)
        state.yaml_path = yaml_path

        await application.bot.send_message(
            chat_id=job.chat_id,
            text=_m(uid, "build_running"),
        )

        result = await asyncio.to_thread(run_pipeline, yaml_path)
        if state.cancel_requested:
            state.status = "idle"
            state.cancel_requested = False
            await application.bot.send_message(chat_id=job.chat_id, text=_m(uid, "cancelled"))
            return
        if not result.get("success"):
            errors = "\n".join(result.get("errors", [])) or "Unknown error"
            await application.bot.send_message(
                chat_id=job.chat_id, text=_m(uid, "build_failed", errors=errors)
            )
            state.status = "idle"
            return

        fit_files = result.get("fit_files", [])
        state.fit_files = fit_files

        if not fit_files:
            await application.bot.send_message(chat_id=job.chat_id, text=_m(uid, "build_no_files"))
            state.status = "idle"
            return

        if state.cancel_requested:
            state.status = "idle"
            state.cancel_requested = False
            await application.bot.send_message(chat_id=job.chat_id, text=_m(uid, "cancelled"))
            return

        await application.bot.send_message(
            chat_id=job.chat_id,
            text=_m(uid, "build_done",
                    count=len(fit_files),
                    valid=result.get("valid_count", 0),
                    total=result.get("total_count", 0)),
        )

        # Build ZIP and store path in state — send only after delivery choice
        now = datetime.now()
        zip_name = f"garmin_{now.strftime('%Y-%m')}_u{job.user_id}_{ts}.zip"
        zip_path = Path(gettempdir()) / zip_name
        _create_plan_zip(zip_path, state.original_plan_text, fit_files, now)
        state.pending_zip_path = zip_path

        # Archive build artifacts (always, regardless of delivery choice)
        archive_name = get_archive_name(plan_name=yaml_path.stem, owner_tag=job.user_id)
        archive_current_plan(
            archive_name=archive_name,
            run_id=f"tg_u{job.user_id}_{ts}",
            owner_tag=job.user_id,
            plan_paths=[yaml_path],
            artifact_paths=result.get("artifact_paths", []),
        )

        # Ask user how to deliver the workouts
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(_m(uid, "delivery_fit_btn"), callback_data="delivery:fit"),
            InlineKeyboardButton(_m(uid, "delivery_garmin_btn"), callback_data="delivery:garmin"),
        ]])
        state.status = "awaiting_delivery_choice"
        await application.bot.send_message(
            chat_id=job.chat_id,
            text=_m(uid, "delivery_ask"),
            reply_markup=keyboard,
        )

    except Exception as e:
        await application.bot.send_message(
            chat_id=job.chat_id, text=_m(job.user_id, "build_error", err=e)
        )
        state.status = "idle"
    finally:
        state.cancel_requested = False
        # Keep "awaiting_delivery_choice" — it will be resolved by the inline keyboard callback
        if state.status not in ("awaiting_delivery_choice",):
            state.status = "idle"


async def handle_delivery_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard callback for delivery choice (FIT files or Garmin Calendar)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    user_id = query.from_user.id
    if not user_is_allowed(user_id):
        await query.edit_message_text("Access denied.")
        return

    state = get_state(user_id)
    data = query.data or ""

    if not data.startswith("delivery:"):
        return

    choice = data.split(":", 1)[1]

    if choice == "fit":
        zip_path = state.pending_zip_path
        state.pending_zip_path = None
        state.status = "idle"

        if not zip_path or not zip_path.exists():
            await query.edit_message_text(_m(user_id, "zip_not_found"))
            return

        await query.edit_message_text(_m(user_id, "delivery_sending"))
        try:
            with open(zip_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=f,
                    filename=zip_path.name,
                    caption=f"{len(state.fit_files)} FIT file(s)",
                )
        finally:
            zip_path.unlink(missing_ok=True)

        hint = _m(user_id, "garmin_hint_connect") if (not state.garmin_client and _garmin_auth_available()) else ""
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=_m(user_id, "delivery_sent_hint") + hint,
        )

    elif choice == "garmin":
        if state.pending_zip_path:
            state.pending_zip_path.unlink(missing_ok=True)
            state.pending_zip_path = None

        if not state.garmin_client:
            state.status = "idle"
            if not _garmin_auth_available():
                await query.edit_message_text(_m(user_id, "delivery_garmin_not_installed"))
            else:
                await query.edit_message_text(_m(user_id, "delivery_garmin_not_connected"))
            return

        await query.edit_message_text(_m(user_id, "delivery_garmin_uploading"))
        state.status = "idle"
        await _garmin_upload_and_report(
            context.application,
            query.message.chat_id,
            user_id,
        )


async def build_worker(application: Application) -> None:
    while True:
        job = await BUILD_QUEUE.get()
        try:
            await _execute_build_job(application, job)
        finally:
            BUILD_QUEUE.task_done()


async def on_post_init(application: Application) -> None:
    global BUILD_QUEUE
    BUILD_QUEUE = asyncio.Queue()
    application.create_task(build_worker(application))


def main() -> None:
    global BOT_CONFIG
    BOT_CONFIG = load_bot_config()
    check_required_directories()

    application = (
        Application.builder()
        .token(str(BOT_CONFIG["telegram_bot_token"]))
        .post_init(on_post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("build", build))
    application.add_handler(CommandHandler("connect_garmin", connect_garmin))
    application.add_handler(CommandHandler("disconnect_garmin", disconnect_garmin))
    application.add_handler(CommandHandler("send_to_garmin", send_to_garmin))
    application.add_handler(CommandHandler("delete_workout", delete_workout))
    application.add_handler(CallbackQueryHandler(handle_lang_choice, pattern="^lang:"))
    application.add_handler(CallbackQueryHandler(handle_delivery_choice, pattern="^delivery:"))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("Bot is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
