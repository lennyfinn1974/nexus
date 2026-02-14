"""Intelligent tool selection for Ollama-based routing.

When Ollama handles a request with tools, sending all 52 tools leads to
scattered, unfocused tool calls.  This module classifies user intent via
lightweight regex matching and returns only the 10–15 most relevant tool
definitions — dramatically improving tool-call quality for local models.

Claude receives the full tool set (it handles large tool arrays well).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from schemas.tools import ToolDefinition

logger = logging.getLogger("nexus.tools.selector")

# ── Intent Patterns ─────────────────────────────────────────────────
# Each category maps to a list of (pattern, weight) tuples.
# A message may match multiple categories; they are ranked by total weight.

CATEGORY_PATTERNS: dict[str, list[tuple[str, int]]] = {
    "web": [
        (r"\b(google|find online|web search|browse the web|look up online)\b", 2),
        (r"\b(search for|search the web|search online)\b", 2),
        (r"\bhttps?://", 3),
        (r"\bwww\.", 3),
        (r"\b(news|article|blog post|webpage)\b", 1),
        (r"\b(weather|forecast|temperature)\b", 2),
        (r"\b(research|find information|look up)\b", 1),
    ],
    "system": [
        (r"\bopen (safari|chrome|firefox|finder|terminal|preview|notes|mail|slack|discord|music|spotify|iterm|vscode|code)\b", 3),
        (r"\b(launch|open app|open application)\b", 2),
        (r"\b(screenshot|screen capture|take a photo of screen)\b", 2),
        (r"\b(clipboard|copy|paste)\b", 1),
        (r"\b(volume|brightness|dark mode|light mode|night mode)\b", 2),
        (r"\b(notification|notify|alert me|say text|speak)\b", 1),
        (r"\b(frontmost|running apps|active window|window list)\b", 1),
        (r"\b(keyboard|type text|shortcut|press key|key combo)\b", 1),
        (r"\b(calendar|events?|schedule|appointment|meeting)\b", 2),
        (r"\b(reminder|reminders|remind me|to.?do)\b", 2),
        (r"\b(note|notes|apple notes)\b", 2),
        (r"\b(things|task manager)\b", 2),
        (r"\b(system info|cpu|ram|disk|uptime|os version)\b", 2),
        (r"\b(ollama|model|local model)\b", 1),
    ],
    "files": [
        (r"\b(read file|write file|edit file|create file)\b", 3),
        (r"\b(list directory|list files|ls |dir )\b", 2),
        (r"\b(search files|find file|locate file|file info)\b", 2),
        (r"\b(move file|copy file|delete file|rename file)\b", 2),
        (r"\b\w+\.(py|js|ts|json|yaml|yml|md|txt|csv|html|css)\b", 1),
    ],
    "code": [
        (r"\b(run command|execute|terminal|bash|shell|command line|CLI)\b", 2),
        (r"\b(tmux|session|new session|send command)\b", 2),
        (r"\b(pip|npm|git|docker|make|cargo|brew)\b", 1),
        (r"\b(compile|build|deploy|test)\b", 1),
    ],
    "memory": [
        (r"\b(remember|recall|what do (i|you) know)\b", 3),
        (r"\b(what have (i|you) (told|said|stored|saved))\b", 3),
        (r"\b(store this|memorize|save this|keep in mind)\b", 2),
        (r"\b(forget|stored|memories|my preferences)\b", 1),
        (r"\b(do you know about|tell me what you know)\b", 2),
    ],
    "knowledge": [
        (r"\b(document|knowledge base|indexed docs|search docs)\b", 2),
        (r"\b(qmd|documentation|readme|manual|guide)\b", 2),
        (r"\b(ingest|learn from|read the docs)\b", 1),
    ],
    "workspace": [
        (r"\b(sovereign|workspace)\b", 3),
        (r"\b(project status|project overview)\b", 2),
        (r"\b(BLD:|ANZ:|SYS:)\b", 2),
    ],
    "skills": [
        (r"\b(install skill|skill catalog|browse skills|available skills)\b", 3),
        (r"\b(antigravity|skill pack|upgrade capabilities)\b", 2),
        (r"\b(self.improve|new capability|learn how to)\b", 1),
        (r"\b(search.*skills?|find.*skills?|what skills)\b", 2),
        (r"\b(run action|execute action|call action|skill action|list actions)\b", 3),
        (r"\b(use the .+ skill|invoke skill|load skill)\b", 2),
        (r"@[\w-]+", 3),  # @skill-name syntax
    ],
}

# Tools that are ALWAYS included regardless of intent — covers the
# most universally useful actions.  NOTE: terminal_execute is intentionally
# NOT here — it's too "attractive" to the model and gets called even when
# it's not appropriate.  It's included only for "code" intent.
# NOTE: mem0 tools removed from core — passive memory handles automatic
# recall now. Mem0 tools are still available via the "memory" category
# when the user explicitly mentions remember/recall/forget.
CORE_TOOL_NAMES: list[str] = [
    "brave__google_search",
    "brave__web_fetch",
]

# When no category matches, fall back to these categories.
DEFAULT_CATEGORIES = ["web"]


class ToolSelector:
    """Select a subset of tools relevant to the user's message intent."""

    def __init__(self, all_definitions: list[ToolDefinition]) -> None:
        self.all_definitions = all_definitions
        self._by_category: dict[str, list[ToolDefinition]] = {}
        self._by_name: dict[str, ToolDefinition] = {}
        self._build_maps()

    # ── Internal ────────────────────────────────────────────────────

    def _build_maps(self) -> None:
        for defn in self.all_definitions:
            cat = defn.category
            self._by_category.setdefault(cat, []).append(defn)
            full_name = f"{defn.plugin}__{defn.name}"
            self._by_name[full_name] = defn

    # ── Public API ──────────────────────────────────────────────────

    def classify_intent(self, message: str) -> list[str]:
        """Return ranked list of matching categories (highest score first)."""
        msg_lower = message.lower()
        scores: dict[str, int] = {}

        for category, patterns in CATEGORY_PATTERNS.items():
            total = 0
            for pattern, weight in patterns:
                if re.search(pattern, msg_lower):
                    total += weight
            if total > 0:
                scores[category] = total

        if not scores:
            return list(DEFAULT_CATEGORIES)

        return sorted(scores.keys(), key=lambda c: scores[c], reverse=True)

    def select_tools(
        self,
        message: str,
        max_tools: int = 15,
    ) -> list[ToolDefinition]:
        """Select the most relevant tools for *message*.

        Strategy
        --------
        1. Always include CORE_TOOL_NAMES (5 tools).
        2. Primary category → all its tools (up to 10).
        3. Secondary categories → top 3 tools each.
        4. Cap at *max_tools*.
        """
        selected: dict[str, ToolDefinition] = {}

        # 1. Core essentials
        for tool_name in CORE_TOOL_NAMES:
            if tool_name in self._by_name:
                selected[tool_name] = self._by_name[tool_name]

        # 2. Classify intent
        categories = self.classify_intent(message)
        logger.info(f"Tool selection — intent: {categories}")

        # 3. Fill from matched categories
        for i, category in enumerate(categories):
            tools_in_cat = self._by_category.get(category, [])

            if i == 0:
                # Primary category — include everything (up to remaining budget)
                limit = min(10, max_tools - len(selected))
            else:
                # Secondary categories — include top 3
                limit = min(3, max_tools - len(selected))

            for tool in tools_in_cat[:limit]:
                full_name = f"{tool.plugin}__{tool.name}"
                if full_name not in selected:
                    selected[full_name] = tool

                if len(selected) >= max_tools:
                    break

            if len(selected) >= max_tools:
                break

        result = list(selected.values())
        tool_names = [d.name for d in result]
        logger.info(f"Selected {len(result)} tools: {tool_names}")
        return result
