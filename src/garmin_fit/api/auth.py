"""Shared-secret auth. Binary allow/deny -- no authz tiers."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request


def require_api_token(request: Request, x_api_token: str | None = Header(default=None)) -> None:
    settings = request.app.state.settings
    # compare_digest: constant-time, so response timing does not leak the token.
    if not x_api_token or not hmac.compare_digest(
        x_api_token.encode("utf-8"), str(settings.api_token).encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Token header")
