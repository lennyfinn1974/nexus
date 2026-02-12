"""Conversation context builder.

Assembles the messages list sent to the model, including:
- A rolling summary of older conversation (if available)
- The N most recent messages
- Proper chronological ordering

Replaces the inline 3-line pattern previously duplicated in ws.py
and message_processor.py.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("nexus.context")

# Number of recent messages to keep in the context window
RECENT_WINDOW = 20
# Threshold: when message count exceeds this, generate a summary
SUMMARY_THRESHOLD = 30
# How many new messages beyond the last summary before we regenerate
SUMMARY_REFRESH_GAP = 20

# Context window limits by model type (in tokens).
# Ollama's 32K makes truncation and guards critical for local-first operation.
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude": 200_000,
    "claude_code": 200_000,
    "ollama": 32_000,
}


# ── Token Estimation ────────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    if not text:
        return 0
    return len(text) // 4 + 1


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Sum token estimates across all messages.

    Handles both plain string content and Anthropic's list-of-blocks format.
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            # Anthropic format: list of content blocks
            for block in content:
                if isinstance(block, dict):
                    total += estimate_tokens(
                        block.get("text", block.get("content", ""))
                    )
                elif isinstance(block, str):
                    total += estimate_tokens(block)
        elif isinstance(content, str):
            total += estimate_tokens(content)
        # Add small overhead per message for role/metadata
        total += 4
    return total


def check_context_fits(
    messages: list[dict],
    system: str,
    model: str,
) -> bool:
    """Return True if messages + system prompt fit within the model's context.

    Leaves 20% headroom for the model's response.
    """
    total = estimate_tokens(system) + estimate_messages_tokens(messages)
    limit = MODEL_CONTEXT_LIMITS.get(model, 32_000)
    fits = total < limit * 0.8
    if not fits:
        logger.warning(
            f"Context check: {total:,} tokens exceeds 80% of {model}'s "
            f"{limit:,} token limit"
        )
    return fits


def get_context_limit(model: str) -> int:
    """Return the context window size in tokens for a model."""
    return MODEL_CONTEXT_LIMITS.get(model, 32_000)


async def build_conversation_context(
    db: Any,
    conv_id: str,
    new_user_message: str,
    model_router: Any = None,
    system_prompt: str = "",
) -> list[dict]:
    """Build the messages list for the AI model.

    Returns a list of message dicts ready to send to the model.
    If the conversation is long enough, prepends a summary of older
    messages as the first user/assistant exchange.
    """
    total_count = await db.get_message_count(conv_id)
    history = await db.get_conversation_messages(conv_id, limit=RECENT_WINDOW)
    messages: list[dict] = []

    # If conversation is long, try to prepend a summary
    if total_count > RECENT_WINDOW:
        summary = await db.get_conversation_summary(conv_id)
        if summary:
            messages.append({
                "role": "user",
                "content": "[Conversation summary of earlier messages — use as background context]",
            })
            messages.append({
                "role": "assistant",
                "content": summary,
            })

        # Check if we should generate/refresh the summary in the background
        if model_router:
            asyncio.create_task(
                _maybe_refresh_summary(db, conv_id, total_count, model_router)
            )

    # Append the recent message history
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    # Append the new user message (if not already in history from DB)
    if new_user_message:
        messages.append({"role": "user", "content": new_user_message})

    return messages


async def _maybe_refresh_summary(
    db: Any,
    conv_id: str,
    total_count: int,
    model_router: Any,
) -> None:
    """Generate or refresh a conversation summary if needed.

    A summary is generated when:
    - Total messages >= SUMMARY_THRESHOLD (30) AND no summary exists
    - OR the gap between total messages and messages_covered exceeds SUMMARY_REFRESH_GAP

    Runs as a background task — does NOT block the current response.
    """
    try:
        if total_count < SUMMARY_THRESHOLD:
            return

        detail = await db.get_conversation_summary_detail(conv_id)

        needs_refresh = False
        if detail is None:
            # No summary at all — generate one
            needs_refresh = True
        else:
            # Check if enough new messages have accumulated beyond the last summary
            covered = detail.get("messages_covered", 0)
            gap = total_count - covered - RECENT_WINDOW
            if gap >= SUMMARY_REFRESH_GAP:
                needs_refresh = True

        if needs_refresh:
            await _generate_summary(db, conv_id, total_count, model_router)

    except Exception as e:
        logger.warning(f"Summary refresh check failed for {conv_id}: {e}")


async def _generate_summary(
    db: Any,
    conv_id: str,
    total_count: int,
    model_router: Any,
) -> None:
    """Generate a conversation summary from older messages."""
    try:
        # Calculate how many older messages to summarise
        # (everything except the most recent RECENT_WINDOW)
        older_count = total_count - RECENT_WINDOW
        if older_count <= 5:
            return  # Not enough older messages to warrant a summary

        # Get ALL messages to extract the older portion
        all_messages = await db.get_conversation_messages(conv_id, limit=total_count)
        older_messages = all_messages[:older_count]

        if not older_messages:
            return

        # Build a concise conversation text (truncate individual messages to save tokens)
        conversation_parts = []
        for m in older_messages:
            content = m["content"]
            if len(content) > 500:
                content = content[:500] + "..."
            role_label = "USER" if m["role"] == "user" else "ASSISTANT"
            conversation_parts.append(f"{role_label}: {content}")

        conversation_text = "\n".join(conversation_parts)

        # Truncate total conversation text if extremely long
        if len(conversation_text) > 8000:
            conversation_text = conversation_text[:8000] + "\n...(truncated)"

        summary_prompt = (
            "Summarise the following conversation history concisely. "
            "Capture the key topics discussed, any decisions made, important facts mentioned, "
            "and the current state of each topic. Use bullet points. "
            "Keep it under 300 words.\n\n"
            f"CONVERSATION:\n{conversation_text}"
        )

        result = await model_router.chat(
            messages=[{"role": "user", "content": summary_prompt}],
            system="You are a precise summariser. Extract key facts, topics, and decisions only. Be concise.",
            force_model=None,  # Use default routing (cheapest available)
        )

        summary_text = result.get("content", "")
        if summary_text and len(summary_text) > 20:
            await db.save_conversation_summary(conv_id, summary_text, older_count)
            logger.info(f"Generated summary for {conv_id} covering {older_count} messages ({len(summary_text)} chars)")
        else:
            logger.warning(f"Summary generation returned empty result for {conv_id}")

    except Exception as e:
        logger.warning(f"Failed to generate conversation summary for {conv_id}: {e}")
