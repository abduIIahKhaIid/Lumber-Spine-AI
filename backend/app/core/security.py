"""Local reviewer key for the case library, plus a small per-client rate limiter."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Header, HTTPException, Request

from app.core.config import get_settings


def authorize(x_review_key: str = Header(default="")) -> str:
    settings = get_settings()
    if not settings.review_access_token:
        raise HTTPException(
            503,
            "Set REVIEW_ACCESS_TOKEN and REVIEWER_NAME in backend/.env to enable the case library.",
        )
    if not hmac.compare_digest(settings.review_access_token, x_review_key):
        raise HTTPException(401, "Invalid review access key")
    return settings.reviewer_name


class RateLimiter:
    """Sliding one-minute window per client address. Process-local by design."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, limit: int, window: float = 60.0) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                retry = max(1, int(window - (now - hits[0])))
                raise HTTPException(
                    429, "Too many requests. Please wait a moment.", {"Retry-After": str(retry)}
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limited(scope: str):
    def dependency(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        limiter.check(f"{scope}:{client}", get_settings().rate_limit_per_minute)

    return dependency
