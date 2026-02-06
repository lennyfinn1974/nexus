"""Tool calling schemas — the core of structured tool interaction."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class ToolParameter(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True


class ToolDefinition(BaseModel):
    """Describes a tool that can be called by the model."""

    name: str
    plugin: str
    description: str = ""
    parameters: list[ToolParameter] = Field(default_factory=list)

    def to_anthropic_format(self) -> dict:
        """Convert to Anthropic API tool format."""
        properties = {}
        required = []
        for p in self.parameters:
            properties[p.name] = {
                "type": p.type,
                "description": p.description,
            }
            if p.required:
                required.append(p.name)

        return {
            "name": f"{self.plugin}__{self.name}",
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def to_ollama_format(self) -> dict:
        """Convert to Ollama/OpenAI-compatible tool format."""
        properties = {}
        required = []
        for p in self.parameters:
            properties[p.name] = {
                "type": p.type,
                "description": p.description,
            }
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": f"{self.plugin}__{self.name}",
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class ToolCall(BaseModel):
    """A parsed tool call from the model's response."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    plugin: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The result of executing a tool call."""

    tool_call_id: str
    name: str
    result: str | None = None
    error: str | None = None
    success: bool = True
