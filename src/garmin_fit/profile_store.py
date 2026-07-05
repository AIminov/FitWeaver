"""Per-user profile isolation for the desktop GUI.

Lets several people share one PC, each with their own working plan, HR zones,
and Garmin session — keyed by Garmin email, since that's already the identity
the whole app revolves around (workout upload/delete is per Garmin account).

Garmin token caching already isolates by an email slug (see
workflow._resolve_garmin_token_dir). This module reuses the exact same slug
formula so a profile directory and its Garmin token cache always agree, and
extends the same isolation to GUI-local state: the last opened plan, the
active year, and personal HR zones.

LLM connection settings (server URL/model/timeout) are deliberately NOT
part of a profile — they describe the local LLM server running on this
machine, not the person using it, and stay shared across all profiles.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .config import PROJECT_ROOT, USER_PROFILE

PROFILES_ROOT = PROJECT_ROOT / "profiles"


def email_slug(email: str) -> str:
    """Stable short slug for an email — same formula as the Garmin token dir
    (workflow._resolve_garmin_token_dir), so both stay consistent for the
    same account."""
    return hashlib.md5(email.strip().lower().encode()).hexdigest()[:8]


def profile_dir(email: str) -> Path:
    d = PROFILES_ROOT / email_slug(email)
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_profiles() -> list[str]:
    """Known emails, read back from each profile's saved session.json."""
    if not PROFILES_ROOT.exists():
        return []
    emails = []
    for child in sorted(PROFILES_ROOT.iterdir()):
        if not child.is_dir():
            continue
        session_path = child / "session.json"
        if not session_path.exists():
            continue
        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("email"):
            emails.append(data["email"])
    return emails


def load_session(email: str) -> dict:
    session_path = profile_dir(email) / "session.json"
    if not session_path.exists():
        return {}
    try:
        return json.loads(session_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_session(email: str, data: dict) -> None:
    payload = dict(data)
    payload["email"] = email
    session_path = profile_dir(email) / "session.json"
    session_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def user_profile_yaml_path(email: str) -> Path:
    return profile_dir(email) / "user_profile.yaml"


def activate_user_profile(email: str) -> None:
    """Make this profile's personal HR zones the ones the LLM prompt sees.

    workout_utils.load_user_profile() (used by the Telegram bot and the CLI,
    not just the GUI) always reads the single global config.USER_PROFILE
    path with no arguments. Rather than thread a new path parameter through
    that shared chain (plan_service -> llm/prompt.py -> workout_utils),
    which the bot also depends on, this copies the active profile's
    user_profile.yaml into that one global slot. Only one person drives the
    GUI at a time on a shared PC, so "whoever is active in the GUI" is the
    correct owner of that global file for the duration of their session —
    same assumption the project already made before profiles existed.
    """
    src = user_profile_yaml_path(email)
    if src.exists():
        USER_PROFILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, USER_PROFILE)
