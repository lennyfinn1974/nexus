"""Model router — decides which model handles each request."""

import asyncio
import logging
import re
from typing import AsyncGenerator
from .ollama_client import OllamaClient
from .claude_client import ClaudeClient

logger = logging.getLogger("nexus.router")

# Indicators that suggest a message needs complex reasoning
COMPLEX_INDICATORS = [
    r"\b(analyse|analyze|explain|compare|contrast|evaluate|synthesize|critique)\b",
    r"\b(write|draft|compose|create)\b.{10,}",  # writing tasks with detail
    r"\b(code|implement|build|architect|debug|refactor)\b",
    r"\b(research|investigate|deep.?dive|thorough)\b",
    r"\b(strategy|plan|roadmap|design)\b",
    r"\b(why|how come|what causes|reasoning behind)\b",
    r"\b(step.by.step|break.?down|walk.me.through)\b",
    r"\b(pros?.and.cons?|trade.?offs?|advantages?.and.disadvantages?)\b",
    r"```",  # code blocks suggest technical work
]

# Indicators for simple tasks suitable for local model
SIMPLE_INDICATORS = [
    r"^(hi|hello|hey|thanks|thank you|ok|okay|yes|no|sure)\b",
    r"^(what is|who is|when was|where is|define)\b.{0,50}$",
    r"^(translate|summarize|summarise|tldr)\b",
    r"\b(remind|timer|alarm|schedule)\b",
    r"^.{0,80}$",  # very short messages
]


class ModelRouter:
    """Routes requests to the appropriate model based on complexity."""

    def __init__(
        self,
        ollama,
        claude,
        complexity_threshold: int = 60,
        timeout_seconds: int = 30,
    ):
        self.ollama = ollama
        self.claude = claude
        self.complexity_threshold = complexity_threshold
        self.timeout_seconds = timeout_seconds
        self._ollama_available = False
        self._claude_available = False

    async def check_availability(self):
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
        score = 50  # baseline

        # Check for complexity indicators
        for pattern in COMPLEX_INDICATORS:
            if re.search(pattern, message, re.IGNORECASE):
                score += 8

        # Check for simplicity indicators
        for pattern in SIMPLE_INDICATORS:
            if re.search(pattern, message, re.IGNORECASE):
                score -= 12

        # Length factor — longer messages tend to be more complex
        word_count = len(message.split())
        if word_count > 200:
            score += 15
        elif word_count > 100:
            score += 8
        elif word_count < 10:
            score -= 10

        # Multi-part questions
        question_marks = message.count("?")
        if question_marks > 2:
            score += 10

        return max(0, min(100, score))

    def select_model(self, message: str, force_model: str = None) -> str:
        """Select which model to use. Returns 'claude', 'ollama', or raises."""

        # User override
        if force_model:
            if force_model == "claude" and self._claude_available:
                return "claude"
            elif force_model in ("ollama", "local") and self._ollama_available:
                return "ollama"
            # Fall through to auto if forced model isn't available

        complexity = self.estimate_complexity(message)
        logger.info(f"Complexity score: {complexity}/{self.complexity_threshold}")

        if complexity >= self.complexity_threshold:
            # Prefer Claude for complex tasks
            if self._claude_available:
                return "claude"
            elif self._ollama_available:
                logger.warning("Claude unavailable, falling back to Ollama for complex task")
                return "ollama"
        else:
            # Prefer local for simple tasks
            if self._ollama_available:
                return "ollama"
            elif self._claude_available:
                logger.info("Ollama unavailable, using Claude for simple task")
                return "claude"

        raise RuntimeError("No models are currently available")

    def _get_client(self, model_name: str):
        if model_name == "claude":
            return self.claude
        return self.ollama

    async def chat(self, messages: list, system: str = None, force_model: str = None) -> dict:
        """Route a chat request to the appropriate model with timeout handling."""
        last_message = messages[-1]["content"] if messages else ""
        model_name = self.select_model(last_message, force_model)
        client = self._get_client(model_name)

        logger.info(f"Routing to: {model_name} (timeout: {self.timeout_seconds}s)")

        async def _try_chat_with_timeout(client, model_name, messages, system):
            try:
                result = await asyncio.wait_for(
                    client.chat(messages, system), 
                    timeout=self.timeout_seconds
                )
                result["routed_to"] = model_name
                return result
            except asyncio.TimeoutError:
                logger.warning(f"{model_name} timed out after {self.timeout_seconds}s")
                raise TimeoutError(f"Model {model_name} timed out after {self.timeout_seconds} seconds")
            except Exception as e:
                logger.warning(f"{model_name} failed: {e}")
                raise

        try:
            return await _try_chat_with_timeout(client, model_name, messages, system)
        except (TimeoutError, Exception) as e:
            # Try fallback if available
            fallback = "claude" if model_name == "ollama" else "ollama"
            if (fallback == "claude" and self._claude_available) or (fallback == "ollama" and self._ollama_available):
                logger.warning(f"Trying fallback to {fallback}...")
                fallback_client = self._get_client(fallback)
                try:
                    result = await _try_chat_with_timeout(fallback_client, fallback, messages, system)
                    result["fallback"] = True
                    result["fallback_reason"] = str(e)
                    return result
                except Exception as fallback_e:
                    logger.error(f"Fallback {fallback} also failed: {fallback_e}")
                    raise Exception(f"Primary model {model_name} failed ({e}), fallback {fallback} also failed ({fallback_e})")
            else:
                logger.error(f"No fallback available for {model_name}")
                raise

    async def chat_stream(
        self, messages: list, system: str = None, force_model: str = None
    ) -> tuple:
        """Route a streaming chat request. Returns (model_name, stream)."""
        last_message = messages[-1]["content"] if messages else ""
        model_name = self.select_model(last_message, force_model)
        client = self._get_client(model_name)

        logger.info(f"Streaming via: {model_name}")
        return model_name, client.chat_stream(messages, system)

    @property
    def status(self) -> dict:
        return {
            "ollama_available": self._ollama_available,
            "claude_available": self._claude_available,
            "ollama_model": self.ollama.model if self.ollama else None,
            "claude_model": self.claude.model if self.claude else None,
            "complexity_threshold": self.complexity_threshold,
        }
