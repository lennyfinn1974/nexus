"""Provider-specific message formatting for tool call follow-up rounds.

Extracts the three-way branching (Anthropic / Ollama / legacy) that was
previously inline in ws.py, so AgentAttempt can format messages without
knowing provider details.
"""

from __future__ import annotations

import json
from typing import Any


class MessageFormatter:
    """Format tool call follow-up messages for different providers."""

    @staticmethod
    def format_anthropic(
        text: str,
        tool_calls: list[dict],
        tool_results: list[dict],
    ) -> list[dict]:
        """Build Anthropic-format follow-up messages.

        Returns a list of messages to append:
        1. Assistant message with text + tool_use content blocks
        2. User message with tool_result content blocks
        """
        # Assistant content: text (if any) + tool_use blocks
        assistant_content: list[dict] = []
        if text:
            assistant_content.append({"type": "text", "text": text})
        for tc in tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": tc.get("id", ""),
                "name": tc.get("name", ""),
                "input": tc.get("input", {}),
            })

        # Tool results
        tool_result_content: list[dict] = []
        for tr in tool_results:
            tool_result_content.append({
                "type": "tool_result",
                "tool_use_id": tr.get("tool_use_id", ""),
                "content": tr.get("result", tr.get("error", "No result")),
            })

        return [
            {"role": "assistant", "content": assistant_content},
            {"role": "user", "content": tool_result_content},
        ]

    @staticmethod
    def format_ollama(
        text: str,
        tool_calls: list[dict],
        tool_results: list[dict],
    ) -> list[dict]:
        """Build Ollama/OpenAI-format follow-up messages.

        /v1/chat/completions requires:
        - arguments as JSON *string* (not dict)
        - id and type:"function" on each tool_call
        - tool_call_id on each tool-role message
        """
        # Assistant message with tool_calls array
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": text or ""}
        tool_calls_for_msg = []
        for tc in tool_calls:
            args = tc.get("input", {})
            tool_calls_for_msg.append({
                "id": tc.get("id", f"ollama_{id(tc)}"),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                },
            })
        if tool_calls_for_msg:
            assistant_msg["tool_calls"] = tool_calls_for_msg

        messages = [assistant_msg]

        # Tool result messages
        for i, tr in enumerate(tool_results):
            result_content = tr.get("result", tr.get("error", "No result"))
            tool_call_id = tr.get("tool_use_id", "")
            if not tool_call_id and i < len(tool_calls):
                tool_call_id = tool_calls[i].get("id", f"ollama_{i}")
            messages.append({
                "role": "tool",
                "content": str(result_content),
                "tool_call_id": tool_call_id,
            })

        return messages

    @staticmethod
    def format_legacy(
        text: str,
        tool_results: list[dict],
        round_num: int,
    ) -> list[dict]:
        """Build legacy text-based follow-up messages.

        Used when neither Anthropic nor Ollama native tool calling is active.
        """
        tool_feedback_parts = []
        for tr in tool_results:
            name = tr.get("tool", "unknown")
            if "result" in tr:
                tool_feedback_parts.append(f"**{name}** returned:\n{tr['result']}")
            else:
                tool_feedback_parts.append(f"**{name}** error: {tr.get('error', 'unknown')}")
        tool_feedback = "\n\n".join(tool_feedback_parts)

        return [
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": (
                    f"[Tool Results -- Round {round_num}]\n\n"
                    f"{tool_feedback}\n\n"
                    f"Use these results to continue. If you need more tools, "
                    f"call them. Otherwise give your final answer."
                ),
            },
        ]
