"""Tests for the model routing logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestComplexityEstimation:
    """Test the complexity scoring algorithm."""

    def test_simple_greeting(self, mock_model_router):
        score = mock_model_router.estimate_complexity("hi")
        assert score < 50

    def test_complex_code_request(self, mock_model_router):
        msg = "Can you analyze this code and refactor the authentication module step by step?"
        score = mock_model_router.estimate_complexity(msg)
        assert score > 60

    def test_short_question(self, mock_model_router):
        score = mock_model_router.estimate_complexity("What is Python?")
        assert score < 60

    def test_long_multi_question(self, mock_model_router):
        msg = (
            "Can you explain the trade-offs between microservices and monolithic architecture? "
            "What are the pros and cons of each? How do you decide which one to use? "
            "Can you provide examples of when each approach is better?"
        )
        score = mock_model_router.estimate_complexity(msg)
        assert score > 60

    def test_code_block_detection(self, mock_model_router):
        msg = "Fix this:\n```python\ndef broken():\n    pass\n```"
        score = mock_model_router.estimate_complexity(msg)
        # Code blocks (+8) but short message (-10), so score stays near baseline
        assert score > 40

    def test_score_bounds(self, mock_model_router):
        # Should never exceed 0-100 range
        assert 0 <= mock_model_router.estimate_complexity("") <= 100
        assert 0 <= mock_model_router.estimate_complexity("a" * 10000) <= 100


class TestModelSelection:
    def test_select_claude_for_complex(self, mock_model_router):
        model = mock_model_router.select_model(
            "Analyze the architectural trade-offs of this distributed system and refactor the code"
        )
        assert model == "claude"

    def test_select_ollama_for_simple(self, mock_model_router):
        model = mock_model_router.select_model("hello")
        assert model == "ollama"

    def test_force_claude(self, mock_model_router):
        model = mock_model_router.select_model("hi", force_model="claude")
        assert model == "claude"

    def test_force_ollama(self, mock_model_router):
        model = mock_model_router.select_model("analyze everything", force_model="ollama")
        assert model == "ollama"

    def test_fallback_when_forced_unavailable(self, mock_model_router):
        mock_model_router._claude_available = False
        # Force claude but it's unavailable - should fall through to auto
        model = mock_model_router.select_model("hello", force_model="claude")
        assert model == "ollama"

    def test_no_models_available_raises(self, mock_model_router):
        mock_model_router._ollama_available = False
        mock_model_router._claude_available = False
        with pytest.raises(RuntimeError, match="No models"):
            mock_model_router.select_model("hello")


class TestModelChat:
    async def test_chat_routes_correctly(self, mock_model_router):
        result = await mock_model_router.chat(
            [{"role": "user", "content": "hello"}],
            system="You are helpful.",
        )
        assert "content" in result

    async def test_chat_with_force_model(self, mock_model_router):
        result = await mock_model_router.chat(
            [{"role": "user", "content": "hello"}],
            force_model="claude",
        )
        assert "content" in result

    async def test_chat_fallback_on_failure(self, mock_model_router):
        """When primary model fails, should try the fallback."""
        mock_model_router.ollama.chat = AsyncMock(side_effect=Exception("Ollama down"))
        result = await mock_model_router.chat(
            [{"role": "user", "content": "hello"}],
        )
        # Should have fallen back to Claude
        assert "content" in result

    async def test_chat_stream_returns_tuple(self, mock_model_router):
        model_name, stream = await mock_model_router.chat_stream(
            [{"role": "user", "content": "hello"}],
        )
        assert model_name in ("ollama", "claude", "test-model")
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)
        assert len(chunks) > 0


class TestRouterStatus:
    def test_status_property(self, mock_model_router):
        status = mock_model_router.status
        assert "ollama_available" in status
        assert "claude_available" in status
        assert "complexity_threshold" in status
        assert status["ollama_available"] is True
        assert status["claude_available"] is True
