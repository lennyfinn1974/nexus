"""API request/response models for public REST endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StatusResponse(BaseModel):
    models: dict[str, Any] = Field(default_factory=dict)
    tasks_active: int = 0
    skills_count: int = 0
    plugins: dict[str, Any] = Field(default_factory=dict)


class ConversationCreate(BaseModel):
    title: str = "New Conversation"


class ConversationUpdate(BaseModel):
    title: str


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str | None = None
    updated_at: str | None = None


class MessageResponse(BaseModel):
    id: str | None = None
    role: str
    content: str
    model_used: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    created_at: str | None = None


class SkillResponse(BaseModel):
    id: str
    name: str
    type: str = "knowledge"
    domain: str = "general"
    description: str = ""
    version: str = "1.0"
    has_actions: bool = False
    configured: bool | None = None
    config_keys: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class TaskResponse(BaseModel):
    id: str
    type: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None
    created_at: str | None = None


class IngestRequest(BaseModel):
    filename: str
