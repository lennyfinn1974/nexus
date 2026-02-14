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
    """Routes requests to the appropriate model based on complexity.

    Supports three providers:
      - **ollama** — local model via Ollama (primary, always tried first)
      - **claude** — Anthropic Claude API (fallback for complex tasks)
      - **claude_code** — Claude Code CLI with MCP tools (agentic tasks)
    """

    def __init__(
        self,
        ollama: OllamaClient | None,
        claude: ClaudeClient | None,
        claude_code: Any | None = None,
        complexity_threshold: int = 60,
        timeout_seconds: int = 30,
    ):
        self.ollama = ollama
        self.claude = claude
        self.claude_code = claude_code
        self.complexity_threshold = complexity_threshold
        self.timeout_seconds = timeout_seconds
        self._ollama_available = False
        self._claude_available = False
        self._claude_code_available = False

    async def check_availability(self) -> None:
        """Check which models are available."""
        if self.ollama:
            self._ollama_available = await self.ollama.is_available()
            logger.info(f"Ollama available: {self._ollama_available}")
        if self.claude:
            self._claude_available = await self.claude.is_available()
            logger.info(f"Claude available: {self._claude_available}")
        if self.claude_code:
            self._claude_code_available = await self.claude_code.is_available()
            logger.info(f"Claude Code available: {self._claude_code_available}")

        if not self._ollama_available and not self._claude_available and not self._claude_code_available:
            logger.error("No models available! Check Ollama and Anthropic API key.")

    def estimate_complexity(self, message: str, context: list[dict] | None = None) -> int:
        """Estimate message complexity on a 0-100 scale.

        Enhanced routing considers:
        1. Content patterns (regex-based)
        2. Message length
        3. Conversation context (multi-turn complexity)
        4. Tool requirements (agentic indicators)
        5. Code density
        """
        score = 50

        # ── Pattern matching ──
        for pattern in COMPLEX_INDICATORS:
            if re.search(pattern, message, re.IGNORECASE):
                score += 8

        for pattern in SIMPLE_INDICATORS:
            if re.search(pattern, message, re.IGNORECASE):
                score -= 12

        # ── Length analysis ──
        word_count = len(message.split())
        if word_count > 200:
            score += 15
        elif word_count > 100:
            score += 8
        elif word_count < 10:
            score -= 10

        if message.count("?") > 2:
            score += 10

        # ── Code density (code blocks suggest coding task) ──
        code_blocks = message.count("```")
        if code_blocks >= 2:
            score += 12  # Contains code — likely needs reasoning

        # ── Agentic indicators (suggests Claude Code) ──
        agentic_patterns = [
            r"\b(run|execute|install|deploy|test)\b.*\b(command|script|server|pipeline)\b",
            r"\b(browse|navigate|open|visit)\b.*\b(website|page|url|link)\b",
            r"\b(search|find|look|scan)\b.*\b(file|directory|folder|web)\b",
            r"\b(create|edit|modify|update|delete)\b.*\b(file|folder|database|table)\b",
            r"\b(git|npm|pip|docker|brew)\b",
            r"/sov\b|/exec\b|/learn\b",
        ]
        agentic_score = sum(
            1 for p in agentic_patterns if re.search(p, message, re.IGNORECASE)
        )
        if agentic_score >= 2:
            score += 15  # Strongly agentic

        # ── Conversation context analysis ──
        if context:
            # Long conversations tend to be more complex
            if len(context) > 10:
                score += 5
            if len(context) > 20:
                score += 5

            # If recent messages contain tool results, complexity rises
            recent = context[-4:] if len(context) > 4 else context
            tool_mentions = sum(
                1 for m in recent
                if any(kw in m.get("content", "").lower()
                       for kw in ["tool_result", "function_call", "error:", "traceback"])
            )
            score += tool_mentions * 5

            # If user keeps asking follow-ups on same topic, stay on same tier
            if len(context) >= 2:
                prev_content = context[-2].get("content", "")
                if len(prev_content) > 500 and word_count < 30:
                    # Short follow-up to long context — keep it local
                    score -= 8

        return max(0, min(100, score))

    def select_model(
        self,
        message: str,
        force_model: str | None = None,
        context: list[dict] | None = None,
    ) -> str:
        """Select which model to use. Returns 'claude', 'ollama', or 'claude_code'."""
        if force_model:
            if force_model == "claude" and self._claude_available:
                return "claude"
            elif force_model in ("ollama", "local") and self._ollama_available:
                return "ollama"
            elif force_model == "claude_code" and self._claude_code_available:
                return "claude_code"

        complexity = self.estimate_complexity(message, context=context)
        logger.info(f"Complexity score: {complexity}/{self.complexity_threshold}")

        if complexity >= self.complexity_threshold:
            if self._claude_available:
                return "claude"
            elif self._claude_code_available:
                return "claude_code"
            elif self._ollama_available:
                logger.warning("Claude unavailable, falling back to Ollama for complex task")
                return "ollama"
        else:
            if self._ollama_available:
                return "ollama"
            elif self._claude_available:
                logger.info("Ollama unavailable, using Claude for simple task")
                return "claude"
            elif self._claude_code_available:
                return "claude_code"

        raise RuntimeError("No models are currently available")

    def _get_client(self, model_name: str):
        if model_name == "claude":
            return self.claude
        elif model_name == "claude_code":
            return self.claude_code
        return self.ollama

    @staticmethod
    def _sanitize_messages_for_claude(messages: list) -> list:
        """Strip Ollama-format tool messages that Claude can't understand.

        Ollama uses {"role": "tool", ...} and assistant messages with
        {"tool_calls": [...]} — Claude expects tool_use/tool_result content
        blocks. On failover we drop tool interaction messages and keep only
        the plain text conversation so Claude can still answer.
        """
        clean = []
        for msg in messages:
            role = msg.get("role", "")
            # Skip Ollama tool result messages
            if role == "tool":
                continue
            # Strip tool_calls from assistant messages
            if role == "assistant" and "tool_calls" in msg:
                content = msg.get("content", "")
                if content:
                    clean.append({"role": "assistant", "content": content})
                continue
            clean.append(msg)
        return clean

    @staticmethod
    def _sanitize_messages_for_ollama(messages: list) -> list:
        """Strip Anthropic-format tool messages that Ollama can't understand.

        Anthropic uses content blocks [{"type": "tool_use"}, ...] and
        [{"type": "tool_result"}, ...]. On failover we keep only plain text.
        """
        clean = []
        for msg in messages:
            content = msg.get("content", "")
            # If content is a list (Anthropic content blocks), extract text only
            if isinstance(content, list):
                text_parts = [b.get("text", "") for b in content if b.get("type") == "text"]
                text = " ".join(t for t in text_parts if t)
                if text:
                    clean.append({"role": msg["role"], "content": text})
                continue
            clean.append(msg)
        return clean

    async def chat(
        self,
        messages: list,
        system: str | None = None,
        force_model: str | None = None,
        tools: list[dict] | None = None,
        fallback_tools: list[dict] | None = None,
    ) -> dict:
        """Route a chat request with timeout handling and tool support.

        Args:
            messages: Conversation messages.
            system: System prompt.
            force_model: Override model selection.
            tools: Tool definitions in the primary model's format.
            fallback_tools: Tool definitions for the fallback model's format.
                If not provided, tools are dropped on fallback to avoid
                format incompatibility.
        """
        last_message = messages[-1]["content"] if messages else ""
        model_name = self.select_model(last_message, force_model)
        client = self._get_client(model_name)

        logger.info(f"Routing to: {model_name} (timeout: {self.timeout_seconds}s)")

        async def _try(c: Any, name: str, t: list[dict] | None = None, msgs: list | None = None) -> dict:
            try:
                result = await asyncio.wait_for(
                    c.chat(msgs or messages, system, tools=t),
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
            return await _try(client, model_name, tools)
        except Exception as e:
            fallback = "claude" if model_name == "ollama" else "ollama"
            if (fallback == "claude" and self._claude_available) or (fallback == "ollama" and self._ollama_available):
                logger.warning(f"Trying fallback to {fallback}...")
                fb_client = self._get_client(fallback)
                # Sanitize messages for the fallback model
                if fallback == "claude":
                    fb_messages = self._sanitize_messages_for_claude(messages)
                else:
                    fb_messages = self._sanitize_messages_for_ollama(messages)
                # Use fallback_tools if provided, otherwise drop tools
                fb_tools = fallback_tools
                try:
                    result = await _try(fb_client, fallback, fb_tools, fb_messages)
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
        s = {
            "ollama_available": self._ollama_available,
            "claude_available": self._claude_available,
            "claude_code_available": self._claude_code_available,
            "ollama_model": self.ollama.model if self.ollama else None,
            "claude_model": self.claude.model if self.claude else None,
            "claude_code_model": self.claude_code.model if self.claude_code else None,
            "complexity_threshold": self.complexity_threshold,
        }
        return s
