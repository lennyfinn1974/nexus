"""Ollama API client with tool calling support for compatible models."""

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
            "llama3.1", "llama3.2", "llama3.3",
            "mistral", "mixtral",
            "qwen2", "qwen2.5",
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

        Args:
            messages: Conversation messages.
            system: System prompt.
            tools: OpenAI-format tool definitions (optional).
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if system:
            payload["messages"] = [{"role": "system", "content": system}] + payload["messages"]
        if tools and self.supports_tools:
            payload["tools"] = tools

        try:
            resp = await self._client.post("/api/chat", json=payload, timeout=180.0)
            resp.raise_for_status()
            data = resp.json()

            result = {
                "content": data.get("message", {}).get("content", ""),
                "model": self.model,
                "tokens_in": data.get("prompt_eval_count", 0),
                "tokens_out": data.get("eval_count", 0),
                "provider": "ollama",
            }

            # Parse tool calls from response
            tool_calls_raw = data.get("message", {}).get("tool_calls", [])
            if tool_calls_raw:
                result["tool_calls"] = [
                    {
                        "id": f"ollama_{i}",
                        "function": tc.get("function", {}),
                    }
                    for i, tc in enumerate(tool_calls_raw)
                ]

            return result
        except httpx.TimeoutException:
            raise TimeoutError("Ollama request timed out after 180s")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama error {e.response.status_code}: {e.response.text}")

    async def chat_stream(
        self,
        messages: list,
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a chat completion response."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if system:
            payload["messages"] = [{"role": "system", "content": system}] + payload["messages"]
        if tools and self.supports_tools:
            payload["tools"] = tools

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
