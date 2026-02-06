"""Pydantic v2 schemas for the Nexus API."""

from .admin import (
    BackupResponse,
    PluginInfo,
    SettingsResponse,
    SettingsUpdateRequest,
)
from .api import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    IngestRequest,
    MessageResponse,
    SkillResponse,
    StatusResponse,
    TaskResponse,
)
from .chat import ChatMessage, StreamEvent, WebSocketIncoming
from .common import ErrorResponse, PaginatedResponse, SuccessResponse
from .partnerships import AgentMessage, PartnerAgent
from .tools import ToolCall, ToolDefinition, ToolParameter, ToolResult

__all__ = [
    "ErrorResponse",
    "SuccessResponse",
    "PaginatedResponse",
    "ChatMessage",
    "WebSocketIncoming",
    "StreamEvent",
    "ToolParameter",
    "ToolDefinition",
    "ToolCall",
    "ToolResult",
    "StatusResponse",
    "ConversationCreate",
    "ConversationUpdate",
    "ConversationResponse",
    "MessageResponse",
    "SkillResponse",
    "TaskResponse",
    "IngestRequest",
    "SettingsUpdateRequest",
    "SettingsResponse",
    "PluginInfo",
    "BackupResponse",
    "PartnerAgent",
    "AgentMessage",
]
