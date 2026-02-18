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
import time
from typing import Any, Optional

logger = logging.getLogger("nexus.context")

# Number of recent messages to keep in the context window.
# Model-aware: Ollama gets fewer (saves ~600 tokens per turn, ~3s TTFT).
# Claude's 200K context can handle the full window without performance impact.
RECENT_WINDOW_OLLAMA = 8   # ~800 tokens (4 exchanges)
RECENT_WINDOW_CLAUDE = 20  # ~2000 tokens (10 exchanges)
RECENT_WINDOW = 20  # Default (backward compat for callers that don't specify model)
# Threshold: when message count exceeds this, generate a summary
SUMMARY_THRESHOLD = 30
# How many new messages beyond the last summary before we regenerate
SUMMARY_REFRESH_GAP = 20

# Backoff: don't retry summary generation for this many seconds after a failure
_SUMMARY_BACKOFF_SECONDS = 300  # 5 minutes
_summary_fail_timestamps: dict[str, float] = {}  # conv_id → last failure time

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


# ── Message Trimming (Ollama) ─────────────────────────────────────────
# Long assistant messages in history are the biggest token drain.
# A single assistant response can be 2000+ chars (~500 tokens).
# For Ollama's 32K context, we trim each message to keep total history lean.

# Max chars per message in history (Ollama only)
_MSG_MAX_CHARS_USER_OLLAMA = 400    # User messages are usually short anyway
_MSG_MAX_CHARS_ASSIST_OLLAMA = 600  # Trim long assistant responses aggressively


def _trim_messages_for_ollama(messages: list[dict]) -> list[dict]:
    """Trim individual message content for Ollama's tight context budget.

    Truncates long messages while preserving the start and end of content
    (head + tail split) so the model sees both the topic and the conclusion.
    The last user message is never trimmed (it's the current query).
    """
    if not messages:
        return messages

    trimmed = []
    for i, msg in enumerate(messages):
        content = msg.get("content", "")
        role = msg.get("role", "user")

        # Never trim the last message (current user query)
        if i == len(messages) - 1:
            trimmed.append(msg)
            continue

        # Never trim system messages (summaries, context injection)
        if role == "system":
            trimmed.append(msg)
            continue

        max_chars = (
            _MSG_MAX_CHARS_USER_OLLAMA if role == "user"
            else _MSG_MAX_CHARS_ASSIST_OLLAMA
        )

        if isinstance(content, str) and len(content) > max_chars:
            # Head/tail split: keep 70% head + 30% tail with ellipsis
            head_len = int(max_chars * 0.7)
            tail_len = max_chars - head_len - 5  # 5 for "\n...\n"
            trimmed_content = content[:head_len] + "\n...\n" + content[-tail_len:]
            trimmed.append({"role": role, "content": trimmed_content})
        else:
            trimmed.append(msg)

    return trimmed


