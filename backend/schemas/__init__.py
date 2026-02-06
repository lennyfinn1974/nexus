"""Pydantic v2 schemas for the Nexus API."""

from .common import ErrorResponse, SuccessResponse, PaginatedResponse
from .chat import ChatMessage, WebSocketIncoming, StreamEvent
from .tools import ToolParameter, ToolDefinition, ToolCall, ToolResult
from .api import (
    StatusResponse, ConversationCreate, ConversationUpdate,
    ConversationResponse, MessageResponse, SkillResponse,
    TaskResponse, IngestRequest,
)
from .admin import (
    SettingsUpdateRequest, SettingsResponse, PluginInfo, BackupResponse,
)
from .partnerships import PartnerAgent, AgentMessage

__all__ = [
    "ErrorResponse", "SuccessResponse", "PaginatedResponse",
    "ChatMessage", "WebSocketIncoming", "StreamEvent",
    "ToolParameter", "ToolDefinition", "ToolCall", "ToolResult",
    "StatusResponse", "ConversationCreate", "ConversationUpdate",
    "ConversationResponse", "MessageResponse", "SkillResponse",
    "TaskResponse", "IngestRequest",
    "SettingsUpdateRequest", "SettingsResponse", "PluginInfo", "BackupResponse",
    "PartnerAgent", "AgentMessage",
]
