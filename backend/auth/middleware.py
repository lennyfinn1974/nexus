"""Auth enforcement middleware — HTTP + WebSocket."""
from __future__ import annotations

import logging

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse

logger = logging.getLogger("nexus.auth.middleware")

# Routes that never require authentication
PUBLIC_PATHS = {
    "/api/health",
    "/healthz",
}
PUBLIC_PREFIXES = (
    "/api/auth/",
)


class AuthMiddleware:
    """HTTP middleware that validates JWT when auth is enabled.

    Checks Authorization header and nexus_access_token cookie.
    Sets request.state.user on success.
    """

    def __init__(self, app, cfg, jwt_manager):
        self.app = app
        self._cfg = cfg
        self._jwt = jwt_manager

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http",):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        path = request.url.path

        # Auth disabled — pass through
        if not self._cfg.auth_enabled:
            scope["state"] = getattr(scope, "state", {})
            if isinstance(scope.get("state"), dict):
                scope["state"]["user"] = None
            await self.app(scope, receive, send)
            return

        # Public routes — no auth required
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return

        # Static assets (frontend files) — let the route handler decide
        if not path.startswith("/api/") and path not in ("/", "/admin"):
            await self.app(scope, receive, send)
            return

        # Extract token from header or cookie
        token = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            token = request.cookies.get("nexus_access_token")

        if not token:
            # For HTML pages, let the route handler deal with redirect
            if path in ("/", "/admin"):
                await self.app(scope, receive, send)
                return
            response = JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        claims = self._jwt.verify_access_token(token)
        if not claims:
            if path in ("/", "/admin"):
                await self.app(scope, receive, send)
                return
            response = JSONResponse(
                {"detail": "Invalid or expired token"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        # Attach user claims to request state
        if not isinstance(scope.get("state"), dict):
            scope["state"] = {}
        scope["state"]["user"] = claims
        await self.app(scope, receive, send)


async def authenticate_websocket(ws: WebSocket, jwt_manager) -> dict | None:
    """Validate token from query param for WebSocket handshake.

    Returns user claims dict or None.
    """
    token = ws.query_params.get("token", "")
    if not token:
        return None

    claims = jwt_manager.verify_ws_token(token)
    if claims:
        return claims

    # Also try access token as fallback
    claims = jwt_manager.verify_access_token(token)
    return claims
