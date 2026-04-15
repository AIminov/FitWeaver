"""
Garmin Connect authentication manager.

Wraps garmin-auth (drkostas) to provide a simple connect() interface
for both local (FileTokenStore) and cloud/Telegram (DBTokenStore) use cases.

Dependencies (optional — graceful error if not installed):
    garmin-auth >= 0.3.0
    garminconnect >= 0.3.0

Usage:
    # Local (tokens saved to ~/.garminconnect/garmin_tokens.json):
    manager = GarminAuthManager.from_env()
    client = manager.connect()

    # Interactive MFA (CLI):
    manager = GarminAuthManager(email, password,
                                prompt_mfa=lambda: input("MFA: "))
    client = manager.connect()

    # Async MFA (Telegram bot):
    manager = GarminAuthManager(email, password, return_on_mfa=True)
    result = manager.connect()
    if result == "needs_mfa":
        client = manager.resume(mfa_code)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_GARMIN_AUTH_AVAILABLE = False
try:
    from garmin_auth import GarminAuth  # type: ignore[import]
    from garmin_auth.storage import FileTokenStore  # type: ignore[import]
    _GARMIN_AUTH_AVAILABLE = True
except ImportError:
    pass


def _require_garmin_auth() -> None:
    if not _GARMIN_AUTH_AVAILABLE:
        raise ImportError(
            "garmin-auth is not installed. "
            "Run: pip install garmin-auth"
        )


class GarminAuthManager:
    """
    Thin wrapper over garmin-auth GarminAuth.

    Parameters
    ----------
    email:
        Garmin account email. Falls back to GARMIN_EMAIL env var if None.
    password:
        Garmin account password. Falls back to GARMIN_PASSWORD env var if None.
    token_dir:
        Directory for FileTokenStore. Defaults to ~/.garminconnect/.
    prompt_mfa:
        Callable that returns an MFA code string (blocking). Used for CLI.
    return_on_mfa:
        If True, connect() returns the string "needs_mfa" instead of blocking.
        Caller must then call resume(mfa_code). Used for Telegram bot.
    store:
        Override token store entirely (e.g., DBTokenStore for PostgreSQL).
    """

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        token_dir: Path | None = None,
        prompt_mfa: Callable[[], str] | None = None,
        return_on_mfa: bool = False,
        store: Any = None,
    ) -> None:
        _require_garmin_auth()
        self._email = email or os.environ.get("GARMIN_EMAIL")
        self._password = password or os.environ.get("GARMIN_PASSWORD")
        self._token_dir = token_dir
        self._prompt_mfa = prompt_mfa
        self._return_on_mfa = return_on_mfa
        self._store = store
        self._auth: Any = None

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        token_dir: Path | None = None,
        prompt_mfa: Callable[[], str] | None = None,
    ) -> "GarminAuthManager":
        """Create from GARMIN_EMAIL / GARMIN_PASSWORD environment variables."""
        return cls(token_dir=token_dir, prompt_mfa=prompt_mfa)

    @classmethod
    def for_telegram(
        cls,
        email: str,
        password: str,
        token_dir: Path | None = None,
    ) -> "GarminAuthManager":
        """Create for Telegram bot use — async MFA (return_on_mfa=True)."""
        return cls(email=email, password=password,
                   token_dir=token_dir, return_on_mfa=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> Any:
        """
        Authenticate with Garmin Connect.

        Returns
        -------
        garminconnect.Garmin
            Authenticated client ready to use.
        str
            Literal "needs_mfa" if return_on_mfa=True and MFA is required.
        """
        self._auth = self._build_auth()
        result = self._auth.login()
        if result == "needs_mfa":
            logger.info("Garmin MFA required — waiting for code")
            return "needs_mfa"
        logger.info("Garmin Connect authenticated")
        return result

    def resume(self, mfa_code: str) -> Any:
        """
        Complete MFA flow after connect() returned "needs_mfa".

        Parameters
        ----------
        mfa_code:
            One-time code from the authenticator app or SMS.

        Returns
        -------
        garminconnect.Garmin
            Authenticated client.
        """
        if self._auth is None:
            raise RuntimeError("Call connect() before resume()")
        client = self._auth.resume_login(mfa_code)
        logger.info("Garmin Connect authenticated (MFA completed)")
        return client

    def status(self) -> dict[str, Any]:
        """Return stored token metadata without triggering a login."""
        auth = self._build_auth()
        return auth.status()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_auth(self) -> Any:
        kwargs: dict[str, Any] = {}
        if self._email:
            kwargs["email"] = self._email
        if self._password:
            kwargs["password"] = self._password
        if self._return_on_mfa:
            kwargs["return_on_mfa"] = True
        elif self._prompt_mfa:
            kwargs["prompt_mfa"] = self._prompt_mfa

        if self._store is not None:
            kwargs["store"] = self._store
        elif self._token_dir is not None:
            kwargs["store"] = FileTokenStore(str(self._token_dir))

        return GarminAuth(**kwargs)


def is_available() -> bool:
    """Return True if garmin-auth and garminconnect are installed."""
    return _GARMIN_AUTH_AVAILABLE
