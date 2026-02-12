"""Request logging / audit middleware."""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from typing import Callable

from core.logging_config import clear_request_context, set_request_context
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

access_logger = logging.getLogger("nexus.access")


class AuditMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status, duration, and request ID."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        request.state.request_id = request_id
        start = time.monotonic()

        # Set context for structured JSON logging
        set_request_context(
            request_id=request_id,
            method=request.method,
            path=str(request.url.path),
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.monotonic() - start) * 1000
            access_logger.error(
                "%s %s -> 500 (%.1fms) [rid:%s]\n%s",
                request.method,
                request.url.path,
                duration_ms,
                request_id,
                traceback.format_exc(),
            )
            clear_request_context()
            raise

        duration_ms = (time.monotonic() - start) * 1000
        status = response.status_code
        log_fn = access_logger.warning if status >= 400 else access_logger.info
        log_fn(
            "%s %s -> %d (%.1fms) [rid:%s] ip:%s",
            request.method,
            request.url.path,
            status,
            duration_ms,
            request_id,
            request.client.host if request.client else "unknown",
        )
        response.headers["X-Request-ID"] = request_id
        clear_request_context()
        return response
