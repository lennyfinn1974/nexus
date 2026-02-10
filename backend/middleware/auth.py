"""Optional bearer token authentication middleware for /api/* routes.

Disabled by default -- if API_AUTH_TOKEN is not set, all requests pass through.
When enabled, validates Authorization: Bearer <token> on /api/* endpoints.
Skips: WebSocket /ws/*, frontend routes (/, /admin), and GET /api/health.
Admin routes keep their own stricter ADMIN_API_KEY check (layered security).
"""

from __future__ import annotations

import os
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Paths that bypass auth even when token is configured
_SKIP_PATHS = {"/", "/admin", "/api/health"}
_SKIP_PREFIXES = ("/ws/", "/static/")


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer token auth for API routes (opt-in via API_AUTH_TOKEN env var)."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        token = os.environ.get("API_AUTH_TOKEN", "")
        if not token:
            # Auth disabled -- pass through
            return await call_next(request)

        path = request.url.path

        # Skip non-API paths
        if path in _SKIP_PATHS:
            return await call_next(request)
        for prefix in _SKIP_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # Only enforce on /api/* paths
        if not path.startswith("/api/"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )

        provided = auth_header[7:]
        if provided != token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid API token"},
            )

        return await call_next(request)
