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

import yaml

from .config import PROJECT_ROOT, USER_PROFILE

PROFILES_ROOT = PROJECT_ROOT / "profiles"

# Simple % of max-HR split (Z1 recovery .. Z5 anaerobic). Not physiologically
# authoritative — just a reasonable, well-known default a user can hand-edit
# in their profile's user_profile.yaml afterwards.
_ZONE_PERCENTS = [
    ("zone1", 0.50, 0.60),
    ("zone2", 0.60, 0.70),
    ("zone3", 0.70, 0.80),
    ("zone4", 0.80, 0.90),
    ("zone5", 0.90, 1.00),
]


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


def user_templates_path(email: str) -> Path:
    return profile_dir(email) / "templates.json"


def list_user_templates(email: str) -> dict[str, list[dict]]:
    """Personal workout-builder templates for this profile: name -> list of
    step dicts (plan_domain.step_to_data() shape, JSON-serializable)."""
    path = user_templates_path(email)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_user_template(email: str, name: str, steps_data: list[dict]) -> None:
    templates = list_user_templates(email)
    templates[name] = steps_data
    user_templates_path(email).write_text(
        json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def delete_user_template(email: str, name: str) -> None:
    templates = list_user_templates(email)
    templates.pop(name, None)
    user_templates_path(email).write_text(
        json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8"
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


def has_user_profile(email: str) -> bool:
    return user_profile_yaml_path(email).exists()


def compute_hr_zones(max_hr: int) -> dict:
    return {
        name: {"low": round(max_hr * lo), "high": round(max_hr * hi)}
        for name, lo, hi in _ZONE_PERCENTS
    }


def write_user_profile(email: str, max_hr: int, resting_hr: int) -> None:
    """Write this profile's personal HR data, deriving zone ranges from max_hr.

    Format matches user_profile.yaml.example so a user can still hand-edit
    the result (e.g. to plug in lab-measured zones instead of the % split)."""
    data = {
        "max_hr": max_hr,
        "resting_hr": resting_hr,
        "hr_zones": compute_hr_zones(max_hr),
    }
    user_profile_yaml_path(email).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def mark_user_profile_skipped(email: str) -> None:
    """Record that onboarding was explicitly skipped, so the GUI doesn't
    prompt again on every activation. An empty/comment-only file parses to
    None via yaml.safe_load, which load_user_profile()'s callers already
    treat the same as "no personal HR zones configured"."""
    user_profile_yaml_path(email).write_text(
        "# no personal HR profile -- skipped during onboarding\n", encoding="utf-8"
    )


def _legacy_migration_marker() -> Path:
    return PROFILES_ROOT / ".legacy_migrated"


def migrate_legacy_user_profile(email: str) -> bool:
    """One-time convenience: if this profile has no personal HR file yet but
    a legacy global user_profile.yaml already exists (from before multi-profile
    support existed), copy it into the profile instead of prompting the user
    to re-enter data they already have on disk. Returns True if it migrated
    something.

    activate_user_profile() overwrites the global slot with whichever profile
    is currently active, so after the first real activation that file no
    longer represents "unclaimed legacy data" -- it just reflects the last
    active profile, and would otherwise look like fresh "legacy data" to
    steal for every subsequent new profile. A marker file makes the claim
    permanent and global (not per-profile), so this can only ever fire once
    across all profiles; the original file is also removed so it doesn't
    linger looking like unclaimed data (activate_user_profile() recreates it
    immediately afterward from the now-migrated profile, so nothing is lost).
    """
    dest = user_profile_yaml_path(email)
    if dest.exists():
        return False
    marker = _legacy_migration_marker()
    if marker.exists():
        return False
    if not USER_PROFILE.exists():
        return False
    shutil.copyfile(USER_PROFILE, dest)
    USER_PROFILE.unlink()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(email, encoding="utf-8")
    return True
