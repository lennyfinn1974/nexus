"""Typed agent errors for classified error recovery."""

from __future__ import annotations


class AgentError(Exception):
    """Base for classified agent errors."""

    error_type: str = "unknown"


class ContextOverflowError(AgentError):
    """Context window exceeded."""

    error_type = "context_overflow"


class ModelTimeoutError(AgentError):
    """Model didn't respond in time."""

    error_type = "timeout"


class RateLimitError(AgentError):
    """429 / too many requests."""

    error_type = "rate_limit"


class AuthError(AgentError):
    """Invalid API key / 401."""

    error_type = "auth"


class ModelUnavailableError(AgentError):
    """Model not reachable."""

    error_type = "unavailable"


class AgentAbortError(AgentError):
    """User cancelled the request."""

    error_type = "abort"


def classify_error(exc: Exception) -> AgentError:
    """Classify a raw exception into a typed AgentError."""
    if isinstance(exc, AgentError):
        return exc

    msg = str(exc).lower()

    if "context" in msg or "too long" in msg or "maximum context" in msg:
        return ContextOverflowError(str(exc))
    if "timeout" in msg or "timed out" in msg:
        return ModelTimeoutError(str(exc))
    if "rate" in msg and ("limit" in msg or "429" in msg) or "too many" in msg:
        return RateLimitError(str(exc))
    if "401" in msg or "api key" in msg or "invalid key" in msg or "unauthorized" in msg:
        return AuthError(str(exc))
    if "connect" in msg and ("refused" in msg or "error" in msg) or "unavailable" in msg:
        return ModelUnavailableError(str(exc))

    return AgentError(str(exc))
