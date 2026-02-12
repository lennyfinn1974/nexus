"""Tests for tool result truncation."""

import pytest
from core.tool_result_truncation import (
    HARD_MAX_CHARS,
    MAX_RESULT_SHARE,
    MIN_KEEP_CHARS,
    truncate_tool_result,
)


class TestTruncateToolResult:
    """Unit tests for the truncate_tool_result function."""

    def test_empty_input(self):
        assert truncate_tool_result("") == ""
        assert truncate_tool_result(None) is None

    def test_short_input_unchanged(self):
        short = "Hello, this is a short result."
        assert truncate_tool_result(short) == short

    def test_within_budget_unchanged(self):
        text = "x" * 1000
        result = truncate_tool_result(text, max_context_tokens=32_000)
        assert result == text

    def test_exceeds_budget_truncated(self):
        # Budget for 32K context, 1 result: 32000 * 4 * 0.3 / 1 = 38400 chars
        big = "a" * 50_000
        result = truncate_tool_result(big, max_context_tokens=32_000)
        assert len(result) < len(big)
        assert "[... " in result
        assert "truncated ...]" in result

    def test_truncation_marker_present(self):
        big = "\n".join([f"Line {i}: " + "x" * 80 for i in range(1000)])
        result = truncate_tool_result(big, max_context_tokens=4_000)
        assert "truncated" in result

    def test_preserves_head_and_tail(self):
        lines = [f"Line {i}: content" for i in range(500)]
        text = "\n".join(lines)
        result = truncate_tool_result(text, max_context_tokens=4_000)
        # Should contain beginning
        assert "Line 0:" in result
        # Should contain end
        assert "Line 499:" in result

    def test_multiple_results_smaller_budget(self):
        big = "y" * 50_000
        single = truncate_tool_result(big, max_context_tokens=32_000, num_results=1)
        multi = truncate_tool_result(big, max_context_tokens=32_000, num_results=3)
        # With more results, each gets less budget — so more truncation
        assert len(multi) < len(single)

    def test_min_keep_chars(self):
        big = "z" * 100_000
        result = truncate_tool_result(big, max_context_tokens=100, num_results=1)
        # Even with tiny context, we keep at least MIN_KEEP_CHARS
        assert len(result) >= MIN_KEEP_CHARS

    def test_hard_max_cap(self):
        huge = "w" * 500_000
        result = truncate_tool_result(huge, max_context_tokens=1_000_000)
        # Budget would be huge, but HARD_MAX_CHARS caps it
        assert len(result) <= HARD_MAX_CHARS + 200  # margin for truncation marker

    def test_newline_boundary_preference(self):
        lines = ["Line A: " + "a" * 100, "Line B: " + "b" * 100, "Line C: " + "c" * 100]
        text = "\n".join(lines * 200)
        result = truncate_tool_result(text, max_context_tokens=2_000)
        # Truncation should happen at newline boundaries where possible
        head_part = result.split("[...")[0]
        # Head should contain at least one newline (proves it splits at line boundaries)
        assert "\n" in head_part.strip()

    def test_ollama_context_realistic(self):
        """Simulate realistic Ollama 32K context with multiple results."""
        result_text = "def hello():\n    " + "print('hello')\n    " * 500
        truncated = truncate_tool_result(result_text, max_context_tokens=32_000, num_results=2)
        # Should be within budget: 32K * 4 * 0.3 / 2 = 19200 chars
        assert len(truncated) <= 20_000

    def test_claude_context_larger_budget(self):
        """Claude gets 200K context, so more result fits."""
        result_text = "data: " + "x" * 200_000
        truncated = truncate_tool_result(result_text, max_context_tokens=200_000, num_results=1)
        # Budget: 200K * 4 * 0.3 = 240K but capped at HARD_MAX_CHARS
        assert len(truncated) <= HARD_MAX_CHARS + 200
