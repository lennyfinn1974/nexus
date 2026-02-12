"""Ollama API client with tool calling support for compatible models.

Uses the OpenAI-compatible /v1/chat/completions endpoint for tool calls
(more reliable, matches OpenClaw's approach) and native /api/chat for
regular streaming (lower latency).
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

logger = logging.getLogger("nexus.ollama")


class OllamaClient:
    """Client for Ollama's local API."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "kimi-k2.5:cloud"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)
        self._supports_tools: bool | None = None

    @property
    def supports_tools(self) -> bool:
        """Check if the current model supports native tool calling."""
        if self._supports_tools is not None:
            return self._supports_tools
        # Models known to support tool calling
        tool_capable = [
            "llama3.1",
            "llama3.2",
            "llama3.3",
            "mistral",
            "mixtral",
            "qwen2",
            "qwen2.5",
            "command-r",
            "kimi",
        ]
        model_lower = self.model.lower()
        self._supports_tools = any(tc in model_lower for tc in tool_capable)
        return self._supports_tools

    async def is_available(self) -> bool:
        """Check if Ollama is running and the model is accessible."""
        try:
            resp = await self._client.get("/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                available = [m["name"] for m in models]
                if self.model in available or ":cloud" in self.model:
                    return True
                logger.warning(f"Model '{self.model}' not found. Available: {available}")
                return len(available) > 0
            return False
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def chat(
        self,
        messages: list,
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """Send a chat completion request (non-streaming).

        Uses /v1/chat/completions (OpenAI-compatible) when tools are present
        for more reliable tool calling. Falls back to /api/chat otherwise.
        """
        use_tools = bool(tools and self.supports_tools)

        if use_tools:
            return await self._chat_v1(messages, system, tools)
        return await self._chat_native(messages, system)

    async def _chat_v1(
        self,
        messages: list,
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """Chat via OpenAI-compatible /v1/chat/completions endpoint.

        This endpoint produces standardized function calling format that
        models like kimi-k2.5 handle much more reliably than /api/chat.
        """
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
        }
        if tools:
            payload["tools"] = tools

        try:
            resp = await self._client.post(
                "/v1/chat/completions", json=payload, timeout=180.0,
            )
            resp.raise_for_status()
            data = resp.json()

            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            usage = data.get("usage", {})

            result = {
                "content": (message.get("content") or "").strip(),
                "model": self.model,
                "tokens_in": usage.get("prompt_tokens", 0),
                "tokens_out": usage.get("completion_tokens", 0),
                "provider": "ollama",
                "finish_reason": choice.get("finish_reason", ""),
            }

            # Parse tool calls from OpenAI format
            tool_calls_raw = message.get("tool_calls", [])
            if tool_calls_raw:
                result["tool_calls"] = []
                for i, tc in enumerate(tool_calls_raw):
                    func = tc.get("function", {})
                    # /v1 returns arguments as JSON string
                    args = func.get("arguments", "{}")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    result["tool_calls"].append({
                        "id": tc.get("id", f"ollama_{i}"),
                        "function": {
                            "name": func.get("name", ""),
                            "arguments": args,
                        },
                    })

            return result
        except httpx.TimeoutException:
            raise TimeoutError("Ollama request timed out after 180s")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama error {e.response.status_code}: {e.response.text}")

    async def _chat_native(
        self,
        messages: list,
        system: str | None = None,
    ) -> dict:
        """Chat via native /api/chat endpoint (no tools)."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if system:
            payload["messages"] = [{"role": "system", "content": system}] + payload["messages"]

        try:
            resp = await self._client.post("/api/chat", json=payload, timeout=180.0)
            resp.raise_for_status()
            data = resp.json()

            return {
                "content": data.get("message", {}).get("content", ""),
                "model": self.model,
                "tokens_in": data.get("prompt_eval_count", 0),
                "tokens_out": data.get("eval_count", 0),
                "provider": "ollama",
            }
        except httpx.TimeoutException:
            raise TimeoutError("Ollama request timed out after 180s")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama error {e.response.status_code}: {e.response.text}")

    async def chat_stream(
        self,
        messages: list,
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[str | dict, None]:
        """Stream a chat completion response.

        Yields text chunks (str) for content and dicts for tool calls.
        When tools are provided, uses /v1/chat/completions (non-streaming)
        for reliable tool call parsing.  Also uses /v1 when messages contain
        tool-formatted content (role:"tool") even without tools — this
        happens during forced synthesis rounds.
        """
        use_tools = bool(tools and self.supports_tools)

        # Check if messages contain tool-formatted content that requires /v1
        has_tool_messages = any(m.get("role") == "tool" for m in messages)

        if use_tools or has_tool_messages:
            # Non-streaming via /v1 for tool mode — much more reliable
            synthesis_mode = has_tool_messages and not use_tools
            try:
                # In synthesis mode, add a user instruction to force text answer
                synth_messages = list(messages)
                if synthesis_mode:
                    synth_messages.append({
                        "role": "user",
                        "content": (
                            "You now have all the tool results you need. "
                            "Give a clear, comprehensive answer based on the "
                            "tool results above. Do NOT call any more tools."
                        ),
                    })
                result = await self._chat_v1(synth_messages, system, tools)
                # Yield any text content
                if result.get("content"):
                    yield result["content"]
                # Only yield tool calls when NOT in synthesis mode
                if not synthesis_mode:
                    for tc in result.get("tool_calls", []):
                        func = tc.get("function", {})
                        args = func.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        yield {
                            "type": "tool_use",
                            "id": tc.get("id", f"ollama_{id(tc)}"),
                            "name": func.get("name", ""),
                            "input": args,
                        }
            except Exception as e:
                yield f"\n\n[Error: Ollama tool call failed -- {e}]"
            return

        # Standard streaming via /api/chat (no tools — lower latency)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if system:
            payload["messages"] = [{"role": "system", "content": system}] + payload["messages"]

        try:
            async with self._client.stream("POST", "/api/chat", json=payload, timeout=180.0) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if data.get("done", False):
                            return
        except httpx.TimeoutException:
            yield "\n\n[Error: Ollama request timed out]"
        except httpx.HTTPStatusError as e:
            yield f"\n\n[Error: Ollama returned {e.response.status_code}]"

    async def close(self) -> None:
        await self._client.aclose()