async def build_conversation_context(
    db: Any,
    conv_id: str,
    new_user_message: str,
    model_router: Any = None,
    system_prompt: str = "",
    model: str = "",
) -> list[dict]:
    """Build the messages list for the AI model.

    Returns a list of message dicts ready to send to the model.
    If the conversation is long enough, prepends a summary of older
    messages as the first user/assistant exchange.

    The ``model`` parameter controls the history window size:
    Ollama (local) gets 8 messages to minimize prompt tokens and TTFT.
    Claude/Claude Code get 20 messages (200K context handles it fine).
    """
    # Model-aware history window
    if model == "ollama":
        window = RECENT_WINDOW_OLLAMA
    elif model in ("claude", "claude_code"):
        window = RECENT_WINDOW_CLAUDE
    else:
        window = RECENT_WINDOW

    total_count = await db.get_message_count(conv_id)
    history = await db.get_conversation_messages(conv_id, limit=window)
    messages: list[dict] = []

    # If conversation is long, try to prepend a summary
    if total_count > window:
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

    # Trim long messages for Ollama to keep total tokens lean.
    # This is the last step so it applies to all messages including summary.
    if model == "ollama":
        before_tokens = estimate_messages_tokens(messages)
        messages = _trim_messages_for_ollama(messages)
        after_tokens = estimate_messages_tokens(messages)
        if before_tokens != after_tokens:
            logger.info(
                f"Ollama message trimming: {before_tokens}→{after_tokens} tokens "
                f"(saved {before_tokens - after_tokens})"
            )

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
    - AND no recent failure (5-minute backoff to avoid spamming Ollama)

    Runs as a background task — does NOT block the current response.
    """
    try:
        if total_count < SUMMARY_THRESHOLD:
            return

        # Backoff: if summary generation failed recently, don't retry yet.
        # Without this, every message triggers a 30s Ollama call that times out
        # and blocks the inference slot for real user queries.
        last_fail = _summary_fail_timestamps.get(conv_id, 0)
        if time.time() - last_fail < _SUMMARY_BACKOFF_SECONDS:
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
            # Wait for the current user query to finish before using Ollama
            # for summarization. Without this delay, the summary request competes
            # with the user's chat inference on the same Ollama instance.
            await asyncio.sleep(30)
            # Re-check backoff in case another task already ran during the wait
            if time.time() - _summary_fail_timestamps.get(conv_id, 0) < _SUMMARY_BACKOFF_SECONDS:
                return
            await _generate_summary(db, conv_id, total_count, model_router)

    except Exception as e:
        logger.warning(f"Summary refresh check failed for {conv_id}: {e}")


async def _generate_summary(
    db: Any,
    conv_id: str,
    total_count: int,
    model_router: Any,
) -> None:
    """Generate a conversation summary from older messages.

    Uses a tight context budget (3K chars) and short timeout (10s) to avoid
    blocking Ollama's inference slot. If this fails, backoff prevents retries
    for 5 minutes so real user queries aren't competing with failed summaries.
    """
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

        # Build a concise conversation text — keep TIGHT for Ollama's 32K context
        # and to avoid slow inference. Take user messages only (they define topics)
        # and truncate aggressively.
        conversation_parts = []
        for m in older_messages:
            content = m["content"]
            if m["role"] == "user":
                if len(content) > 200:
                    content = content[:200] + "..."
                conversation_parts.append(f"USER: {content}")
            else:
                # For assistant, just take first sentence/line as topic indicator
                first_line = content.split("\n")[0][:150]
                conversation_parts.append(f"ASSISTANT: {first_line}")

        conversation_text = "\n".join(conversation_parts)

        # Hard cap at 3K chars — Ollama needs to handle this fast
        if len(conversation_text) > 3000:
            conversation_text = conversation_text[:3000] + "\n...(truncated)"

        summary_prompt = (
            "Summarise this conversation concisely. Key topics, decisions, and facts only. "
            "Bullet points. Under 200 words.\n\n"
            f"{conversation_text}"
        )

        result = await model_router.chat(
            messages=[{"role": "user", "content": summary_prompt}],
            system="You are a precise summariser. Be very concise.",
            force_model="ollama",
            timeout=10,  # Short timeout — don't block Ollama for long
        )

        summary_text = result.get("content", "")
        if summary_text and len(summary_text) > 20:
            await db.save_conversation_summary(conv_id, summary_text, older_count)
            # Clear any failure backoff on success
            _summary_fail_timestamps.pop(conv_id, None)
            logger.info(f"Generated summary for {conv_id} covering {older_count} messages ({len(summary_text)} chars)")
        else:
            _summary_fail_timestamps[conv_id] = time.time()
            logger.warning(f"Summary generation returned empty result for {conv_id}")

    except Exception as e:
        _summary_fail_timestamps[conv_id] = time.time()
        logger.warning(f"Failed to generate conversation summary for {conv_id}: {e}")
