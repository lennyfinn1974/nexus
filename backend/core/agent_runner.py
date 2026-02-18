"""Outer orchestrator for a user request.

One AgentRunner per WebSocket message. Handles: model selection, context
building, system prompt assembly, tool definition preparation, and
delegating to AgentAttempt for the actual LLM interaction. Supports
sub-agent orchestration for parallel/multi-model execution.

Speculative Streaming (Feb 2026):
    Instead of waiting for RAG embedding + vector search (50-200ms) before
    starting inference, we launch LLM streaming immediately with conversation
    history + passive memory. RAG/KG retrieval runs concurrently. If RAG
    finishes before ~200 chars are streamed, we cancel the speculative stream
    and restart with full context. Otherwise the LLM response continues
    without RAG context for this turn (RAG data is available next turn).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from core.agent_attempt import AgentAttempt, SpeculativeRestartSignal
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
from core.logging_config import get_turn_id
from core.metrics import get_metrics
from core.system_prompt import build_context_messages, build_system_prompt
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

# Speculative streaming: max chars streamed before we give up waiting for RAG
# If RAG arrives before we've streamed this many chars, we restart with full context
SPECULATIVE_RESTART_CHAR_LIMIT = 200

# Minimum chars of RAG/KG context worth restarting for
# Don't restart the stream for trivial context additions
SPECULATIVE_MIN_CONTEXT_LEN = 50

# Adaptive speculative streaming: if the last Ollama TTFT was below this
# threshold, the model is warm in VRAM. In that case, waiting for RAG/KG
# upfront (~100-200ms) and doing a single inference pass is faster than
# paying two TTFTs (speculative + restart). Above this threshold, the model
# is cold-loading from disk and speculative streaming helps hide RAG latency.
# Data: warm TTFT = 3.7-6.4s, cold TTFT = 9-12s. Threshold at 8s.
WARM_MODEL_TTFT_THRESHOLD_MS = 8000

# Module-level TTFT tracker — updated after each Ollama inference.
# Start optimistic (assume warm) — llama-server keeps model loaded,
# and even Ollama with KEEP_ALIVE is typically warm.  The first real
# TTFT measurement will override this immediately.
_last_ollama_ttft_ms: float = 3000  # Start optimistic (assume warm)


class SpeculativeContext:
    """Holds background RAG/KG retrieval state for speculative streaming.

    Created before starting LLM inference. The AgentAttempt checks
    ``is_ready()`` during streaming — if RAG/KG results have arrived
    and fewer than SPECULATIVE_RESTART_CHAR_LIMIT chars have been
    streamed, it raises SpeculativeRestartSignal to trigger a restart
    with full context.
    """

    def __init__(self) -> None:
        self.rag_context: str = ""
        self.kg_context: str = ""
        self._ready = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._start_time: float = 0.0

    def start(self, rag_coro, kg_coro) -> None:
        """Launch RAG + KG retrieval as a background task."""
        self._start_time = time.time()
        self._task = asyncio.create_task(self._fetch(rag_coro, kg_coro))

    async def _fetch(self, rag_coro, kg_coro) -> None:
        """Run RAG + KG concurrently, set ready when done."""
        try:
            results = await asyncio.wait_for(
                asyncio.gather(rag_coro, kg_coro, return_exceptions=True),
                timeout=2.0,
            )
            self.rag_context = results[0] if isinstance(results[0], str) else ""
            self.kg_context = results[1] if isinstance(results[1], str) else ""
        except asyncio.TimeoutError:
            logger.debug("Speculative RAG/KG retrieval timed out (2s)")
        except Exception:
            pass
        finally:
            elapsed = int((time.time() - self._start_time) * 1000)
            has_content = bool(self.rag_context or self.kg_context)
            logger.info(
                f"Speculative context ready: {elapsed}ms "
                f"rag={len(self.rag_context)}chars kg={len(self.kg_context)}chars"
            )
            self._ready.set()

    def is_ready(self) -> bool:
        """Check if RAG/KG results have arrived (non-blocking)."""
        return self._ready.is_set()

    def has_meaningful_context(self) -> bool:
        """Check if RAG/KG produced enough context to justify a restart."""
        return len(self.rag_context) + len(self.kg_context) >= SPECULATIVE_MIN_CONTEXT_LEN

    def cancel(self) -> None:
        """Cancel the background task if still running."""
        if self._task and not self._task.done():
            self._task.cancel()

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
        """Execute the request with speculative streaming.

        Instead of waiting for RAG/KG retrieval before starting inference,
        we start the LLM immediately with conversation history + fast context
        (passive memory, bulletin). RAG/KG run concurrently. If they finish
        before the LLM has streamed ~200 chars, we restart with full context.
        This typically saves 100-200ms on the first-token latency.
        """
        s = self.state
        t0 = time.time()

        # Register with work registry (fire-and-forget — don't await if slow)
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

        t1 = time.time()

        # 1. Get model candidates (local-first)
        candidates = self._get_candidates()

        # 2. Build context (user message already saved to DB by caller)
        # Use the primary candidate model to set history window size:
        # Ollama → 8 messages (saves ~600 tokens), Claude → 20 messages
        primary_model = candidates[0] if candidates else "ollama"
        messages = await build_conversation_context(
            db=s.db,
            conv_id=self.conv_id,
            new_user_message="",  # Already in DB from ws.py
            model_router=s.model_router,
            system_prompt="",  # Will be built per-attempt
            model=primary_model,
        )

        t2 = time.time()

        # 3. Detect @skill-name references for action boosting
        at_skill_ids = self._get_at_skill_ids()

        # 3b. Check if this request should use sub-agent orchestration
        should_orch, strategy = self._should_orchestrate()
        if should_orch:
            return await self._run_orchestrated(messages, strategy)

        # ── Fast context (sub-ms, no I/O) ──
        passive_mem = getattr(s, "passive_memory", None)
        rag_pipeline = getattr(s, "rag_pipeline", None)
        knowledge_graph = getattr(s, "knowledge_graph", None)

        # Passive memory: regex-based, ~0ms
        memory_context = ""
        if passive_mem:
            try:
                memory_context = await passive_mem.get_context_for_prompt(limit=5)
            except Exception:
                pass

        # Bulletin: sync cached in-memory, ~0ms
        bulletin = getattr(s, "memory_bulletin", None)
        bulletin_context = bulletin.get_bulletin() if bulletin else ""

        t3 = time.time()
        logger.info(
            f"Pre-inference pipeline: registry={int((t1-t0)*1000)}ms "
            f"context={int((t2-t1)*1000)}ms fast_ctx={int((t3-t2)*1000)}ms "
            f"total={int((t3-t0)*1000)}ms msgs={len(messages)}"
        )

        # ── RAG/KG retrieval: adaptive speculative vs. upfront ──
        # If the model is warm (last TTFT < 5s), RAG (~100-200ms) will finish
        # well before the first token. Waiting upfront avoids paying two TTFTs.
        # If the model is cold (last TTFT > 5s), speculative streaming hides
        # the RAG latency behind the long model-load time.
        global _last_ollama_ttft_ms
        spec_ctx = None
        rag_context = ""
        kg_context = ""
        has_rag = rag_pipeline and getattr(rag_pipeline, "is_active", False)
        has_kg = knowledge_graph and getattr(knowledge_graph, "entity_count", 0) > 0
        model_is_warm = _last_ollama_ttft_ms < WARM_MODEL_TTFT_THRESHOLD_MS

        # Skip RAG/KG for trivial queries (greetings, confirmations, meta-questions).
        # These never need personal memory — saves ~150ms + ~300 tokens of context.
        _trivial_text = self.text.strip().lower()
        _skip_rag = (
            len(_trivial_text) < 20
            or _trivial_text in ("hi", "hello", "hey", "thanks", "thank you", "ok", "yes", "no", "sure", "bye")
            or _trivial_text.startswith(("hi ", "hello ", "hey ", "good morning", "good afternoon", "good evening"))
            or any(p in _trivial_text for p in ("you seem", "you're slow", "what changed", "are you ok", "how are you"))
        )
        if _skip_rag:
            has_rag = False
            has_kg = False
            logger.debug(f"Skipping RAG/KG for trivial query: {self.text[:40]}")

        if has_rag or has_kg:
            # Shared RAG/KG coroutine builders
            model_for_rag = self.force_model or "ollama"
            default_limit = 3 if model_for_rag == "ollama" else 5
            rag_limit = int(s.cfg.get("RAG_MAX_RESULTS", str(default_limit)))
            if model_for_rag == "ollama":
                rag_limit = min(rag_limit, 3)

            async def _do_rag():
                if not has_rag:
                    return ""
                return await rag_pipeline.retrieve(
                    query=self.text,
                    model=model_for_rag,
                    limit=rag_limit,
                    source_conv=self.conv_id,
                )

            async def _do_kg():
                if not has_kg:
                    return ""
                return await knowledge_graph.query_related(
                    text=self.text, limit=8, max_depth=2,
                )

            if model_is_warm:
                # ── Warm path: wait for RAG/KG upfront, single inference pass ──
                logger.info(
                    f"Warm model path (last TTFT={int(_last_ollama_ttft_ms)}ms < "
                    f"{WARM_MODEL_TTFT_THRESHOLD_MS}ms) — awaiting RAG/KG upfront"
                )
                rag_start = time.time()
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(_do_rag(), _do_kg(), return_exceptions=True),
                        timeout=2.0,
                    )
                    rag_context = results[0] if isinstance(results[0], str) else ""
                    kg_context = results[1] if isinstance(results[1], str) else ""
                except asyncio.TimeoutError:
                    logger.debug("Upfront RAG/KG timed out (2s)")
                rag_ms = int((time.time() - rag_start) * 1000)
                logger.info(
                    f"Upfront RAG/KG: {rag_ms}ms "
                    f"rag={len(rag_context)}chars kg={len(kg_context)}chars"
                )
            else:
                # ── Cold path: speculative streaming (launch RAG/KG in background) ──
                logger.info(
                    f"Cold model path (last TTFT={int(_last_ollama_ttft_ms)}ms >= "
                    f"{WARM_MODEL_TTFT_THRESHOLD_MS}ms) — speculative streaming"
                )
                spec_ctx = SpeculativeContext()
                spec_ctx.start(_do_rag(), _do_kg())

        # 4. Try each candidate model
        last_error: Exception | None = None
        compaction_retries = 0
        speculative_restarted = False

        for attempt_idx, model_name in enumerate(candidates):
            if attempt_idx >= MAX_FAILOVER_ATTEMPTS:
                break

            if self.abort.is_set():
                raise AgentAbortError("Request aborted by user")

            attempt_start = time.time()

            # After a speculative restart, use full context from spec_ctx
            # (On warm path, rag_context/kg_context are already set above)
            if speculative_restarted and spec_ctx:
                rag_context = spec_ctx.rag_context
                kg_context = spec_ctx.kg_context

            # Build system prompt for this model
            tool_executor = getattr(s, "tool_executor", None)
            has_tools = bool(tool_executor and s.plugin_manager.all_tools)
            use_native_tools = has_tools and model_name in ("claude", "ollama", "claude_code")
            tool_mode = "native" if use_native_tools else "legacy"

            system = build_system_prompt(
                s.cfg, s.plugin_manager, tool_calling_mode=tool_mode,
                model=model_name, memory_context=memory_context,
                rag_context=rag_context, kg_context=kg_context,
                bulletin_context=bulletin_context,
            )

            # ── Ollama: context as messages, not system prompt ──
            # Insert RAG/KG/memory as a context message right before
            # the last user message.  This keeps the system prompt lean
            # while still providing knowledge to the model.
            attempt_messages = list(messages)
            if model_name == "ollama":
                ctx_msgs = build_context_messages(
                    memory_context=memory_context,
                    rag_context=rag_context,
                    kg_context=kg_context,
                    bulletin_context=bulletin_context,
                )
                if ctx_msgs:
                    # Insert context before the last user message
                    # so the model sees: [...history, context, user_msg]
                    if attempt_messages and attempt_messages[-1].get("role") == "user":
                        attempt_messages = (
                            attempt_messages[:-1] + ctx_msgs + [attempt_messages[-1]]
                        )
                    else:
                        attempt_messages.extend(ctx_msgs)
                    logger.info(
                        f"Ollama context message injected: "
                        f"{len(ctx_msgs[0]['content'])}chars"
                    )

            # Skill context injection — for Ollama, skip entirely to
            # protect the lean system prompt.  Skills are accessible via
            # tool definitions.  For Claude/Claude Code, inject fully.
            if model_name != "ollama":
                skill_context = self._build_at_skill_context(model_name)
                if skill_context:
                    system += f"\n\n{skill_context}"
                else:
                    auto_context = await s.skills_engine.build_skill_directory(self.text)
                    if auto_context:
                        system += f"\n\n{auto_context}"
            else:
                # For Ollama with @skill references, inject as a
                # short context message instead of bloating system prompt
                skill_context = self._build_at_skill_context(model_name)
                if skill_context:
                    skill_msg = {
                        "role": "system",
                        "content": f"[Skill knowledge]\n{skill_context[:2000]}",
                    }
                    # Insert before last user message
                    if attempt_messages and attempt_messages[-1].get("role") == "user":
                        attempt_messages = (
                            attempt_messages[:-1] + [skill_msg] + [attempt_messages[-1]]
                        )
                    else:
                        attempt_messages.append(skill_msg)

            # ── Hard system prompt guard for Ollama ──
            if model_name == "ollama" and len(system) > 500:
                logger.warning(
                    f"Ollama system prompt too long ({len(system)}chars), "
                    f"truncating to 500 chars to preserve native tool calling"
                )
                system = system[:500]

            # Build tool definitions
            tools_for_api = None
            if use_native_tools and tool_executor and model_name != "claude_code":
                if model_name == "claude":
                    tools_for_api = tool_executor.to_anthropic_tools()
                else:
                    tools_for_api = tool_executor.to_ollama_tools(
                        message=self.text,
                        boost_skill_ids=at_skill_ids,
                    )

            attempt_prep_ms = int((time.time() - attempt_start) * 1000)
            logger.info(
                f"Attempt prep ({model_name}): {attempt_prep_ms}ms "
                f"system={len(system)}chars tools={len(tools_for_api or [])} "
                f"msgs={len(attempt_messages)}"
            )

            # Context guard
            if not check_context_fits(messages, system, model_name):
                logger.warning(f"Context too large for {model_name}, raising overflow")
                raise ContextOverflowError(
                    f"Messages exceed context limit for {model_name}"
                )

            # Create and execute attempt — pass speculative context on first try
            attempt = AgentAttempt(
                runner=self,
                model_name=model_name,
                messages=attempt_messages,
                system=system,
                tools_for_api=tools_for_api,
                ws_id=self.ws_id,
                speculative_ctx=spec_ctx if not speculative_restarted else None,
            )
            self._attempt = attempt

            try:
                result = await attempt.execute()
                # Clean up speculative context
                if spec_ctx:
                    spec_ctx.cancel()
                try:
                    await work_registry.update(work_item_id, "completed")
                except Exception:
                    pass
                return result

            except SpeculativeRestartSignal:
                # RAG/KG arrived early — restart with full context
                speculative_restarted = True
                logger.info(
                    f"Speculative restart: RAG={len(spec_ctx.rag_context if spec_ctx else '')}chars "
                    f"KG={len(spec_ctx.kg_context if spec_ctx else '')}chars — "
                    f"restarting {model_name} with full context"
                )
                get_metrics().record_count("speculative_restarts")
                # Re-insert the same model for retry with full context
                candidates.insert(attempt_idx + 1, model_name)
                continue

            except AgentAbortError:
                if spec_ctx:
                    spec_ctx.cancel()
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
                    messages = self._compact_messages(messages)
                    candidates.insert(attempt_idx + 1, model_name)
                    last_error = exc
                    continue
                last_error = exc
                continue

            except (ModelTimeoutError, RateLimitError, ModelUnavailableError) as exc:
                get_metrics().record_count("failovers")
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
        if spec_ctx:
            spec_ctx.cancel()
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

        # Send the synthesised output to the WebSocket as a stream
        # (sub-agent progress messages were sent during execution,
        #  but the final merged result needs its own stream_start/chunk/end
        #  so the Chat UI displays it as the assistant response)
        if self.ws_id and result:
            await websocket_manager.send_to_client(
                self.ws_id,
                {"type": "stream_start", "model": "multi-agent"},
            )
            await websocket_manager.send_to_client(
                self.ws_id,
                {"type": "stream_chunk", "content": result},
            )
            await websocket_manager.send_to_client(
                self.ws_id,
                {"type": "stream_end", "model": "multi-agent"},
            )

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
