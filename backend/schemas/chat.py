"""Chat message and streaming schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class WebSocketIncoming(BaseModel):
    """Incoming WebSocket message from client."""

    type: str = "text"
    text: str | None = None
    conv_id: str | None = None


class StreamEvent(BaseModel):
    """Server-sent streaming event via WebSocket."""

    type: Literal[
        "stream_start",
        "stream_chunk",
        "stream_end",
        "message",
        "system",
        "error",
        "conversation_set",
        "conversation_renamed",
        "session_info",
        "ping",
    ]
    content: str | None = None
    model: str | None = None
    conv_id: str | None = None
    title: str | None = None
    session_id: str | None = None
