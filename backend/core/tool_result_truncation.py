"""Tool result truncation — prevents oversized results from blowing context.

Modelled on OpenClaw's tool-result-truncation.ts. Critical for local-first
operation where Ollama has only 32K context vs Claude's 200K.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("nexus.truncation")

# Max fraction of context window a single tool result can consume
MAX_RESULT_SHARE = 0.3

# Absolute cap regardless of context window size
HARD_MAX_CHARS = 100_000

# Always keep at least this much of the result
MIN_KEEP_CHARS = 2_000


def truncate_tool_result(
    result: str,
    max_context_tokens: int = 32_000,
    num_results: int = 1,
) -> str:
    """Truncate a tool result to fit within context budget.

    Keeps head + tail with a clear truncation marker, splitting at
    newline boundaries where possible to preserve code structure.

    Parameters
    ----------
    result : str
        The raw tool result text.
    max_context_tokens : int
        The model's total context window in tokens.
    num_results : int
        Number of tool results in this round (budget is shared).
    """
    if not result:
        return result

    # Calculate character budget: tokens * ~4 chars/token * share / num_results
    budget_chars = int(max_context_tokens * 4 * MAX_RESULT_SHARE / max(num_results, 1))
    budget_chars = max(MIN_KEEP_CHARS, min(budget_chars, HARD_MAX_CHARS))

    if len(result) <= budget_chars:
        return result

    # Split into head + tail, preferring newline boundaries
    half = budget_chars // 2

    # Find a newline near the head boundary
    head_end = result.rfind("\n", 0, half)
    if head_end < half // 2:
        # No good newline found — use raw character boundary
        head_end = half

    # Find a newline near the tail boundary
    tail_start = result.find("\n", len(result) - half)
    if tail_start < 0 or tail_start > len(result) - half // 2:
        tail_start = len(result) - half

    omitted = tail_start - head_end
    logger.info(
        f"Truncated tool result: {len(result):,} chars -> "
        f"{head_end + (len(result) - tail_start):,} chars "
        f"({omitted:,} chars omitted)"
    )

    return (
        result[:head_end]
        + f"\n\n[... {omitted:,} characters truncated ...]\n\n"
        + result[tail_start:]
    )
