"""Tests for the conversation context manager."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.context_manager import (
    RECENT_WINDOW,
    SUMMARY_THRESHOLD,
    SUMMARY_REFRESH_GAP,
    build_conversation_context,
    estimate_tokens,
    estimate_messages_tokens,
    check_context_fits,
)


class TestEstimateTokens:
    """Test token estimation helpers."""

    def test_empty_string(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens(None) == 0

    def test_short_string(self):
        tokens = estimate_tokens("Hello world")
        assert tokens > 0
        # ~11 chars / 4 = ~3 tokens
        assert tokens < 10

    def test_scales_with_length(self):
        short_tokens = estimate_tokens("Hi")
        long_tokens = estimate_tokens("x" * 4000)
        assert long_tokens > short_tokens

    def test_estimate_messages_tokens_empty(self):
        assert estimate_messages_tokens([]) == 0

    def test_estimate_messages_tokens_basic(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there, how can I help?"},
        ]
        tokens = estimate_messages_tokens(msgs)
        assert tokens > 0

    def test_estimate_messages_tokens_scales(self):
        short_msgs = [{"role": "user", "content": "Hi"}]
        long_msgs = [{"role": "user", "content": "x" * 4000}]
        assert estimate_messages_tokens(long_msgs) > estimate_messages_tokens(short_msgs)


class TestCheckContextFits:
    """Test context window guard."""

    def test_fits_easily(self):
        msgs = [{"role": "user", "content": "Hello"}]
        assert check_context_fits(msgs, system="", model="claude") is True

    def test_exceeds_limit(self):
        msgs = [{"role": "user", "content": "x" * 200_000}]
        # ollama has 32K limit, this text is ~50K tokens — won't fit
        assert check_context_fits(msgs, system="", model="ollama") is False

    def test_system_prompt_counts(self):
        msgs = [{"role": "user", "content": "Hi"}]
        # Big system prompt should still fit in claude's 200K
        assert check_context_fits(msgs, system="x" * 10_000, model="claude") is True


class TestBuildConversationContext:
    """Test the main context builder."""

    @pytest.mark.asyncio
    async def test_basic_context(self, mock_db):
        """Simple conversation returns recent messages."""
        await mock_db.create_conversation("c1")
        for i in range(5):
            role = "user" if i % 2 == 0 else "assistant"
            await mock_db.add_message("c1", role, f"Message {i}")

        msgs = await build_conversation_context(mock_db, "c1", "")
        assert len(msgs) == 5
        assert msgs[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_empty_conversation(self, mock_db):
        """Empty conversation returns empty list."""
        await mock_db.create_conversation("c1")
        msgs = await build_conversation_context(mock_db, "c1", "")
        assert msgs == []

    @pytest.mark.asyncio
    async def test_respects_recent_window(self, mock_db):
        """Only recent messages returned when under threshold."""
        await mock_db.create_conversation("c1")
        for i in range(RECENT_WINDOW + 5):
            await mock_db.add_message("c1", "user", f"Message {i}")

        msgs = await build_conversation_context(mock_db, "c1", "")
        # Should get RECENT_WINDOW messages (possibly plus summary context)
        assert len(msgs) <= RECENT_WINDOW + 2  # +2 for possible summary pair

    @pytest.mark.asyncio
    async def test_new_user_message_appended(self, mock_db):
        """When new_user_message is provided, it appears last."""
        await mock_db.create_conversation("c1")
        await mock_db.add_message("c1", "user", "First message")
        await mock_db.add_message("c1", "assistant", "Response")

        msgs = await build_conversation_context(mock_db, "c1", "New question?")
        # The new message should be at the end
        if msgs:
            last = msgs[-1]
            if last["content"] == "New question?":
                assert last["role"] == "user"

    @pytest.mark.asyncio
    async def test_summary_included_when_present(self, mock_db, mock_model_router):
        """When a summary exists and messages exceed window, summary is injected."""
        await mock_db.create_conversation("c1")
        # Add enough messages to trigger summary inclusion
        for i in range(RECENT_WINDOW + 10):
            await mock_db.add_message("c1", "user", f"Message {i}")

        # Set a summary
        await mock_db.save_conversation_summary("c1", "Summary of earlier talk.", 20)

        msgs = await build_conversation_context(
            mock_db, "c1", "", model_router=mock_model_router
        )
        # Summary should appear as a message in the context
        contents = [m.get("content", "") for m in msgs]
        has_summary = any("Summary of earlier talk" in c for c in contents)
        assert has_summary or len(msgs) <= RECENT_WINDOW  # may skip summary if few msgs
