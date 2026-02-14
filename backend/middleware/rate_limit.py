"""Rate limiting middleware with sliding-window counters."""

from __future__ import annotations

import collections
import time
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class RateLimiter:
    """Simple in-memory sliding-window rate limiter keyed by IP address."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, collections.deque] = {}

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Return (allowed, remaining) for *key*."""
        now = time.monotonic()
        q = self._hits.setdefault(key, collections.deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        remaining = max(0, self.max_requests - len(q))
        if len(q) >= self.max_requests:
            return False, 0
        q.append(now)
        return True, remaining - 1


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that rate-limits /api/* requests."""

    def __init__(
        self,
        app: ASGIApp,
        general_limit: int = 60,
        admin_limit: int = 30,
        auth_limit: int = 5,
        window_seconds: int = 60,
    ):
        super().__init__(app)
        self._general = RateLimiter(general_limit, window_seconds)
        self._admin = RateLimiter(admin_limit, window_seconds)
        self._auth = RateLimiter(auth_limit, window_seconds)

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        if path.startswith("/api/auth/"):
            allowed, remaining = self._auth.is_allowed(client_ip)
        elif path.startswith("/api/admin/"):
            allowed, remaining = self._admin.is_allowed(client_ip)
        else:
            allowed, remaining = self._general.is_allowed(client_ip)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too Many Requests"},
                headers={
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(self._general.window),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
