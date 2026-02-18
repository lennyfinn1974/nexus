"""Structured JSON logging for Nexus.

Provides a JSONFormatter that outputs log records as single-line JSON objects,
plus a ContextFilter that injects request_id and turn trace context.

Usage:
    Configured automatically via app.py at startup.
    JSON logs go to backend/logs/nexus.jsonl (JSON Lines format).
    Human-readable logs still go to backend/logs/access.log.

Turn Tracing:
    Every conversation turn gets a unique turn_id (12-char hex) that flows
    through the entire pipeline: ws.py → AgentRunner → AgentAttempt →
    tool_executor → plugins. This enables correlating all log lines for
    a single user interaction.
"""

from __future__ import annotations

import json
import logging
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

# Context variable for request-scoped data
_request_id: ContextVar[str] = ContextVar("request_id", default="")
_request_method: ContextVar[str] = ContextVar("request_method", default="")
_request_path: ContextVar[str] = ContextVar("request_path", default="")

# Turn trace context — set once per conversation turn in ws.py
_turn_id: ContextVar[str] = ContextVar("turn_id", default="")
_conv_id: ContextVar[str] = ContextVar("conv_id", default="")
_ws_id: ContextVar[str] = ContextVar("ws_id", default="")


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


def set_turn_context(turn_id: str = "", conv_id: str = "", ws_id: str = "") -> None:
    """Set turn trace context (called at start of each conversation turn)."""
    _turn_id.set(turn_id)
    _conv_id.set(conv_id)
    _ws_id.set(ws_id)


def clear_turn_context() -> None:
    """Clear turn trace context after turn completes."""
    _turn_id.set("")
    _conv_id.set("")
    _ws_id.set("")


def new_turn_id() -> str:
    """Generate a new 12-char hex turn ID."""
    return uuid.uuid4().hex[:12]


def get_turn_id() -> str:
    """Get the current turn_id from context (for passing to sub-components)."""
    return _turn_id.get("")


class ContextFilter(logging.Filter):
    """Inject request + turn trace context into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get("")  # type: ignore[attr-defined]
        record.request_method = _request_method.get("")  # type: ignore[attr-defined]
        record.request_path = _request_path.get("")  # type: ignore[attr-defined]
        record.turn_id = _turn_id.get("")  # type: ignore[attr-defined]
        record.conv_id = _conv_id.get("")  # type: ignore[attr-defined]
        record.ws_id = _ws_id.get("")  # type: ignore[attr-defined]
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
            "turn_id": "a1b2c3d4e5f6",
            "conv_id": "conv-abcd1234",
            "ws_id": "ws-xyz",
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
        }

        # Turn trace fields (omit if empty to keep logs lean)
        turn_id = getattr(record, "turn_id", "") or ""
        conv_id = getattr(record, "conv_id", "") or ""
        ws_id = getattr(record, "ws_id", "") or ""
        if turn_id:
            entry["turn_id"] = turn_id
        if conv_id:
            entry["conv_id"] = conv_id
        if ws_id:
            entry["ws_id"] = ws_id

        # Request context (for HTTP, not WS)
        request_id = getattr(record, "request_id", "") or ""
        if request_id:
            entry["request_id"] = request_id
            method = getattr(record, "request_method", "") or ""
            path = getattr(record, "request_path", "") or ""
            if method:
                entry["method"] = method
            if path:
                entry["path"] = path

        # Include exception info if present
        if record.exc_info and record.exc_info[1]:
            entry["exc"] = traceback.format_exception(*record.exc_info)
        elif record.exc_text:
            entry["exc"] = record.exc_text

        return json.dumps(entry, default=str)
