"""Global exception handlers — return structured ErrorResponse JSON."""

from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.exceptions import (
    NexusError,
    PathAccessDeniedError,
    PluginNotFoundError,
    RateLimitExceededError,
    ToolExecutionError,
    ModelUnavailableError,
    SkillNotConfiguredError,
)

logger = logging.getLogger("nexus.errors")


def register_exception_handlers(app: FastAPI) -> None:
    """Attach global exception handlers to the FastAPI app."""

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=400,
            content={
                "detail": str(exc),
                "error_code": "BAD_REQUEST",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(PermissionError)
    async def _permission_error(request: Request, exc: PermissionError):
        return JSONResponse(
            status_code=403,
            content={
                "detail": str(exc),
                "error_code": "FORBIDDEN",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(FileNotFoundError)
    async def _file_not_found(request: Request, exc: FileNotFoundError):
        return JSONResponse(
            status_code=404,
            content={
                "detail": str(exc),
                "error_code": "NOT_FOUND",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(PathAccessDeniedError)
    async def _path_denied(request: Request, exc: PathAccessDeniedError):
        return JSONResponse(
            status_code=403,
            content={
                "detail": str(exc),
                "error_code": "PATH_DENIED",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(PluginNotFoundError)
    async def _plugin_not_found(request: Request, exc: PluginNotFoundError):
        return JSONResponse(
            status_code=404,
            content={
                "detail": str(exc),
                "error_code": "PLUGIN_NOT_FOUND",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(RateLimitExceededError)
    async def _rate_limit(request: Request, exc: RateLimitExceededError):
        return JSONResponse(
            status_code=429,
            content={
                "detail": str(exc),
                "error_code": "RATE_LIMITED",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(ToolExecutionError)
    async def _tool_error(request: Request, exc: ToolExecutionError):
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc),
                "error_code": "TOOL_EXECUTION_ERROR",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(ModelUnavailableError)
    async def _model_unavailable(request: Request, exc: ModelUnavailableError):
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "error_code": "MODEL_UNAVAILABLE",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(SkillNotConfiguredError)
    async def _skill_not_configured(request: Request, exc: SkillNotConfiguredError):
        return JSONResponse(
            status_code=400,
            content={
                "detail": str(exc),
                "error_code": "SKILL_NOT_CONFIGURED",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(NexusError)
    async def _nexus_error(request: Request, exc: NexusError):
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc),
                "error_code": "INTERNAL_ERROR",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None)
        logger.error(
            "Unhandled exception [rid:%s]: %s\n%s",
            request_id, exc, traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "error_code": "INTERNAL_ERROR",
                "request_id": request_id,
            },
        )
