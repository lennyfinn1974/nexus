"""Single LLM interaction with tool loop.

One AgentAttempt per model attempt. Handles: streaming the response,
collecting tool calls, executing them, formatting follow-up messages,
and looping until the model produces a final answer or hits the round limit.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from core.context_manager import get_context_limit
from core.errors import AgentAbortError, classify_error
from core.message_formatter import MessageFormatter
from core.tool_result_truncation import truncate_tool_result
from websocket_manager import websocket_manager

if TYPE_CHECKING:
    from core.agent_runner import AgentRunner

logger = logging.getLogger("nexus.agent.attempt")

MAX_TOOL_ROUNDS = 5
STREAM_THROTTLE_SECS = 0.1  # Buffer chunks, flush every 100ms


class AgentAttempt:
    """Execute a single LLM attempt including the tool loop."""

    def __init__(
        self,
        runner: AgentRunner,
        model_name: str,
        messages: list[dict],
        system: str,
        tools_for_api: list[dict] | None,
        ws_id: str,
    ) -> None:
        self.runner = runner
        self.model_name = model_name
        self.messages = messages
        self.system = system
        self.tools_for_api = tools_for_api
        self.ws_id = ws_id
        self.use_native_tools = bool(tools_for_api)

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

            try:
                text, native_tool_calls = await self._stream_round(
                    suppress_tools=force_no_tools,
                )
            except AgentAbortError:
                raise
            except Exception as exc:
                raise classify_error(exc) from exc

            # Execute tool calls
            tool_results = await self._execute_tools(native_tool_calls, full_response=text)

            # If no tools were called, we have the final response
            if not tool_results:
                final_response = text
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
                    text, _ = await self._stream_round(suppress_tools=True)
                    final_response = text
                except Exception:
                    final_response = text
                break

            prev_tool_names = current_tool_names
            round_num += 1
            if round_num > MAX_TOOL_ROUNDS:
                final_response = text
                logger.warning(f"[{self.ws_id}] Hit max tool rounds ({MAX_TOOL_ROUNDS})")
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
    ) -> tuple[str, list[dict]]:
        """Single streaming round. Returns (text, tool_calls).

        When *suppress_tools* is True, no tool definitions are sent —
        forcing the model to produce a text-only answer (synthesis).
        """
        state = self.runner.state
        tools = None if suppress_tools else self.tools_for_api

        model_name, stream = await state.model_router.chat_stream(
            self.messages,
            system=self.system,
            force_model=self.model_name,
            tools=tools,
        )
        self.model_name = model_name

        await websocket_manager.send_to_client(
            self.ws_id, {"type": "stream_start", "model": model_name}
        )

        full_response = ""
        native_tool_calls: list[dict] = []
        buffer = ""
        last_flush = time.monotonic()

        async for chunk in stream:
            # Check abort during streaming
            if self.runner.abort.is_set():
                if buffer:
                    await websocket_manager.send_to_client(
                        self.ws_id, {"type": "stream_chunk", "content": buffer}
                    )
                await websocket_manager.send_to_client(
                    self.ws_id, {"type": "stream_end", "model": model_name}
                )
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

        await websocket_manager.send_to_client(
            self.ws_id, {"type": "stream_end", "model": model_name}
        )

        return full_response, native_tool_calls

    async def _execute_tools(
        self,
        native_tool_calls: list[dict],
        full_response: str = "",
    ) -> list[dict]:
        """Execute tool calls and return results.

        Tries native tool calls first, falls back to legacy regex parsing
        on the full response text. Returns empty list if no tools were called.
        """
        state = self.runner.state
        tool_executor = getattr(state, "tool_executor", None)
        tool_results: list[dict] = []

        # Native tool calls (Anthropic or Ollama)
        if native_tool_calls and tool_executor:
            for tc in native_tool_calls:
                tool_name = tc.get("name", "")
                tool_input = tc.get("input", {})
                tool_id = tc.get("id", "")

                # Send tool status as a non-visible event (not a system message)
                # The chat UI shows a typing indicator during streaming instead
                await websocket_manager.send_to_client(
                    self.ws_id,
                    {"type": "tool_status", "tool": tool_name, "status": "running"},
                )

                try:
                    parsed_call = tool_executor.parse_anthropic_tool_call({
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_input,
                    })
                    result = await tool_executor.execute(parsed_call)
                    if result.success:
                        tool_results.append({
                            "tool": tool_name,
                            "result": result.result,
                            "tool_use_id": tool_id,
                        })
                    else:
                        tool_results.append({
                            "tool": tool_name,
                            "error": result.error,
                            "tool_use_id": tool_id,
                        })
                except Exception as exc:
                    logger.error(f"Native tool {tool_name} failed: {exc}")
                    tool_results.append({
                        "tool": tool_name,
                        "error": str(exc),
                        "tool_use_id": tool_id,
                    })

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
