"""Shared base models and error responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str
    error_code: str | None = None
    request_id: str | None = None


class SuccessResponse(BaseModel):
    success: bool = True
    message: str = ""


class PaginatedResponse(BaseModel):
    items: list = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
