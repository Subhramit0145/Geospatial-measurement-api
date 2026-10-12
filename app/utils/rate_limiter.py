"""
High-Performance Rate Limiter.

Protects the API against burst traffic and denial-of-service degradation
under extreme loads (e.g. 100,000 requests) while maintaining minimal overhead.
Uses an in-memory sliding window counter per client IP.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from fastapi import HTTPException, Request, status

from app.config import settings


class SlidingWindowRateLimiter:
    """
    Thread-safe sliding-window rate limiter per client IP.
    """

    def __init__(self, max_requests: int = 10000, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, client_ip: str) -> tuple[bool, int]:
        """
        Check if request is allowed.
        Returns (is_allowed, retry_after_seconds).
        """
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._clients.get(client_ip, [])
            # Filter out timestamps outside window
            valid_timestamps = [ts for ts in timestamps if ts > cutoff]

            if len(valid_timestamps) >= self.max_requests:
                oldest = valid_timestamps[0]
                retry_after = max(1, int(self.window_seconds - (now - oldest)))
                self._clients[client_ip] = valid_timestamps
                return False, retry_after

            valid_timestamps.append(now)
            self._clients[client_ip] = valid_timestamps

            # Periodic cleanup of inactive clients to prevent memory leaks
            if len(self._clients) > 10000:
                self._cleanup(cutoff)

            return True, 0

    def _cleanup(self, cutoff: float) -> None:
        """Purge idle IPs from tracking dictionary."""
        idle_ips = [ip for ip, timestamps in self._clients.items() if not timestamps or timestamps[-1] <= cutoff]
        for ip in idle_ips:
            del self._clients[ip]

    def reset(self) -> None:
        with self._lock:
            self._clients.clear()


limiter = SlidingWindowRateLimiter(
    max_requests=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window_seconds,
)


def rate_limit_dependency(request: Request):
    """
    FastAPI dependency enforcing rate limits when enabled in settings.
    """
    if not settings.rate_limit_enabled:
        return

    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.is_allowed(client_ip)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
