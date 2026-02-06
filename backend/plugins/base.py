"""Unified base class for all Nexus plugins.

Every plugin must:
* expose a unique ``name`` string,
* implement ``setup()``, ``register_tools()``, ``register_commands()``, and ``shutdown()``.
* optionally declare ``description``, ``version``, and permission level.

Plugins are discovered by scanning the ``plugins/`` directory for ``*_plugin.py`` files.
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("nexus.plugins")


@dataclass
class ToolInfo:
    """Metadata for a tool registered by a plugin."""
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    handler: Callable | None = None


class NexusPlugin(abc.ABC):
    """Unified plugin interface for Nexus.

    Subclass this and implement ``setup()``, ``register_tools()``,
    ``register_commands()``, and ``shutdown()``.
    """

    #: Human readable name -- must be unique.
    name: str = "base"

    #: Short description.
    description: str = ""

    #: Version string (semantic).
    version: str = "0.0.0"

    #: Permission level (see plugins.permissions)
    permission_level: int = 20  # STANDARD

    def __init__(self, config: Any, db: Any, router: Any) -> None:
        self.config = config
        self.db = db
        self.router = router
        self.tools: list[ToolInfo] = []
        self.commands: dict[str, dict] = {}
        self.enabled: bool = True

    # ── Lifecycle ──

    async def setup(self) -> bool:
        """Run once during startup. Return True on success."""
        return True

    def register_tools(self) -> None:
        """Register tools via ``self.add_tool(...)``."""

    def register_commands(self) -> None:
        """Register slash commands via ``self.add_command(...)``."""

    async def shutdown(self) -> None:
        """Clean up resources (close sockets, stop background tasks)."""

    # ── Legacy lifecycle aliases ──

    async def init(self) -> None:
        """Legacy alias for setup(). Override setup() instead."""
        await self.setup()
        self.register_tools()
        self.register_commands()

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        """Legacy execution entry point for slash commands."""
        # Default: look up the command and execute its handler
        if args and isinstance(args[0], str):
            cmd_name = args[0] if not args[0].startswith("/") else args[0][1:]
            if cmd_name in self.commands:
                handler = self.commands[cmd_name].get("handler")
                if handler:
                    return await handler(kwargs.get("args", ""))
        return None

    # ── Registration helpers ──

    def add_tool(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable,
    ) -> None:
        """Register a tool that the AI can call."""
        self.tools.append(ToolInfo(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        ))

    def add_command(
        self,
        name: str,
        description: str,
        handler: Callable,
    ) -> None:
        """Register a slash command."""
        self.commands[name] = {
            "name": name,
            "description": description,
            "handler": handler,
        }

    # ── System prompt ──

    def get_system_prompt_addition(self) -> str:
        """Return extra system-prompt text the plugin wants to inject."""
        if not self.tools:
            return ""
        lines = [f"## {self.name} Tools"]
        for t in self.tools:
            params = ", ".join(f"{k}: {v}" for k, v in t.parameters.items())
            lines.append(f"- **{t.name}**({params}): {t.description}")
        return "\n".join(lines)

    # Legacy compatibility alias
    def get_system_prompt_additions(self) -> str:
        return self.get_system_prompt_addition()

    # ── Metadata ──

    def list_tools(self) -> list[str]:
        return [t.name for t in self.tools]

    def list_commands(self) -> list[dict[str, str]]:
        return [
            {"name": name, "description": info["description"]}
            for name, info in self.commands.items()
        ]

    # ── Security hooks ──

    async def on_before_tool_call(self, tool_name: str, params: dict) -> bool:
        """Called before a tool is executed. Return False to block."""
        return True

    async def on_after_tool_call(self, tool_name: str, params: dict, result: Any) -> None:
        """Called after a tool executes. Use for auditing."""

    # ── Health ──

    async def health_check(self) -> dict:
        """Return health status. Override for custom checks."""
        return {"status": "ok"}


# Deprecated alias -- use NexusPlugin instead
BasePlugin = NexusPlugin
