"""Partner agent and inter-agent messaging schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class PartnerAgent(BaseModel):
    name: str
    gateway_url: str
    auth_token: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    status: Literal["online", "offline", "degraded"] = "offline"
    last_seen: datetime | None = None


class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    sender: str
    recipient: str
    type: Literal[
        "task_request", "task_result", "handoff",
        "status_query", "capability_query",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reply_to: str | None = None
