"""Shared-secret auth. Binary allow/deny -- no authz tiers."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request


def require_api_token(request: Request, x_api_token: str | None = Header(default=None)) -> None:
    settings = request.app.state.settings
    if not x_api_token or x_api_token != settings.api_token:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Token header")
