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
from telegram import Document, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
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
    USER_STATES[user_id] = UserState()


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

    await message.reply_text("Access denied for this Telegram user.")
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
            chat_id=chat_id,
            text="Not connected to Garmin. Use /connect_garmin first.",
        )
        return

    if not state.yaml_path or not state.yaml_path.exists():
        await application.bot.send_message(
            chat_id=chat_id,
            text="No built plan found. Use /build first.",
        )
        return

    await application.bot.send_message(chat_id=chat_id, text="Uploading to Garmin Connect Calendar...")

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

        await application.bot.send_message(
            chat_id=chat_id,
            text=(
                f"Garmin Calendar upload complete.\n"
                f"{result.summary()}"
                + (
                    "\n\nSync your watch to see the scheduled workouts."
                    if result.uploaded > 0 else ""
                )
            ),
        )
    except Exception as exc:
        await application.bot.send_message(
            chat_id=chat_id,
            text=f"Garmin Calendar upload error: {exc}",
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
        await update.message.reply_text(
            "garmin-auth not installed.\n"
            "Run: pip install garminconnect garmin-auth"
        )
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
    await update.message.reply_text(
        "Garmin Connect login.\n"
        "Reply with your Garmin account email:"
    )


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

    await update.message.reply_text("Garmin session cleared. Use /connect_garmin to reconnect.")


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
        await update.message.reply_text(
            "Not connected to Garmin Connect.\n"
            "Use /connect_garmin first."
        )
        return

    if not state.fit_files:
        await update.message.reply_text(
            "No FIT files from last build.\n"
            "Use /build first."
        )
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
        await update.message.reply_text(
            "Not connected to Garmin Connect.\nUse /connect_garmin first."
        )
        return

    subcommand = (context.args[0].lower() if context.args else "last")

    # ── list ──────────────────────────────────────────────────────────────
    if subcommand == "list":
        try:
            workouts = await asyncio.to_thread(state.garmin_client.get_workouts, 0, 30)
            if not workouts:
                await update.message.reply_text("No workouts found in Garmin Connect.")
                return
            lines = [f"Workouts in Garmin Connect ({len(workouts)}):"]
            for w in workouts:
                lines.append(f"  {w['workoutId']}  {w.get('workoutName','?')}")
            await update.message.reply_text("\n".join(lines))
        except Exception as exc:
            await update.message.reply_text(f"Error listing workouts: {exc}")
        return

    # ── all ───────────────────────────────────────────────────────────────
    if subcommand == "all":
        try:
            workouts = await asyncio.to_thread(state.garmin_client.get_workouts, 0, 200)
            if not workouts:
                await update.message.reply_text("No workouts to delete.")
                return
            await update.message.reply_text(
                f"Deleting {len(workouts)} workouts from Garmin Connect..."
            )
            deleted, failed = 0, 0
            for w in workouts:
                try:
                    await asyncio.to_thread(
                        state.garmin_client.delete_workout, w["workoutId"]
                    )
                    deleted += 1
                except Exception:
                    failed += 1
            state.last_garmin_workout_ids = []
            await update.message.reply_text(
                f"Done. Deleted {deleted}, failed {failed}."
            )
        except Exception as exc:
            await update.message.reply_text(f"Error deleting workouts: {exc}")
        return

    # ── last (default) ────────────────────────────────────────────────────
    ids = state.last_garmin_workout_ids
    if not ids:
        await update.message.reply_text(
            "No recent upload found.\n"
            "Use /delete_workout list to see all workouts,\n"
            "or /delete_workout all to delete everything."
        )
        return

    await update.message.reply_text(f"Deleting {len(ids)} workout(s) from last upload...")
    deleted, failed = 0, 0
    for wid in ids:
        try:
            await asyncio.to_thread(state.garmin_client.delete_workout, wid)
            deleted += 1
        except Exception:
            failed += 1
    state.last_garmin_workout_ids = []
    await update.message.reply_text(
        f"Done. Deleted {deleted}, failed {failed}."
    )


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
    await update.message.reply_text("Connecting to Garmin Connect...")

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
            await update.message.reply_text(
                "Two-factor authentication required.\n"
                "Reply with your MFA code:"
            )
            return

        state.garmin_client = result
        state.garmin_manager = manager
        state.garmin_email = email
        await update.message.reply_text(
            "Connected to Garmin Connect.\n"
            "Use /send_to_garmin after building a plan."
        )

    except Exception as exc:
        state.status = "idle"
        await update.message.reply_text(f"Garmin authentication failed: {exc}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return
    await update.message.reply_text(
        "Garmin FIT bot is ready.\n"
        "Send plan text, then use /build after YAML preview."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return
    await update.message.reply_text(
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
        "/disconnect_garmin               — clear session"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return
    user_id = update.effective_user.id
    state = get_state(user_id)
    if state.status in {"queued", "building"}:
        state.cancel_requested = True
        await update.message.reply_text("Cancellation requested. Current build job will be stopped.")
        return

    if state.status in {"awaiting_garmin_email", "awaiting_garmin_password", "awaiting_garmin_mfa"}:
        # Preserve any already-connected Garmin client while resetting the flow
        garmin_client = state.garmin_client
        garmin_manager = state.garmin_manager
        garmin_email = state.garmin_email
        reset_state(user_id)
        new_state = get_state(user_id)
        new_state.garmin_client = garmin_client
        new_state.garmin_manager = garmin_manager
        new_state.garmin_email = garmin_email
        await update.message.reply_text("Garmin login cancelled.")
        return

    reset_state(user_id)
    await update.message.reply_text("Current plan state reset.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return

    user_id = update.effective_user.id
    state = get_state(user_id)
    await update.message.reply_text(
        f"status={state.status}\n"
        f"yaml_ready={'yes' if state.yaml_text else 'no'}\n"
        f"fit_files={len(state.fit_files)}\n"
        f"queue_size={BUILD_QUEUE.qsize() if BUILD_QUEUE else 0}"
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
        await update.message.reply_text(
            f"Current operation in progress (status: {state.status}).\n"
            "Wait for it to finish, or send /cancel to reset."
        )
        return

    # Rate limiting: cooldown between requests
    if state.last_request_time:
        elapsed = (datetime.now() - state.last_request_time).total_seconds()
        if elapsed < REQUEST_COOLDOWN_SEC:
            remaining = int(REQUEST_COOLDOWN_SEC - elapsed)
            await update.message.reply_text(
                f"Please wait {remaining} seconds before sending another plan."
            )
            return

    # Rate limiting: max text length
    if len(text) > MAX_PLAN_TEXT_LENGTH:
        await update.message.reply_text(
            f"Plan text is too long ({len(text)} chars). "
            f"Maximum allowed: {MAX_PLAN_TEXT_LENGTH} chars."
        )
        return

    if len(text.strip()) < 20:
        await update.message.reply_text("Plan text is too short. Please send more details.")
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
        await update.message.reply_text(
            f"Current operation in progress (status: {state.status}).\n"
            "Wait for it to finish, or send /cancel to reset."
        )
        return

    document: Document = update.message.document
    fname = document.file_name or ""
    is_plan_text = fname.endswith((".txt", ".md"))
    is_yaml = fname.endswith((".yaml", ".yml"))
    if not is_plan_text and not is_yaml:
        await update.message.reply_text("Supported formats: .txt, .md (plan text) or .yaml/.yml (ready plan).")
        return

    # Rate limiting: cooldown between requests
    if state.last_request_time:
        elapsed = (datetime.now() - state.last_request_time).total_seconds()
        if elapsed < REQUEST_COOLDOWN_SEC:
            remaining = int(REQUEST_COOLDOWN_SEC - elapsed)
            await update.message.reply_text(
                f"Please wait {remaining} seconds before sending another plan."
            )
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
                f"Plan file is too long ({len(plan_text)} chars). "
                f"Maximum allowed: {MAX_PLAN_TEXT_LENGTH} chars."
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
            await update.message.reply_text(
                f"YAML plan loaded from {fname}.\n\nSend /build to generate FIT files."
            )
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
        await update.message.reply_text(f"File read error: {e}")


async def _process_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)

    try:
        state.status = "generating"
        state.active_plan_text = plan_text

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        llm = _build_llm_client()

        await update.message.reply_text("Checking LLM connection...")
        is_connected = await asyncio.to_thread(llm.check_connection)
        if not is_connected:
            await update.message.reply_text("Cannot connect to LLM server.")
            state.status = "idle"
            return

        await update.message.reply_text(f"Generating YAML (timeout: {LLM_TIMEOUT_SEC}s)...")
        try:
            draft = await asyncio.wait_for(
                asyncio.to_thread(build_plan_draft, llm, plan_text),
                timeout=LLM_TIMEOUT_SEC
            )
        except asyncio.TimeoutError:
            await update.message.reply_text(
                f"LLM generation timed out after {LLM_TIMEOUT_SEC} seconds. "
                "Try a shorter plan or check LLM server."
            )
            state.status = "idle"
            return

        if not draft.yaml_text or not isinstance(draft.data, dict):
            details = "\n".join(draft.validation_errors[:5]) or "Failed to generate valid YAML."
            await update.message.reply_text(f"Failed to generate valid YAML.\n{details}")
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
                f"YAML ready. Workouts: {workout_count}.\n\n"
                f"{preview}\n\n"
                "SBU block found. Reply with:\n"
                "- 'standard' to keep default drills\n"
                "- custom drill text to generate custom drills"
            )
            return

        if draft.ambiguities and not state.clarification_attempted:
            state.pending_clarification = "\n".join(f"• {a}" for a in draft.ambiguities[:5])
            state.status = "awaiting_clarification"
            await update.message.reply_text(
                f"YAML ready. Workouts: {workout_count}.\n\n"
                f"{preview}\n\n"
                f"Ambiguities found:\n{state.pending_clarification}\n\n"
                "Reply with clarification and I'll regenerate, or /build to proceed as-is."
            )
            return

        state.status = "awaiting_confirm"
        await update.message.reply_text(
            f"YAML ready. Workouts: {workout_count}.\n\n"
            f"{preview}\n\n"
            "If correct, send /build"
        )

    except Exception as e:
        state.status = "idle"
        await update.message.reply_text(f"Plan processing error: {e}")


async def _handle_garmin_email(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)
    email = text.strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text("That doesn't look like a valid email. Try again:")
        return
    state.garmin_pending_email = email
    state.status = "awaiting_garmin_password"
    await update.message.reply_text("Reply with your Garmin account password:")


async def _handle_garmin_password(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)
    password = text.strip()
    if not password:
        await update.message.reply_text("Password cannot be empty. Try again:")
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
        await update.message.reply_text("MFA session expired. Use /connect_garmin to start again.")
        return

    try:
        client = await asyncio.to_thread(manager.resume, mfa_code)
        state.garmin_client = client
        state.status = "idle"
        await update.message.reply_text(
            "Garmin Connect authenticated.\n"
            "Use /send_to_garmin after building a plan."
        )
    except Exception as exc:
        state.status = "idle"
        state.garmin_manager = None
        await update.message.reply_text(
            f"MFA failed: {exc}\n"
            "Use /connect_garmin to try again."
        )


async def _handle_sbu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)
    yaml_data = state.pending_sbu_yaml_data

    if not isinstance(yaml_data, dict):
        state.status = "idle"
        state.pending_sbu_yaml_data = None
        await update.message.reply_text("SBU state expired. Send plan again.")
        return

    if user_text.strip().lower() in ("standard", "default", "1", "стандарт"):
        state.pending_sbu_yaml_data = None
        if state.yaml_text is None:
            state.status = "idle"
            await update.message.reply_text("YAML state expired. Send plan again.")
            return

        preview = state.yaml_text[:1500] + "..." if state.yaml_text and len(state.yaml_text) > 1500 else state.yaml_text
        ambiguities = state.pending_ambiguities[:5]
        if ambiguities and not state.clarification_attempted:
            state.pending_ambiguities = list(ambiguities)
            state.pending_clarification = "\n".join(f"• {a}" for a in ambiguities)
            state.status = "awaiting_clarification"
            await update.message.reply_text(
                f"Using standard SBU.\n\n{preview}\n\n"
                f"Ambiguities found:\n{state.pending_clarification}\n\n"
                "Reply with clarification and I'll regenerate, or /build to proceed as-is."
            )
            return

        state.pending_clarification = None
        state.status = "awaiting_confirm"
        await update.message.reply_text(f"Using standard SBU.\n\n{preview}\n\nSend /build")
        return

    try:
        llm = _build_llm_client()
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await update.message.reply_text("Parsing custom drills...")

        draft = await asyncio.to_thread(apply_custom_sbu_choice, llm, yaml_data, user_text)
        state.yaml_text = draft.yaml_text
        state.pending_sbu_yaml_data = None
        state.pending_ambiguities = list(draft.ambiguities)

        preview = format_plan_preview(draft)
        if draft.ambiguities and not state.clarification_attempted:
            state.pending_clarification = "\n".join(f"• {a}" for a in draft.ambiguities[:5])
            state.status = "awaiting_clarification"
            await update.message.reply_text(
                f"Custom drills added.\n\n{preview}\n\n"
                f"Ambiguities found:\n{state.pending_clarification}\n\n"
                "Reply with clarification and I'll regenerate, or /build to proceed as-is."
            )
            return

        state.pending_clarification = None
        state.status = "awaiting_confirm"
        await update.message.reply_text(f"Custom drills added.\n\n{preview}\n\nSend /build")

    except Exception as e:
        # Stay in awaiting_sbu_choice so user can retry or type 'standard'
        await update.message.reply_text(
            f"SBU processing error: {e}\n"
            "Try again with different text, or send 'standard' for default drills."
        )


async def _handle_clarification(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)

    if not state.active_plan_text:
        state.status = "idle"
        await update.message.reply_text("Context expired. Please send the plan again.")
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
        # User chose to skip clarification and build as-is
        state.status = "awaiting_confirm"

    if state.status not in {"awaiting_confirm", "queued"}:
        await update.message.reply_text("No confirmed YAML plan. Send plan text first.")
        return

    if state.status == "queued":
        await update.message.reply_text("Build job is already queued.")
        return

    state.cancel_requested = False
    state.status = "queued"
    await BUILD_QUEUE.put(BuildJob(chat_id=update.effective_chat.id, user_id=user_id))
    await update.message.reply_text(f"Build queued. Position: {BUILD_QUEUE.qsize()}")


async def _execute_build_job(application: Application, job: BuildJob) -> None:
    state = get_state(job.user_id)
    if state.status != "queued":
        return
    if state.cancel_requested:
        state.status = "idle"
        state.cancel_requested = False
        await application.bot.send_message(chat_id=job.chat_id, text="Build cancelled.")
        return

    if not state.yaml_text:
        state.status = "idle"
        await application.bot.send_message(chat_id=job.chat_id, text="Queued build skipped: no YAML in state.")
        return

    state.status = "building"

    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        yaml_filename = f"plan_u{job.user_id}_{ts}.yaml"
        yaml_path = save_yaml_to_plan_dir(state.yaml_text, yaml_filename)
        state.yaml_path = yaml_path

        await application.bot.send_message(
            chat_id=job.chat_id,
            text="Running pipeline: YAML -> direct FIT build -> validate",
        )

        result = await asyncio.to_thread(run_pipeline, yaml_path)
        if state.cancel_requested:
            state.status = "idle"
            state.cancel_requested = False
            await application.bot.send_message(chat_id=job.chat_id, text="Build cancelled.")
            return
        if not result.get("success"):
            errors = "\n".join(result.get("errors", [])) or "Unknown error"
            await application.bot.send_message(chat_id=job.chat_id, text=f"Build failed:\n{errors}")
            state.status = "idle"
            return

        fit_files = result.get("fit_files", [])
        state.fit_files = fit_files

        if not fit_files:
            await application.bot.send_message(chat_id=job.chat_id, text="Build finished but no FIT files generated.")
            state.status = "idle"
            return

        if state.cancel_requested:
            state.status = "idle"
            state.cancel_requested = False
            await application.bot.send_message(chat_id=job.chat_id, text="Build cancelled.")
            return

        await application.bot.send_message(
            chat_id=job.chat_id,
            text=(
                f"Build done.\n"
                f"Build path: {result.get('build_mode', 'direct')}\n"
                f"Planned workouts: {result.get('build_total_count', 0)}\n"
                f"FIT files: {len(fit_files)}\n"
                f"Valid: {result.get('valid_count', 0)}/{result.get('total_count', 0)}"
            ),
        )

        now = datetime.now()
        zip_name = f"garmin_{now.strftime('%Y-%m')}_u{job.user_id}_{ts}.zip"
        zip_path = Path(gettempdir()) / zip_name
        _create_plan_zip(zip_path, state.original_plan_text, fit_files, now)
        try:
            with open(zip_path, "rb") as f:
                await application.bot.send_document(
                    chat_id=job.chat_id,
                    document=f,
                    filename=zip_path.name,
                    caption=f"{len(fit_files)} FIT file(s)",
                )
        finally:
            zip_path.unlink(missing_ok=True)

        if state.cancel_requested:
            state.status = "idle"
            state.cancel_requested = False
            await application.bot.send_message(chat_id=job.chat_id, text="Build cancelled before archiving.")
            return

        archive_name = get_archive_name(plan_name=yaml_path.stem, owner_tag=job.user_id)
        archive_path = archive_current_plan(
            archive_name=archive_name,
            run_id=f"tg_u{job.user_id}_{ts}",
            owner_tag=job.user_id,
            plan_paths=[yaml_path],
            artifact_paths=result.get("artifact_paths", []),
        )

        garmin_hint = ""
        state_check = get_state(job.user_id)
        if state_check.garmin_client:
            garmin_hint = "\n\nUse /send_to_garmin to upload to Garmin Calendar."
        elif _garmin_auth_available():
            garmin_hint = "\n\nTip: /connect_garmin to upload directly to Garmin Calendar (no USB)."

        await application.bot.send_message(
            chat_id=job.chat_id,
            text=(
                f"Done. Sent {len(fit_files)} file(s).\n"
                f"Archive: {archive_path.name}"
                f"{garmin_hint}"
            ),
        )

    except Exception as e:
        await application.bot.send_message(chat_id=job.chat_id, text=f"Build execution error: {e}")
    finally:
        state.cancel_requested = False
        state.status = "idle"


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
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("Bot is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
