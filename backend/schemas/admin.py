"""Admin panel request/response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SettingsUpdateRequest(BaseModel):
    updates: dict[str, Any]


class SettingsResponse(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class PluginInfo(BaseModel):
    name: str
    version: str = "0.0.0"
    description: str = ""
    enabled: bool = True
    tools: list[dict[str, Any]] = Field(default_factory=list)
    commands: list[dict[str, Any]] = Field(default_factory=list)
    health: dict[str, Any] = Field(default_factory=dict)
    required_settings: dict[str, Any] = Field(default_factory=dict)
    pip_requires: list[str] = Field(default_factory=list)


class BackupResponse(BaseModel):
    path: str
    size_mb: float
    timestamp: str
