"""Local model API client with tool calling support.

Supports both Ollama and llama-server (llama.cpp) backends transparently.
Both expose OpenAI-compatible /v1/chat/completions endpoints.

Backend auto-detection:
  - Ollama: /api/tags returns model list, also has /api/chat (native)
  - llama-server: /health returns {"status":"ok"}, /v1 only

When talking to llama-server, ALL requests go through /v1/chat/completions
(including no-tools streaming).  When talking to Ollama, no-tools requests
can optionally use /api/chat for lower latency.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

logger = logging.getLogger("nexus.ollama")


class OllamaClient:
    """Client for local model APIs (Ollama or llama-server)."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen3-coder:30b"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)
        self._supports_tools: bool | None = None
        # Backend type: "ollama", "llama_server", or None (unknown)
        self._backend: str | None = None

    @property
    def is_llama_server(self) -> bool:
        """True if connected to llama-server instead of Ollama."""
        return self._backend == "llama_server"

    @property
    def supports_tools(self) -> bool:
        """Check if the current model supports native tool calling."""
        if self._supports_tools is not None:
            return self._supports_tools
        # llama-server with --jinja always supports tools
        if self.is_llama_server:
            self._supports_tools = True
            return True
        # Models known to support tool calling
        tool_capable = [
            "llama3.1",
            "llama3.2",
            "llama3.3",
            "mistral",
            "mixtral",
            "qwen2",
            "qwen2.5",
            "qwen3",
            "command-r",
            "kimi",
        ]
        model_lower = self.model.lower()
        self._supports_tools = any(tc in model_lower for tc in tool_capable)
        return self._supports_tools

    async def is_available(self) -> bool:
        """Check if the local model server is running.

        Auto-detects whether we're talking to Ollama or llama-server:
          - Try /health first (llama-server) — returns {"status":"ok"}
          - Fall back to /api/tags (Ollama) — returns model list
        """
        # Try llama-server health endpoint first
        try:
            resp = await self._client.get("/health", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if data.get("status") == "ok":
                    if self._backend != "llama_server":
                        self._backend = "llama_server"
                        self._supports_tools = True  # Reset — llama-server always supports tools
                        logger.info(f"Detected llama-server backend at {self.base_url}")
                    return True
        except (httpx.ConnectError, httpx.TimeoutException, Exception):
            pass

        # Try Ollama /api/tags
        try:
            resp = await self._client.get("/api/tags", timeout=5.0)
            if resp.status_code == 200:
                if self._backend != "ollama":
                    self._backend = "ollama"
                    self._supports_tools = None  # Reset — re-check for Ollama
                    logger.info(f"Detected Ollama backend at {self.base_url}")
                models = resp.json().get("models", [])
                available = [m["name"] for m in models]
                if self.model in available or ":cloud" in self.model:
                    return True
                logger.warning(f"Model '{self.model}' not found. Available: {available}")
                return len(available) > 0
        except (httpx.ConnectError, httpx.TimeoutException):
            pass

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

        When connected to llama-server, ALL requests use /v1 (no /api/chat).
        """
        use_tools = bool(tools and self.supports_tools)

        # llama-server: always use /v1
        if self.is_llama_server:
            return await self._chat_v1(messages, system, tools if use_tools else None)

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
        Uses /v1/chat/completions with SSE streaming for both tool-calling
        and synthesis (tool-result) modes.  Falls back to /api/chat (native
        Ollama streaming) when no tools are involved for lowest latency.

        When connected to llama-server, ALL streaming uses /v1 (no /api/chat).
        """
        use_tools = bool(tools and self.supports_tools)

        # Check if messages contain tool-formatted content that requires /v1
        has_tool_messages = any(m.get("role") == "tool" for m in messages)

        # llama-server: always use /v1 streaming (no /api/chat endpoint)
        if use_tools or has_tool_messages or self.is_llama_server:
            # SSE streaming via /v1 — streams text chunks AND collects tool calls
            synthesis_mode = has_tool_messages and not use_tools
            try:
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

                msgs = synth_messages
                if system:
                    msgs = [{"role": "system", "content": system}] + msgs

                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": msgs,
                    "stream": True,
                }
                if not synthesis_mode and tools:
                    payload["tools"] = tools
                    tool_names = [t.get("function", {}).get("name", "?") for t in tools]
                    logger.info(f"Sending {len(tools)} tools to Ollama /v1: {tool_names}")
                    logger.debug(f"System prompt length: {len(system or '')} chars, Messages: {len(msgs)}")

                # Accumulate tool calls from streaming deltas
                tool_call_accum: dict[int, dict] = {}  # index → {id, name, arguments_str}

                async with self._client.stream(
                    "POST", "/v1/chat/completions", json=payload, timeout=180.0,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or line == "data: [DONE]":
                            continue
                        if line.startswith("data: "):
                            line = line[6:]
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        delta = data.get("choices", [{}])[0].get("delta", {})

                        # Stream text content immediately
                        content = delta.get("content")
                        if content:
                            yield content

                        # Accumulate tool call deltas
                        for tc_delta in delta.get("tool_calls", []):
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_call_accum:
                                tool_call_accum[idx] = {
                                    "id": tc_delta.get("id", f"ollama_{idx}"),
                                    "name": "",
                                    "arguments": "",
                                }
                            func = tc_delta.get("function", {})
                            if func.get("name"):
                                tool_call_accum[idx]["name"] = func["name"]
                            if func.get("arguments"):
                                tool_call_accum[idx]["arguments"] += func["arguments"]

                        # Check for finish
                        finish = data.get("choices", [{}])[0].get("finish_reason")
                        if finish:
                            logger.debug(f"Stream finish_reason: {finish}")
                            break

                # Yield accumulated tool calls after streaming completes
                if tool_call_accum:
                    logger.info(f"Model returned {len(tool_call_accum)} tool call(s): {[tc['name'] for tc in tool_call_accum.values()]}")
                else:
                    logger.info("Model returned NO tool calls (text-only response)")
                if not synthesis_mode:
                    for idx in sorted(tool_call_accum.keys()):
                        tc = tool_call_accum[idx]
                        args = tc["arguments"]
                        try:
                            args = json.loads(args) if args else {}
                        except json.JSONDecodeError:
                            args = {}
                        yield {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
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
