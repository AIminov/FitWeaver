"""In-memory token-bucket rate limiter.

Bucket state lives on app.state.rate_limit_buckets (set up per create_app()
call), not a module-level dict -- keeps tests isolated across separate
create_app() instances and avoids cross-test leakage. Keyed by the caller's
API token; requests with no/wrong token are already rejected by auth.py
before this dependency would matter, but FastAPI resolves dependencies in
declaration order per route, so this still runs after require_api_token
when both are declared on the same route.
"""

from __future__ import annotations

import threading
import time

from fastapi import Header, HTTPException, Request

_lock = threading.Lock()


def enforce_rate_limit(request: Request, x_api_token: str | None = Header(default=None)) -> None:
    settings = request.app.state.settings
    buckets: dict[str, tuple[float, float]] = request.app.state.rate_limit_buckets
    rate_per_min = settings.rate_limit_per_minute
    burst = settings.rate_limit_burst
    key = x_api_token or "anonymous"
    now = time.monotonic()
    refill_rate = rate_per_min / 60.0

    with _lock:
        tokens, last = buckets.get(key, (float(burst), now))
        tokens = min(burst, tokens + (now - last) * refill_rate)
        if tokens < 1.0:
            buckets[key] = (tokens, now)
            raise HTTPException(status_code=429, detail="Rate limit exceeded, try again shortly")
        buckets[key] = (tokens - 1.0, now)
