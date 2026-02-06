"""Structured tool calling engine — replaces regex-based <tool_call> parsing."""

from __future__ import annotations

import logging
from typing import Any

from schemas.tools import ToolCall, ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger("nexus.tools")


class ToolExecutor:
    """Unified tool calling engine for both plugin tools and skill actions."""

    def __init__(self, plugin_manager: Any, skills_engine: Any):
        self.plugin_manager = plugin_manager
        self.skills_engine = skills_engine

    def get_tool_definitions(self) -> list[ToolDefinition]:
        """Collect all tool definitions from plugins + skill actions."""
        definitions: list[ToolDefinition] = []

        # Plugin tools
        for plugin_name, plugin in self.plugin_manager.plugins.items():
            for tool in plugin.tools:
                params = []
                for pname, pdesc in tool.parameters.items():
                    params.append(ToolParameter(
                        name=pname,
                        type="string",
                        description=str(pdesc),
                        required=True,
                    ))
                definitions.append(ToolDefinition(
                    name=tool.name,
                    plugin=plugin_name,
                    description=tool.description,
                    parameters=params,
                ))

        # Skill actions
        for skill in self.skills_engine.skills.values():
            if not skill.is_configured(self.skills_engine.config) if self.skills_engine.config else False:
                continue
            for action in skill.actions:
                params = []
                for pname, pdesc in action.parameters.items():
                    params.append(ToolParameter(
                        name=pname,
                        type="string",
                        description=str(pdesc),
                        required=True,
                    ))
                definitions.append(ToolDefinition(
                    name=action.name,
                    plugin=f"skill_{skill.id}",
                    description=action.description,
                    parameters=params,
                ))

        return definitions

    def to_anthropic_tools(self) -> list[dict]:
        """Convert all tool definitions to Anthropic API format."""
        return [d.to_anthropic_format() for d in self.get_tool_definitions()]

    def to_ollama_tools(self) -> list[dict]:
        """Convert all tool definitions to Ollama/OpenAI format."""
        return [d.to_ollama_format() for d in self.get_tool_definitions()]

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool call with security checks."""
        logger.info(f"Executing tool: {tool_call.plugin}:{tool_call.name}")

        # Skill actions
        if tool_call.plugin.startswith("skill_"):
            try:
                result = await self.skills_engine.execute_action(
                    tool_call.name, tool_call.parameters
                )
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    result=result,
                    success=True,
                )
            except Exception as e:
                logger.error(f"Skill action {tool_call.name} failed: {e}")
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    error=str(e),
                    success=False,
                )

        # Plugin tools
        plugin = self.plugin_manager.plugins.get(tool_call.plugin)
        if not plugin:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error=f"Plugin '{tool_call.plugin}' not found",
                success=False,
            )

        # Security hook
        allowed = await self.plugin_manager.validate_tool_call(
            plugin, tool_call.name, tool_call.parameters
        )
        if not allowed:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error="Tool call blocked by security policy",
                success=False,
            )

        # Find and execute handler
        tool_info = next((t for t in plugin.tools if t.name == tool_call.name), None)
        if not tool_info or not tool_info.handler:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error=f"Tool '{tool_call.name}' has no handler",
                success=False,
            )

        try:
            result = await tool_info.handler(tool_call.parameters)
            await self.plugin_manager.audit_tool_call(
                plugin, tool_call.name, tool_call.parameters, result
            )
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=str(result),
                success=True,
            )
        except Exception as e:
            logger.error(f"Tool {tool_call.name} failed: {e}")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error=str(e),
                success=False,
            )

    async def execute_batch(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Execute multiple tool calls sequentially."""
        results = []
        for tc in tool_calls:
            result = await self.execute(tc)
            results.append(result)
        return results

    @staticmethod
    def parse_anthropic_tool_call(block: dict) -> ToolCall:
        """Parse an Anthropic API tool_use content block into a ToolCall."""
        full_name = block.get("name", "")
        # Format: plugin__tool_name
        if "__" in full_name:
            plugin, name = full_name.split("__", 1)
        else:
            plugin = "unknown"
            name = full_name

        return ToolCall(
            id=block.get("id", ""),
            name=name,
            plugin=plugin,
            parameters=block.get("input", {}),
        )

    @staticmethod
    def parse_ollama_tool_call(tool_call: dict) -> ToolCall:
        """Parse an Ollama/OpenAI tool call into a ToolCall."""
        func = tool_call.get("function", {})
        full_name = func.get("name", "")
        if "__" in full_name:
            plugin, name = full_name.split("__", 1)
        else:
            plugin = "unknown"
            name = full_name

        import json
        args = func.get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}

        return ToolCall(
            id=tool_call.get("id", ""),
            name=name,
            plugin=plugin,
            parameters=args,
        )

    def format_results_for_anthropic(self, results: list[ToolResult]) -> list[dict]:
        """Format tool results as Anthropic tool_result content blocks."""
        blocks = []
        for r in results:
            blocks.append({
                "type": "tool_result",
                "tool_use_id": r.tool_call_id,
                "content": r.result if r.success else f"Error: {r.error}",
            })
        return blocks

    def format_results_for_ollama(self, results: list[ToolResult]) -> list[dict]:
        """Format tool results as Ollama/OpenAI tool messages."""
        messages = []
        for r in results:
            messages.append({
                "role": "tool",
                "content": r.result if r.success else f"Error: {r.error}",
                "tool_call_id": r.tool_call_id,
            })
        return messages
