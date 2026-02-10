"""Model router -- decides which model handles each request."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

from .claude_client import ClaudeClient
from .ollama_client import OllamaClient

logger = logging.getLogger("nexus.router")

# Indicators that suggest a message needs complex reasoning
COMPLEX_INDICATORS = [
    r"\b(analyse|analyze|explain|compare|contrast|evaluate|synthesize|critique)\b",
    r"\b(write|draft|compose|create)\b.{10,}",
    r"\b(code|implement|build|architect|debug|refactor)\b",
    r"\b(research|investigate|deep.?dive|thorough)\b",
    r"\b(strategy|plan|roadmap|design)\b",
    r"\b(why|how come|what causes|reasoning behind)\b",
    r"\b(step.by.step|break.?down|walk.me.through)\b",
    r"\b(pros?.and.cons?|trade.?offs?|advantages?.and.disadvantages?)\b",
    r"```",
]

# Indicators for simple tasks suitable for local model
SIMPLE_INDICATORS = [
    r"^(hi|hello|hey|thanks|thank you|ok|okay|yes|no|sure)\b",
    r"^(what is|who is|when was|where is|define)\b.{0,50}$",
    r"^(translate|summarize|summarise|tldr)\b",
    r"\b(remind|timer|alarm|schedule)\b",
    r"^.{0,80}$",
]


class ModelRouter:
    """Routes requests to the appropriate model based on complexity."""

    def __init__(
        self,
        ollama: OllamaClient | None,
        claude: ClaudeClient | None,
        complexity_threshold: int = 60,
        timeout_seconds: int = 30,
    ):
        self.ollama = ollama
        self.claude = claude
        self.complexity_threshold = complexity_threshold
        self.timeout_seconds = timeout_seconds
        self._ollama_available = False
        self._claude_available = False

    async def check_availability(self) -> None:
        """Check which models are available."""
        if self.ollama:
            self._ollama_available = await self.ollama.is_available()
            logger.info(f"Ollama available: {self._ollama_available}")
        if self.claude:
            self._claude_available = await self.claude.is_available()
            logger.info(f"Claude available: {self._claude_available}")

        if not self._ollama_available and not self._claude_available:
            logger.error("No models available! Check Ollama and Anthropic API key.")

    def estimate_complexity(self, message: str) -> int:
        """Estimate message complexity on a 0-100 scale."""
        score = 50

        for pattern in COMPLEX_INDICATORS:
            if re.search(pattern, message, re.IGNORECASE):
                score += 8

        for pattern in SIMPLE_INDICATORS:
            if re.search(pattern, message, re.IGNORECASE):
                score -= 12

        word_count = len(message.split())
        if word_count > 200:
            score += 15
        elif word_count > 100:
            score += 8
        elif word_count < 10:
            score -= 10

        if message.count("?") > 2:
            score += 10

        return max(0, min(100, score))

    def select_model(self, message: str, force_model: str | None = None) -> str:
        """Select which model to use. Returns 'claude' or 'ollama'."""
        if force_model:
            if force_model == "claude" and self._claude_available:
                return "claude"
            elif force_model in ("ollama", "local") and self._ollama_available:
                return "ollama"

        complexity = self.estimate_complexity(message)
        logger.info(f"Complexity score: {complexity}/{self.complexity_threshold}")

        if complexity >= self.complexity_threshold:
            if self._claude_available:
                return "claude"
            elif self._ollama_available:
                logger.warning("Claude unavailable, falling back to Ollama for complex task")
                return "ollama"
        else:
            if self._ollama_available:
                return "ollama"
            elif self._claude_available:
                logger.info("Ollama unavailable, using Claude for simple task")
                return "claude"

        raise RuntimeError("No models are currently available")

    def _get_client(self, model_name: str) -> ClaudeClient | OllamaClient:
        if model_name == "claude":
            return self.claude
        return self.ollama

    async def chat(
        self,
        messages: list,
        system: str | None = None,
        force_model: str | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """Route a chat request with timeout handling and tool support."""
        last_message = messages[-1]["content"] if messages else ""
        model_name = self.select_model(last_message, force_model)
        client = self._get_client(model_name)

        logger.info(f"Routing to: {model_name} (timeout: {self.timeout_seconds}s)")

        async def _try(c: Any, name: str) -> dict:
            try:
                result = await asyncio.wait_for(
                    c.chat(messages, system, tools=tools),
                    timeout=self.timeout_seconds,
                )
                result["routed_to"] = name
                return result
            except asyncio.TimeoutError:
                logger.warning(f"{name} timed out after {self.timeout_seconds}s")
                raise TimeoutError(f"Model {name} timed out")
            except Exception as e:
                logger.warning(f"{name} failed: {e}")
                raise

        try:
            return await _try(client, model_name)
        except Exception as e:
            fallback = "claude" if model_name == "ollama" else "ollama"
            if (fallback == "claude" and self._claude_available) or (fallback == "ollama" and self._ollama_available):
                logger.warning(f"Trying fallback to {fallback}...")
                fb_client = self._get_client(fallback)
                try:
                    result = await _try(fb_client, fallback)
                    result["fallback"] = True
                    result["fallback_reason"] = str(e)
                    return result
                except Exception as fb_e:
                    raise Exception(f"Primary {model_name} failed ({e}), " f"fallback {fallback} also failed ({fb_e})")
            else:
                raise

    async def chat_stream(
        self,
        messages: list,
        system: str | None = None,
        force_model: str | None = None,
        tools: list[dict] | None = None,
    ) -> tuple[str, AsyncGenerator]:
        """Route a streaming chat request. Returns (model_name, stream)."""
        last_message = messages[-1]["content"] if messages else ""
        model_name = self.select_model(last_message, force_model)
        client = self._get_client(model_name)

        logger.info(f"Streaming via: {model_name}")
        return model_name, client.chat_stream(messages, system, tools=tools)

    @property
    def status(self) -> dict:
        return {
            "ollama_available": self._ollama_available,
            "claude_available": self._claude_available,
            "ollama_model": self.ollama.model if self.ollama else None,
            "claude_model": self.claude.model if self.claude else None,
            "complexity_threshold": self.complexity_threshold,
        }
