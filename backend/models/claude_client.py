"""Anthropic Claude API client with native tool calling support."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

import anthropic

logger = logging.getLogger("nexus.claude")


class ClaudeClient:
    """Client for the Anthropic Claude API."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def is_available(self) -> bool:
        """Check if the API key is valid."""
        try:
            await self._client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except anthropic.AuthenticationError:
            logger.error("Anthropic API key is invalid")
            return False
        except Exception as e:
            logger.warning(f"Claude availability check failed: {e}")
            return False

    async def chat(
        self,
        messages: list,
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """Send a chat completion request (non-streaming).

        Args:
            messages: Conversation messages.
            system: System prompt.
            tools: Anthropic-format tool definitions (optional).

        Returns:
            Dict with content, model, tokens, provider, and optional tool_calls.
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        try:
            resp = await self._client.messages.create(**kwargs)
            content = ""
            tool_calls = []

            for block in resp.content:
                if block.type == "text":
                    content += block.text
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            result = {
                "content": content,
                "model": self.model,
                "tokens_in": resp.usage.input_tokens,
                "tokens_out": resp.usage.output_tokens,
                "provider": "anthropic",
                "stop_reason": resp.stop_reason,
            }

            if tool_calls:
                result["tool_calls"] = tool_calls

            return result
        except anthropic.RateLimitError:
            raise RuntimeError("Claude API rate limit reached. Please wait a moment.")
        except anthropic.APIError as e:
            raise RuntimeError(f"Claude API error: {e.message}")

    async def chat_stream(
        self,
        messages: list,
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[str | dict, None]:
        """Stream a chat completion response.

        Yields text chunks for text content blocks.
        Yields dicts for tool_use blocks (complete tool call).
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        try:
            if not tools:
                # Simple text streaming without tools
                async with self._client.messages.stream(**kwargs) as stream:
                    async for text in stream.text_stream:
                        yield text
            else:
                # Full streaming with tool support
                async with self._client.messages.stream(**kwargs) as stream:
                    current_tool: dict | None = None
                    tool_input_json = ""

                    async for event in stream:
                        if hasattr(event, 'type'):
                            if event.type == 'content_block_start':
                                block = event.content_block
                                if block.type == 'tool_use':
                                    current_tool = {
                                        "id": block.id,
                                        "name": block.name,
                                        "input": {},
                                    }
                                    tool_input_json = ""

                            elif event.type == 'content_block_delta':
                                delta = event.delta
                                if delta.type == 'text_delta':
                                    yield delta.text
                                elif delta.type == 'input_json_delta':
                                    tool_input_json += delta.partial_json

                            elif event.type == 'content_block_stop':
                                if current_tool:
                                    import json
                                    try:
                                        current_tool["input"] = json.loads(tool_input_json) if tool_input_json else {}
                                    except json.JSONDecodeError:
                                        current_tool["input"] = {}
                                    yield {"type": "tool_use", **current_tool}
                                    current_tool = None
                                    tool_input_json = ""
                        elif isinstance(event, str):
                            yield event

        except anthropic.RateLimitError:
            yield "\n\n[Error: Claude API rate limit reached]"
        except anthropic.APIError as e:
            yield f"\n\n[Error: Claude API -- {e.message}]"

    async def close(self) -> None:
        await self._client.close()
