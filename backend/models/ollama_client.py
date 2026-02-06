"""Ollama API client for local model inference."""

import httpx
import asyncio
import logging
from typing import AsyncGenerator

logger = logging.getLogger("nexus.ollama")


class OllamaClient:
    """Client for Ollama's local API."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "kimi-k2.5:cloud"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)

    async def is_available(self) -> bool:
        """Check if Ollama is running and the model is accessible."""
        try:
            resp = await self._client.get("/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                available = [m["name"] for m in models]
                # Also check for cloud-routed models which may not appear in local tags
                if self.model in available or ":cloud" in self.model:
                    return True
                logger.warning(f"Model '{self.model}' not found. Available: {available}")
                return len(available) > 0  # At least Ollama is running
            return False
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def chat(self, messages: list, system: str = None) -> dict:
        """Send a chat completion request (non-streaming)."""
        payload = {
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
            raise TimeoutError(f"Ollama request timed out after 180s")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama error {e.response.status_code}: {e.response.text}")

    async def chat_stream(self, messages: list, system: str = None) :
        """Stream a chat completion response."""
        payload = {
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
                        import json
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

    async def close(self):
        await self._client.aclose()
