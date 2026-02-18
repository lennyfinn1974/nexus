"""Single LLM interaction with tool loop.

One AgentAttempt per model attempt. Handles: streaming the response,
collecting tool calls, executing them, formatting follow-up messages,
and looping until the model produces a final answer or hits the round limit.

Speculative Streaming Support:
    When ``speculative_ctx`` is set, the first streaming round checks if
    background RAG/KG retrieval has completed. If it arrives before ~200
    chars are streamed, a ``SpeculativeRestartSignal`` is raised so the
    AgentRunner can restart with full context. This saves 100-200ms on
    typical turns.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import TYPE_CHECKING, Any

from core.context_manager import get_context_limit
from core.errors import AgentAbortError, classify_error
from core.logging_config import get_turn_id
from core.message_formatter import MessageFormatter
from core.metrics import get_metrics
from core.tool_result_truncation import truncate_tool_result
from websocket_manager import websocket_manager

if TYPE_CHECKING:
    from core.agent_runner import AgentRunner, SpeculativeContext

logger = logging.getLogger("nexus.agent.attempt")

MAX_TOOL_ROUNDS = 5
STREAM_THROTTLE_SECS = 0.1  # Buffer chunks, flush every 100ms

# Speculative streaming threshold — restart if RAG arrives before this many chars
SPECULATIVE_CHAR_THRESHOLD = 200


class SpeculativeRestartSignal(Exception):
    """Raised when speculative context arrives early enough to restart."""
    pass


class AgentAttempt:
    """Execute a single LLM attempt including the tool loop."""

    # Tools whose results should be captured for web memory ingestion
    WEB_TOOLS = {"google_search", "web_fetch", "web_fetch_rendered"}

    def __init__(
        self,
        runner: AgentRunner,
        model_name: str,
        messages: list[dict],
        system: str,
        tools_for_api: list[dict] | None,
        ws_id: str,
        speculative_ctx: SpeculativeContext | None = None,
    ) -> None:
        self.runner = runner
        self.model_name = model_name
        self.messages = messages
        self.system = system
        self.tools_for_api = tools_for_api
        self.ws_id = ws_id
        self.use_native_tools = bool(tools_for_api)
        self.web_results: list[dict] = []  # Accumulated web tool results for memory
        self.speculative_ctx = speculative_ctx  # Background RAG/KG retrieval

    async def execute(self) -> str:
        """Stream, parse tool calls, execute, loop. Returns final response text."""
        round_num = 0
        final_response = ""
        prev_tool_names: list[str] = []  # Track tools called each round for circuit breaker

        while round_num <= MAX_TOOL_ROUNDS:
            # Check abort before each round
            if self.runner.abort.is_set():
                raise AgentAbortError("Request aborted by user")

            # After round 2 for Ollama, stop sending tools to force synthesis
            force_no_tools = (
                round_num >= 2
                and self.model_name == "ollama"
            )

            # Only send stream_start/stream_end on the first round —
            # subsequent rounds (tool-loop follow-ups) append to the same
            # assistant bubble via stream_chunk instead of creating new ones.
            is_first_round = (round_num == 0)

            # Check speculative context on first round only — if RAG/KG
            # arrives early, we'll restart with full context
            check_spec = is_first_round and self.speculative_ctx is not None

            try:
                text, native_tool_calls = await self._stream_round(
                    suppress_tools=force_no_tools,
                    send_stream_lifecycle=is_first_round,
                    check_speculative=check_spec,
                )
            except (AgentAbortError, SpeculativeRestartSignal):
                raise
            except Exception as exc:
                raise classify_error(exc) from exc

            # Execute tool calls
            tool_results = await self._execute_tools(native_tool_calls, full_response=text)

            # If no tools were called, we have the final response
            if not tool_results:
                final_response = text
                # If this wasn't the first round, send stream_end now
                if not is_first_round:
                    await websocket_manager.send_to_client(
                        self.ws_id, {"type": "stream_end", "model": self.model_name}
                    )
                break

            # Circuit breaker: if the same tool is being called repeatedly, stop
            current_tool_names = [tr.get("tool", "") for tr in tool_results]
            if prev_tool_names and current_tool_names == prev_tool_names:
                logger.warning(
                    f"[{self.ws_id}] Circuit breaker: same tools called twice "
                    f"({current_tool_names}), forcing synthesis"
                )
                # Don't execute more rounds — force synthesis with what we have
                round_num += 1
                followup = self._build_followup(text, native_tool_calls, tool_results, round_num)
                self.messages.extend(followup)
                # One final round with NO tools to force a text answer
                try:
                    text, _ = await self._stream_round(
                        suppress_tools=True, send_stream_lifecycle=False,
                    )
                    final_response = text
                except Exception:
                    final_response = text
                # Send final stream_end
                await websocket_manager.send_to_client(
                    self.ws_id, {"type": "stream_end", "model": self.model_name}
                )
                break

            prev_tool_names = current_tool_names
            round_num += 1
            if round_num > MAX_TOOL_ROUNDS:
                final_response = text
                logger.warning(f"[{self.ws_id}] Hit max tool rounds ({MAX_TOOL_ROUNDS})")
                # Send final stream_end
                await websocket_manager.send_to_client(
                    self.ws_id, {"type": "stream_end", "model": self.model_name}
                )
                break

            # Send tool completion as a non-visible event (not a system message)
            await websocket_manager.send_to_client(
                self.ws_id,
                {"type": "tool_status", "status": "complete", "count": len(tool_results)},
            )

            # Truncate oversized tool results to fit context window
            max_ctx = get_context_limit(self.model_name)
            for tr in tool_results:
                if "result" in tr and tr["result"]:
                    tr["result"] = truncate_tool_result(
                        tr["result"],
                        max_context_tokens=max_ctx,
                        num_results=len(tool_results),
                    )

            # Build follow-up messages for next round
            followup = self._build_followup(text, native_tool_calls, tool_results, round_num)
            self.messages.extend(followup)

        return final_response

    async def _stream_round(
        self, suppress_tools: bool = False,
        send_stream_lifecycle: bool = True,
        check_speculative: bool = False,
    ) -> tuple[str, list[dict]]:
        """Single streaming round. Returns (text, tool_calls).

        When *suppress_tools* is True, no tool definitions are sent —
        forcing the model to produce a text-only answer (synthesis).

        When *send_stream_lifecycle* is False, stream_start/stream_end
        are NOT sent — used for follow-up rounds in the tool loop so
        the Chat UI appends to the existing assistant bubble instead
        of creating a new one.

        When *check_speculative* is True and speculative_ctx is set,
        checks if background RAG/KG has arrived during streaming.
        If it arrives before SPECULATIVE_CHAR_THRESHOLD chars are
        streamed, raises SpeculativeRestartSignal to trigger a restart
        with full context. This avoids sending a response that lacks
        relevant memory context.
        """
        state = self.runner.state
        tools = None if suppress_tools else self.tools_for_api
        metrics = get_metrics()

        inference_start = time.time()

        model_name, stream = await state.model_router.chat_stream(
            self.messages,
            system=self.system,
            force_model=self.model_name,
            tools=tools,
        )
        self.model_name = model_name

        # Track model provider call
        metrics.record_count(f"{model_name}_calls")

        if send_stream_lifecycle:
            await websocket_manager.send_to_client(
                self.ws_id, {"type": "stream_start", "model": model_name}
            )

        full_response = ""
        native_tool_calls: list[dict] = []
        buffer = ""
        last_flush = time.monotonic()
        speculative_checked = False  # Only check once
        first_token_logged = False

        async for chunk in stream:
            # Log time-to-first-token (once) and update warm-model tracker
            if not first_token_logged and isinstance(chunk, str) and chunk:
                ttft_ms = int((time.time() - inference_start) * 1000)
                logger.info(f"Time-to-first-token: {ttft_ms}ms ({model_name})")
                first_token_logged = True
                # Update the adaptive speculative streaming tracker
                if model_name == "ollama":
                    import core.agent_runner as _runner
                    _runner._last_ollama_ttft_ms = ttft_ms

            # Check abort during streaming
            if self.runner.abort.is_set():
                if buffer:
                    await websocket_manager.send_to_client(
                        self.ws_id, {"type": "stream_chunk", "content": buffer}
                    )
                if send_stream_lifecycle:
                    await websocket_manager.send_to_client(
                        self.ws_id, {"type": "stream_end", "model": model_name}
                    )
                metrics.record_count("aborts")
                raise AgentAbortError("Request aborted by user")

            if isinstance(chunk, dict) and chunk.get("type") == "tool_use":
                # Flush text buffer before tool call
                if buffer:
                    await websocket_manager.send_to_client(
                        self.ws_id, {"type": "stream_chunk", "content": buffer}
                    )
                    buffer = ""
                native_tool_calls.append(chunk)
            elif isinstance(chunk, str):
                full_response += chunk
                buffer += chunk

                # ── Speculative restart check ──
                # If RAG/KG arrived while we were streaming and we haven't
                # sent much to the client yet, cancel and restart with
                # full context. We check at the SPECULATIVE_CHAR_THRESHOLD
                # boundary to avoid checking every chunk.
                if (
                    check_speculative
                    and not speculative_checked
                    and self.speculative_ctx
                    and len(full_response) >= SPECULATIVE_CHAR_THRESHOLD
                ):
                    speculative_checked = True
                    if (
                        self.speculative_ctx.is_ready()
                        and self.speculative_ctx.has_meaningful_context()
                    ):
                        # RAG/KG arrived — cancel this stream, don't send anything
                        # Send stream_end to cleanly close the UI bubble
                        if send_stream_lifecycle:
                            # Send a "restarting" hint so the UI can clear the partial
                            await websocket_manager.send_to_client(
                                self.ws_id,
                                {"type": "stream_end", "model": model_name, "speculative_restart": True},
                            )
                        logger.info(
                            f"Speculative restart triggered at {len(full_response)} chars"
                        )
                        raise SpeculativeRestartSignal()

                now = time.monotonic()
                if (now - last_flush) >= STREAM_THROTTLE_SECS:
                    await websocket_manager.send_to_client(
                        self.ws_id, {"type": "stream_chunk", "content": buffer}
                    )
                    buffer = ""
                    last_flush = now

        # Flush remaining buffer
        if buffer:
            await websocket_manager.send_to_client(
                self.ws_id, {"type": "stream_chunk", "content": buffer}
            )

        if send_stream_lifecycle:
            await websocket_manager.send_to_client(
                self.ws_id, {"type": "stream_end", "model": model_name}
            )

        # Record model inference timing
        inference_ms = int((time.time() - inference_start) * 1000)
        metrics.record("model_inference", inference_ms)

        return full_response, native_tool_calls

    async def _execute_tools(
        self,
        native_tool_calls: list[dict],
        full_response: str = "",
    ) -> list[dict]:
        """Execute tool calls and return results.

        Tries native tool calls first, falls back to legacy regex parsing
        on the full response text. Returns empty list if no tools were called.

        Each tool execution gets a span_id for tracing (C3).
        """
        state = self.runner.state
        tool_executor = getattr(state, "tool_executor", None)
        tool_results: list[dict] = []
        metrics = get_metrics()
        turn_id = get_turn_id()

        # Native tool calls (Anthropic or Ollama)
        if native_tool_calls and tool_executor:
            for tc in native_tool_calls:
                tool_name = tc.get("name", "")
                tool_input = tc.get("input", {})
                tool_id = tc.get("id", "")
                span_id = uuid.uuid4().hex[:8]

                # Send tool status as a non-visible event (not a system message)
                await websocket_manager.send_to_client(
                    self.ws_id,
                    {"type": "tool_status", "tool": tool_name, "status": "running"},
                )

                logger.info(
                    f"tool_start {turn_id} {span_id} {tool_name} "
                    f"{json.dumps(tool_input, default=str)[:200]}"
                )
                tool_start = time.time()

                try:
                    parsed_call = tool_executor.parse_anthropic_tool_call({
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_input,
                    })
                    result = await tool_executor.execute(parsed_call)

                    tool_ms = int((time.time() - tool_start) * 1000)
                    metrics.record("tool_execution", tool_ms)
                    metrics.record_count("tool_calls")

                    if result.success:
                        tool_results.append({
                            "tool": tool_name,
                            "result": result.result,
                            "tool_use_id": tool_id,
                        })
                        logger.info(
                            f"tool_end {turn_id} {span_id} {tool_name} "
                            f"{tool_ms}ms ok len={len(result.result or '')}"
                        )
                        # Capture web tool results for memory ingestion
                        if tool_name in self.WEB_TOOLS:
                            self.web_results.append({
                                "tool": tool_name,
                                "query": tool_input,
                                "result": result.result or "",
                            })
                    else:
                        tool_results.append({
                            "tool": tool_name,
                            "error": result.error,
                            "tool_use_id": tool_id,
                        })
                        metrics.record_count("tool_errors")
                        logger.info(
                            f"tool_end {turn_id} {span_id} {tool_name} "
                            f"{tool_ms}ms error={result.error}"
                        )
                except Exception as exc:
                    tool_ms = int((time.time() - tool_start) * 1000)
                    metrics.record("tool_execution", tool_ms)
                    metrics.record_count("tool_calls")
                    metrics.record_count("tool_errors")
                    logger.error(
                        f"tool_end {turn_id} {span_id} {tool_name} "
                        f"{tool_ms}ms exception={exc}"
                    )
                    tool_results.append({
                        "tool": tool_name,
                        "error": str(exc),
                        "tool_use_id": tool_id,
                    })

        # Fallback: parse text-based tool calls from response body.
        # qwen3-coder sometimes outputs <function=tool_name> XML tags instead
        # of using native function calling (especially with longer prompts).
        if not tool_results and full_response and tool_executor:
            fn_pattern = r"<function=([\w_]+)>\s*(.*?)\s*</function>"
            for match in re.finditer(fn_pattern, full_response, re.DOTALL):
                func_name = match.group(1)
                args_str = match.group(2).strip()
                try:
                    args = json.loads(args_str) if args_str else {}
                except (ValueError, json.JSONDecodeError):
                    args = {}

                logger.info(f"Fallback text-tool-call parsed: {func_name}({args})")
                try:
                    parsed = tool_executor.parse_anthropic_tool_call({
                        "id": f"text_fallback_{len(tool_results)}",
                        "name": func_name,
                        "input": args,
                    })
                    result = await tool_executor.execute(parsed)
                    if result.success:
                        tool_results.append({
                            "tool": func_name,
                            "result": result.result,
                            "tool_use_id": f"text_fallback_{len(tool_results)}",
                        })
                        if func_name.split("__")[-1] in self.WEB_TOOLS:
                            self.web_results.append({
                                "tool": func_name,
                                "query": args,
                                "result": result.result or "",
                            })
                    else:
                        tool_results.append({
                            "tool": func_name,
                            "error": result.error,
                            "tool_use_id": f"text_fallback_{len(tool_results)}",
                        })
                except Exception as exc:
                    logger.error(f"Fallback tool {func_name} failed: {exc}")

        # Legacy regex-based tool calls (fallback for text-based tool_call tags)
        if not tool_results and full_response:
            if state.plugin_manager:
                cleaned, plugin_results = await state.plugin_manager.process_tool_calls(
                    full_response
                )
                if plugin_results:
                    tool_results.extend(plugin_results)

            if state.skills_engine:
                from core.message_processor import process_skill_actions
                skill_results = await process_skill_actions(full_response, state.skills_engine)
                if skill_results:
                    tool_results.extend(skill_results)

        return tool_results

    def _build_followup(
        self,
        text: str,
        tool_calls: list[dict],
        tool_results: list[dict],
        round_num: int,
    ) -> list[dict]:
        """Build follow-up messages for the next tool round."""
        if tool_calls and self.use_native_tools and self.model_name == "claude":
            return MessageFormatter.format_anthropic(text, tool_calls, tool_results)
        elif tool_calls and self.use_native_tools and self.model_name == "ollama":
            return MessageFormatter.format_ollama(text, tool_calls, tool_results)
        else:
            return MessageFormatter.format_legacy(text, tool_results, round_num)
