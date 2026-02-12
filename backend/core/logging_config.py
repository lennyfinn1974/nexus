"""Structured JSON logging for Nexus.

Provides a JSONFormatter that outputs log records as single-line JSON objects,
plus a ContextFilter that injects request_id from the current request context.

Usage:
    Configured automatically via app.py at startup.
    JSON logs go to backend/logs/nexus.jsonl (JSON Lines format).
    Human-readable logs still go to backend/logs/access.log.
"""

from __future__ import annotations

import json
import logging
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone

# Context variable for request-scoped data
_request_id: ContextVar[str] = ContextVar("request_id", default="")
_request_method: ContextVar[str] = ContextVar("request_method", default="")
_request_path: ContextVar[str] = ContextVar("request_path", default="")


def set_request_context(request_id: str = "", method: str = "", path: str = "") -> None:
    """Set request context vars (called from audit middleware)."""
    _request_id.set(request_id)
    _request_method.set(method)
    _request_path.set(path)


def clear_request_context() -> None:
    """Clear request context vars after request completes."""
    _request_id.set("")
    _request_method.set("")
    _request_path.set("")


class ContextFilter(logging.Filter):
    """Inject request context into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get("")  # type: ignore[attr-defined]
        record.request_method = _request_method.get("")  # type: ignore[attr-defined]
        record.request_path = _request_path.get("")  # type: ignore[attr-defined]
        return True


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON (JSON Lines / .jsonl).

    Output schema:
        {
            "ts": "2026-02-11T09:30:00.123456Z",
            "level": "INFO",
            "logger": "nexus.access",
            "msg": "GET /api/status -> 200",
            "request_id": "4d4ae9bfd09a",
            "method": "GET",
            "path": "/api/status",
            "exc": null
        }
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

        entry = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "") or "",
            "method": getattr(record, "request_method", "") or "",
            "path": getattr(record, "request_path", "") or "",
        }

        # Include exception info if present
        if record.exc_info and record.exc_info[1]:
            entry["exc"] = traceback.format_exception(*record.exc_info)
        elif record.exc_text:
            entry["exc"] = record.exc_text

        return json.dumps(entry, default=str)
