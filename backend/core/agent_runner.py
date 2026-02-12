"""Outer orchestrator for a user request.

One AgentRunner per WebSocket message. Handles: model selection, context
building, system prompt assembly, tool definition preparation, and
delegating to AgentAttempt for the actual LLM interaction. Supports
sub-agent orchestration for parallel/multi-model execution.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from core.agent_attempt import AgentAttempt
from core.context_manager import build_conversation_context, check_context_fits
from core.errors import (
    AgentAbortError,
    AgentError,
    AuthError,
    ContextOverflowError,
    ModelTimeoutError,
    ModelUnavailableError,
    RateLimitError,
    classify_error,
)
from core.system_prompt import build_system_prompt
from websocket_manager import websocket_manager

# @ syntax pattern — matches @skill-name at word boundaries
_AT_SKILL_PATTERN = re.compile(r"@([\w-]+)")

# Context budget per @-invoked skill (chars)
_AT_CONTEXT_BUDGET = {
    "ollama": 8000,   # Ollama 32K context — keep each skill to ~8K chars
    "claude": 50000,  # Claude 200K context — generous budget
}
_AT_CONTEXT_DEFAULT = 8000

logger = logging.getLogger("nexus.agent.runner")

MAX_FAILOVER_ATTEMPTS = 3

# ── Sub-agent orchestration triggers ──────────────────────────────

# Explicit keywords that trigger orchestration
_ORCHESTRATION_KEYWORDS = re.compile(
    r"\b(sub.?agents?|in parallel|second opinion|verify this|double.?check|"
    r"review my|critique|research these|compare these|fact.?check)\b",
    re.IGNORECASE,
)

# Build/review pattern — user wants something built and then reviewed
_BUILD_REVIEW_PATTERN = re.compile(
    r"\b(write|create|build|implement|code|draft)\b.*\b(then|and)\b.*\b(review|check|critique|verify)\b",
    re.IGNORECASE,
)

# BLD:APP code task pattern — auto-detect during agentic mode
_CODE_TASK_PATTERN = re.compile(
    r"\b(build|create|implement|write|refactor|add|fix|update|modify)\b",
    re.IGNORECASE,
)


class AgentRunner:
    """Orchestrate a complete user request: routing, context, execution, failover."""

    def __init__(
        self,
        state: Any,
        ws_id: str,
        conv_id: str,
        text: str,
        force_model: str | None,
    ) -> None:
        self.state = state
        self.ws_id = ws_id
        self.conv_id = conv_id
        self.text = text
        self.force_model = force_model
        self.abort = asyncio.Event()

    async def run(self) -> str:
        """Execute the request. Returns the final response text."""
        s = self.state

        # Register with work registry
        from core.work_registry import work_registry
        work_item_id = f"agent-{self.ws_id or 'api'}-{self.conv_id[:8]}"
        try:
            await work_registry.register(
                work_item_id, "agent", self.text[:80],
                status="running", conv_id=self.conv_id,
                model=self.force_model or "auto",
            )
        except Exception:
            pass  # Don't fail the request if registry is unavailable

        # 1. Get model candidates (local-first)
        candidates = self._get_candidates()

        # 2. Build context (message already saved to DB by caller)
        messages = await build_conversation_context(
            db=s.db,
            conv_id=self.conv_id,
            new_user_message="",  # Already in DB from ws.py
            model_router=s.model_router,
            system_prompt="",  # Will be built per-attempt
        )

        # 3. Detect @skill-name references for action boosting
        at_skill_ids = self._get_at_skill_ids()

        # 3b. Check if this request should use sub-agent orchestration
        should_orch, strategy = self._should_orchestrate()
        if should_orch:
            return await self._run_orchestrated(messages, strategy)

        # 4. Try each candidate model
        last_error: Exception | None = None
        compaction_retries = 0

        for attempt_idx, model_name in enumerate(candidates):
            if attempt_idx >= MAX_FAILOVER_ATTEMPTS:
                break

            if self.abort.is_set():
                raise AgentAbortError("Request aborted by user")

            # Build system prompt for this model
            tool_executor = getattr(s, "tool_executor", None)
            has_tools = bool(tool_executor and s.plugin_manager.all_tools)
            # Claude Code uses MCP tools internally — treat as native (no legacy tags)
            use_native_tools = has_tools and model_name in ("claude", "ollama", "claude_code")
            tool_mode = "native" if use_native_tools else "legacy"

            system = build_system_prompt(
                s.cfg, s.plugin_manager, tool_calling_mode=tool_mode, model=model_name,
            )

            # Skill context injection — @skill-name explicit invocation or auto-match
            skill_context = self._build_at_skill_context(model_name)
            if skill_context:
                system += f"\n\n{skill_context}"
            else:
                # No @ skills — fall back to automatic skill matching
                auto_context = await s.skills_engine.build_skill_context(self.text)
                if auto_context:
                    system += f"\n\n{auto_context}"

            # Build tool definitions — boost @skill actions into the tool set
            # Claude Code gets tools via MCP, not API — don't send tools_for_api
            tools_for_api = None
            if use_native_tools and tool_executor and model_name != "claude_code":
                if model_name == "claude":
                    tools_for_api = tool_executor.to_anthropic_tools()
                else:
                    tools_for_api = tool_executor.to_ollama_tools(
                        message=self.text,
                        boost_skill_ids=at_skill_ids,
                    )

            # Context guard — check if messages fit before sending
            if not check_context_fits(messages, system, model_name):
                logger.warning(f"Context too large for {model_name}, raising overflow")
                raise ContextOverflowError(
                    f"Messages exceed context limit for {model_name}"
                )

            # Create and execute attempt
            attempt = AgentAttempt(
                runner=self,
                model_name=model_name,
                messages=list(messages),  # Copy so failover gets fresh messages
                system=system,
                tools_for_api=tools_for_api,
                ws_id=self.ws_id,
            )

            try:
                result = await attempt.execute()
                try:
                    await work_registry.update(work_item_id, "completed")
                except Exception:
                    pass
                return result

            except AgentAbortError:
                try:
                    await work_registry.update(work_item_id, "cancelled")
                except Exception:
                    pass
                raise

            except ContextOverflowError as exc:
                if compaction_retries < 2:
                    logger.warning(
                        f"Context overflow on {model_name}, compacting "
                        f"(attempt {compaction_retries + 1})"
                    )
                    compaction_retries += 1
                    # Simple compaction: halve the message window
                    messages = self._compact_messages(messages)
                    # Insert the same model again for retry
                    candidates.insert(attempt_idx + 1, model_name)
                    last_error = exc
                    continue
                last_error = exc
                continue  # Try next model candidate

            except (ModelTimeoutError, RateLimitError, ModelUnavailableError) as exc:
                logger.warning(f"{model_name} failed ({exc.error_type}), trying next candidate")
                if attempt_idx + 1 < len(candidates):
                    await websocket_manager.send_to_client(
                        self.ws_id,
                        {
                            "type": "system",
                            "content": f"{model_name} {exc.error_type}, switching to {candidates[attempt_idx + 1]}...",
                        },
                    )
                last_error = exc
                continue

            except AuthError as exc:
                logger.warning(f"{model_name} auth error, trying next candidate")
                last_error = exc
                continue

            except AgentError as exc:
                last_error = exc
                continue

            except Exception as exc:
                last_error = classify_error(exc)
                continue

        # All candidates exhausted
        try:
            await work_registry.update(work_item_id, "failed",
                                       {"error": str(last_error) if last_error else "all candidates exhausted"})
        except Exception:
            pass
        if last_error:
            raise last_error
        raise RuntimeError("All models failed — no candidates available")

    # ── Sub-agent Orchestration ─────────────────────────────────

    def _should_orchestrate(self) -> tuple[bool, str]:
        """Check if this request should use sub-agent orchestration.

        Returns (should_orchestrate, strategy_name). Opt-in, not always-on.
        """
        cfg = self.state.cfg

        # Master switch
        if not cfg.get_bool("SUB_AGENT_ENABLED", True):
            return False, ""

        text = self.text.lower()

        # 1. Explicit build+review pattern
        if _BUILD_REVIEW_PATTERN.search(self.text):
            # Check if in BLD:APP mode (forced to claude_code)
            session_data = websocket_manager.get_session_data(self.ws_id) or {}
            if session_data.get("force_model") == "claude_code" or self.force_model == "claude_code":
                return True, "build_review_code"
            return True, "build_review"

        # 2. Explicit orchestration keywords
        if _ORCHESTRATION_KEYWORDS.search(self.text):
            # Determine strategy from context
            if any(kw in text for kw in ["verify", "fact-check", "double-check"]):
                return True, "verify"
            if any(kw in text for kw in ["research these", "compare these", "in parallel"]):
                return True, "parallel_research"
            if any(kw in text for kw in ["review my", "critique", "second opinion"]):
                return True, "build_review"
            return True, "parallel_research"

        # 3. BLD:APP auto-orchestration — code tasks during agentic mode
        session_data = websocket_manager.get_session_data(self.ws_id) or {}
        if session_data.get("force_model") == "claude_code":
            if cfg.get_bool("SUB_AGENT_AUTO_ENABLED", False):
                if _CODE_TASK_PATTERN.search(self.text):
                    return True, "build_review_code"

        # 4. Auto-detection (if enabled) — multiple questions
        if cfg.get_bool("SUB_AGENT_AUTO_ENABLED", False):
            if self.text.count("?") >= 2 and len(self.text) > 80:
                return True, "parallel_research"

        return False, ""

    async def _run_orchestrated(self, messages: list[dict], strategy: str) -> str:
        """Execute the request using sub-agent orchestration."""
        from core.sub_agent import OrchestrationStrategy, SubAgentOrchestrator

        cfg = self.state.cfg

        # Build the orchestration from strategy
        if strategy == "parallel_research":
            queries = self._split_into_queries(self.text)
            orchestration = OrchestrationStrategy.parallel_research(queries, cfg)
        elif strategy == "build_review":
            orchestration = OrchestrationStrategy.build_review(self.text, cfg=cfg)
        elif strategy == "build_review_code":
            orchestration = OrchestrationStrategy.build_review_code(self.text, cfg=cfg)
        elif strategy == "verify":
            orchestration = OrchestrationStrategy.verify(self.text, cfg=cfg)
        else:
            logger.warning(f"Unknown orchestration strategy: {strategy}, falling back to normal")
            return ""  # Caller should fall through to normal path

        # Notify user
        agent_count = len(orchestration.specs)
        await websocket_manager.send_to_client(
            self.ws_id,
            {
                "type": "system",
                "content": (
                    f"Launching {agent_count} sub-agents ({strategy.replace('_', ' ')})..."
                ),
            },
        )

        logger.info(
            f"[{self.ws_id}] Orchestration triggered: {strategy} "
            f"with {agent_count} sub-agents"
        )

        # Create and execute orchestrator
        orchestrator = SubAgentOrchestrator(
            state=self.state,
            ws_id=self.ws_id,
            conv_id=self.conv_id,
            parent_abort=self.abort,
            messages=messages,
            cfg=cfg,
        )

        result = await orchestrator.execute(orchestration)
        return result

    @staticmethod
    def _split_into_queries(text: str) -> list[str]:
        """Split a multi-part request into individual queries.

        Tries several splitting strategies:
        1. Pipe delimiter (|)
        2. Numbered list (1. ... 2. ...)
        3. Semicolons
        4. "and" conjunctions (only for short segments)
        5. Falls back to the full text as a single query
        """
        # Strip common prefixes
        text = re.sub(r"^(research|compare|look up|search for)\s+(these|the following)?\s*:?\s*", "", text, flags=re.IGNORECASE)

        # 1. Pipe delimiter
        if "|" in text:
            parts = [p.strip() for p in text.split("|") if p.strip()]
            if len(parts) >= 2:
                return parts

        # 2. Numbered list
        numbered = re.split(r"\d+\.\s+", text)
        numbered = [p.strip() for p in numbered if p.strip()]
        if len(numbered) >= 2:
            return numbered

        # 3. Semicolons
        if ";" in text:
            parts = [p.strip() for p in text.split(";") if p.strip()]
            if len(parts) >= 2:
                return parts

        # 4. "and" for short segments
        if " and " in text.lower():
            parts = re.split(r"\s+and\s+", text, flags=re.IGNORECASE)
            parts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 10]
            if len(parts) >= 2:
                return parts

        # 5. Fallback: full text as single query
        return [text]

    def _get_at_skill_ids(self) -> list[str]:
        """Extract @skill-name references and return matching skill IDs.

        Used to boost those skills' actions into the tool set so the model
        can actually call them even if ToolSelector wouldn't normally include them.
        """
        at_matches = _AT_SKILL_PATTERN.findall(self.text)
        if not at_matches:
            return []

        skills_engine = self.state.skills_engine
        ids = []
        for skill_name in at_matches:
            skill = skills_engine.skills.get(skill_name)
            if skill and skill.actions:
                ids.append(skill.id)
        return ids

    def _build_at_skill_context(self, model_name: str) -> str:
        """Extract @skill-name references and inject full skill knowledge.

        When a user says ``@brainstorming plan a SaaS MVP``, the brainstorming
        skill's full knowledge.md is injected into the system prompt (without
        the 2000-char truncation that automatic matching applies).

        Context budget is model-aware: Ollama gets 8K chars per skill,
        Claude gets 50K chars per skill.
        """
        at_matches = _AT_SKILL_PATTERN.findall(self.text)
        if not at_matches:
            return ""

        budget = _AT_CONTEXT_BUDGET.get(model_name, _AT_CONTEXT_DEFAULT)
        skills_engine = self.state.skills_engine
        parts = ["## Requested Skills\n"]
        found_any = False

        for skill_name in at_matches:
            skill = skills_engine.skills.get(skill_name)
            if not skill:
                logger.debug(f"@{skill_name} not found in installed skills")
                continue

            knowledge = skill.get_knowledge()
            if not knowledge:
                continue

            # Strip YAML frontmatter
            if knowledge.startswith("---"):
                end = knowledge.find("---", 3)
                if end != -1:
                    knowledge = knowledge[end + 3:].strip()

            # Apply model-aware context budget
            if len(knowledge) > budget:
                knowledge = knowledge[:budget] + "\n...(truncated to fit context)"

            parts.append(f"### {skill.name}\n{knowledge}\n")
            found_any = True
            logger.info(f"@{skill_name}: injected {len(knowledge)} chars")

        if not found_any:
            return ""

        return "\n".join(parts)

    def _get_candidates(self) -> list[str]:
        """Return ordered list of model candidates. Local-first.

        Priority order:
        1. ollama (local, fast, free)
        2. claude (API, reliable, tool-calling)
        3. claude_code (CLI, agentic, MCP tools)
        """
        router = self.state.model_router

        if self.force_model:
            # User explicitly chose a model
            if self.force_model == "claude" and router._claude_available:
                return ["claude"]
            elif self.force_model in ("ollama", "local") and router._ollama_available:
                return ["ollama"]
            elif self.force_model == "claude_code" and router._claude_code_available:
                return ["claude_code"]
            # Forced model not available — try all
            return self._all_candidates()

        # Local-first: Ollama → Claude → Claude Code
        return self._all_candidates()

    def _all_candidates(self) -> list[str]:
        """Return all available models, Ollama first."""
        router = self.state.model_router
        candidates = []
        if router._ollama_available:
            candidates.append("ollama")
        if router._claude_available:
            candidates.append("claude")
        if router._claude_code_available:
            candidates.append("claude_code")
        if not candidates:
            raise RuntimeError("No models are currently available")
        return candidates

    @staticmethod
    def _compact_messages(messages: list[dict]) -> list[dict]:
        """Simple compaction: keep first 2 messages (summary if present) + last half.

        This is a mechanical fallback. The background summary generator
        handles proper LLM-based compaction for long conversations.
        """
        if len(messages) <= 4:
            return messages

        # Keep any summary prefix (first 2 msgs if they look like summary)
        prefix = []
        rest = messages
        if (
            len(messages) >= 2
            and isinstance(messages[0].get("content"), str)
            and "summary" in messages[0]["content"].lower()
        ):
            prefix = messages[:2]
            rest = messages[2:]

        # Keep the most recent half
        keep = max(len(rest) // 2, 2)
        compacted = prefix + rest[-keep:]
        logger.info(
            f"Compacted messages: {len(messages)} -> {len(compacted)} "
            f"(dropped {len(messages) - len(compacted)} older messages)"
        )
        return compacted
