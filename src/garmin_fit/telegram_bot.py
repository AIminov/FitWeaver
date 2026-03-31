"""
Telegram Bot for Garmin FIT Generator.
Accepts plan text -> generates YAML via LLM (LM Studio/Ollama) -> builds FIT files.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from typing import Dict, List, Optional
from zipfile import ZIP_DEFLATED, ZipFile

import yaml
from telegram import Document, InputMediaDocument, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .archive_manager import archive_current_plan, get_archive_name
from .generate_from_yaml import generate_all_templates
from .llm.client import UnifiedLLMClient
from .pipeline_runner import run_pipeline, save_yaml_to_plan_dir
from .plan_service import (
    apply_custom_sbu_choice,
    build_plan_draft,
    count_workouts,
    format_plan_preview,
    has_default_sbu_block,
)
from .config import TEMPLATES_DIR, PLAN_DIR, OUTPUT_DIR, ARCHIVE_DIR, ARTIFACTS_DIR, BOT_CONFIG_FILE

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
    status: str = "idle"  # idle/generating/awaiting_sbu_choice/awaiting_confirm/queued/building
    generated_at: Optional[datetime] = None
    fit_files: List[Path] = field(default_factory=list)
    pending_sbu_yaml_data: Optional[dict] = None
    cancel_requested: bool = False
    last_request_time: Optional[datetime] = None


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


def _create_plan_zip(
    zip_path: Path,
    yaml_path: Optional[Path],
    fit_files: List[Path],
    artifact_paths: Optional[List[Path]] = None,
) -> None:
    """Create ZIP with generated plan artifacts for bulk download."""
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        if yaml_path and yaml_path.exists():
            archive.write(yaml_path, arcname=f"plan/{yaml_path.name}")

        for artifact_path in sorted(Path(path) for path in (artifact_paths or [])):
            if artifact_path.exists() and artifact_path.is_file():
                archive.write(artifact_path, arcname=f"artifacts/{artifact_path.name}")

        template_files = sorted(TEMPLATES_DIR.glob("*.py"))
        if template_files:
            for template_file in template_files:
                archive.write(template_file, arcname=f"templates/{template_file.name}")
        elif yaml_path and yaml_path.exists():
            with TemporaryDirectory(prefix="garmin_templates_") as tmp:
                temp_dir = Path(tmp)
                generated, total = generate_all_templates(
                    yaml_path,
                    output_dir=temp_dir,
                    cleanup_output=True,
                )
                if total > 0 and generated == total:
                    for template_file in sorted(temp_dir.glob("*.py")):
                        archive.write(template_file, arcname=f"templates/{template_file.name}")

        for fit_file in fit_files:
            archive.write(fit_file, arcname=f"fit/{fit_file.name}")


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
        "/start\n"
        "/help\n"
        "/status\n"
        "/cancel\n"
        "/build"
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

    if state.status == "awaiting_sbu_choice":
        await _handle_sbu_choice(update, context, text)
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
    if not document.file_name or not document.file_name.endswith((".txt", ".md")):
        await update.message.reply_text("Only .txt and .md files are supported.")
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

        state.last_request_time = datetime.now()
        await _process_plan(update, context, plan_text)

    except Exception as e:
        await update.message.reply_text(f"File read error: {e}")


async def _process_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)

    try:
        state.status = "generating"

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

        state.status = "awaiting_confirm"
        await update.message.reply_text(
            f"YAML ready. Workouts: {workout_count}.\n\n"
            f"{preview}\n\n"
            "If correct, send /build"
        )

    except Exception as e:
        state.status = "idle"
        await update.message.reply_text(f"Plan processing error: {e}")


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
        state.status = "awaiting_confirm"
        state.pending_sbu_yaml_data = None
        preview = state.yaml_text[:1500] + "..." if len(state.yaml_text) > 1500 else state.yaml_text
        await update.message.reply_text(f"Using standard SBU.\n\n{preview}\n\nSend /build")
        return

    try:
        llm = _build_llm_client()
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await update.message.reply_text("Parsing custom drills...")

        draft = await asyncio.to_thread(apply_custom_sbu_choice, llm, yaml_data, user_text)
        state.yaml_text = draft.yaml_text
        state.status = "awaiting_confirm"
        state.pending_sbu_yaml_data = None

        preview = format_plan_preview(draft)
        await update.message.reply_text(f"Custom drills added.\n\n{preview}\n\nSend /build")

    except Exception as e:
        # Stay in awaiting_sbu_choice so user can retry or type 'standard'
        await update.message.reply_text(
            f"SBU processing error: {e}\n"
            "Try again with different text, or send 'standard' for default drills."
        )


async def build(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_user_allowed(update):
        return

    user_id = update.effective_user.id
    state = get_state(user_id)

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

        if len(fit_files) <= 10:
            media = []
            file_handles = []
            try:
                for idx, fit_path in enumerate(fit_files):
                    handle = open(fit_path, "rb")
                    file_handles.append(handle)
                    caption = f"FIT files: {len(fit_files)}" if idx == 0 else None
                    media.append(InputMediaDocument(media=handle, filename=fit_path.name, caption=caption))
                await application.bot.send_media_group(chat_id=job.chat_id, media=media)
            finally:
                for handle in file_handles:
                    handle.close()
        else:
            zip_path = Path(gettempdir()) / f"plan_bundle_u{job.user_id}_{ts}.zip"
            artifact_paths = result.get("artifact_paths", [])
            _create_plan_zip(zip_path, state.yaml_path, fit_files, artifact_paths)
            try:
                with open(zip_path, "rb") as f:
                    await application.bot.send_document(
                        chat_id=job.chat_id,
                        document=f,
                        filename=zip_path.name,
                        caption=f"Bundle with {len(fit_files)} FIT files and plan artifacts",
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

        await application.bot.send_message(
            chat_id=job.chat_id,
            text=(
                f"Done. Sent {len(fit_files)} file(s).\n"
                f"Archive: {archive_path.name}"
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
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("Bot is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
