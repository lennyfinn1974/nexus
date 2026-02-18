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
    "chat": [
        # Conversational / knowledge recall — no tools needed, RAG handles it
        (r"\b(what do you know|what did you learn|tell me about|what is|who is)\b", 3),
        (r"\b(explain|describe|summarize|what'?s the difference)\b", 2),
        (r"\b(do you (know|remember)|have you (seen|heard))\b", 3),
        (r"^(test|testing|check|let'?s (test|try|check))\b", 3),
        (r"\b(how does|how do|what are|why is|why does)\b", 2),
        (r"\b(can you|could you|would you)\b.*\b(tell|explain|describe|help me understand)\b", 2),
        (r"\b(my|your) (opinion|thoughts|take)\b", 2),
        # Greetings and social / status check — never needs tools
        (r"^(hi|hello|hey|good (morning|afternoon|evening)|morning|greetings)\b", 4),
        (r"\bhow are you\b", 4),
        (r"\b(what'?s up|how'?s? it going|how do you do|how'?s everything|how is it going)\b", 4),
        (r"\b(thank you|thanks|cheers|appreciate|great job|well done|nice work)\b", 3),
        (r"\b(check.?in|checking in|just saying hi|quick hello)\b", 3),
        (r"^(yes|no|ok|okay|sure|yep|nope|agreed|exactly|right|correct)\b", 3),
        (r"^(bye|goodbye|see you|later|good night|night|gn)\b", 3),
        # Conversational continuity — referencing previous context
        (r"\b(shall we|let'?s|can we)\b.*\b(try|test|check|go|continue|revisit)\b", 3),
        (r"\bfrom (before|earlier|last time|yesterday|the other day)\b", 3),
        (r"\b(what (we|did we)|we (talked|discussed|covered|went over))\b", 3),
        (r"\b(go back to|return to|pick up where)\b", 3),
        (r"\b(those|the|that|these) (questions?|topics?|things?|items?)\b", 2),
        # Meta-questions about the agent / performance / system
        (r"\b(you seem|you('re| are) (slow|fast|different|broken|wrong))\b", 3),
        (r"\b(what('s| is| has) (changed|different|wrong|happening|going on))\b", 3),
        (r"\b(why (are|is|did) you)\b", 3),
        (r"\b(your (response|speed|performance|answer|behavior))\b", 3),
        (r"\b(are you (ok|working|broken|there|alive|listening))\b", 4),
        (r"\b(what (can|do) you do)\b", 3),
        (r"\b(how (long|fast|slow))\b.*\b(take|respond|answer)\b", 3),
        # Short conversational fragments
        (r"^(really|seriously|wow|huh|interesting|cool|nice|great|hmm|lol)\b", 3),
        (r"^(i think|i feel|i want|i need|i was|i am)\b", 2),
        (r"\b(help me|assist me|guide me)\b", 2),
    ],
    "web": [
        (r"\b(google|find online|web search|browse the web|look up online)\b", 2),
        (r"\b(search for|search the web|search online)\b", 2),
        (r"\bhttps?://", 3),
        (r"\bwww\.", 3),
        (r"\b(news|article|blog post|webpage)\b", 1),
        (r"\b(weather|forecast|temperature)\b", 4),
        (r"\b(research|find information|look up)\b", 1),
    ],
    "system": [
        (r"\bopen (safari|chrome|firefox|finder|terminal|preview|notes|mail|slack|discord|music|spotify|iterm|vscode|code)\b", 3),
        (r"\b(launch|open app|open application)\b", 2),
        (r"\b(screenshot|screen capture|take a photo of screen)\b", 2),
        (r"\b(clipboard|copy|paste)\b", 1),
        (r"\b(volume|brightness|dark mode|light mode|night mode)\b", 2),
        (r"\b(notification|notify|alert me|say text|speak)\b", 1),
        (r"\b(frontmost|running apps?|active window|window list)\b", 2),
        (r"\b(what apps?|which apps?|apps?.*(running|open|active)|(running|open|active).*apps?)\b", 3),
        (r"\b(my (mac|computer|desktop|laptop|machine))\b", 2),
        (r"\b(list.*(apps?|processes?|windows?))\b", 2),
        (r"\b(keyboard|type text|shortcut|press key|key combo)\b", 1),
        (r"\b(calendar|events?|schedule|appointment|meeting)\b", 2),
        (r"\b(reminder|reminders|remind me|to.?do)\b", 2),
        (r"\b(note|notes|apple notes)\b", 2),
        (r"\b(things|task manager)\b", 2),
        (r"\b(system info|cpu|ram|disk|uptime|os version)\b", 2),
        (r"\b(ollama|model|local model)\b", 1),
    ],
    "files": [
        (r"\b(read|write|edit|create|open|view|show|cat)\b.{0,20}\b(file|document)\b", 3),
        (r"\b(list directory|list files|ls |dir )\b", 2),
        (r"\b(search files|find file|locate file|file info)\b", 2),
        (r"\b(move file|copy file|delete file|rename file)\b", 2),
        (r"\b(what files|which files|files in)\b", 2),
        (r"\b\w+\.(py|js|ts|json|yaml|yml|md|txt|csv|html|css)\b", 1),
    ],
    "code": [
        (r"\b(run command|execute|terminal|bash|shell|command line|CLI)\b", 2),
        (r"\b(tmux|session|new session|send command)\b", 2),
        (r"\b(pip|npm|git|docker|make|cargo|brew)\b", 1),
        (r"\b(compile|build|deploy|tests?)\b", 1),
    ],
    "memory": [
        (r"\b(remember|recall|what do (i|you) know)\b", 3),
        (r"\b(what have (i|you) (told|said|stored|saved))\b", 3),
        (r"\b(store this|memorize|save this|keep in mind)\b", 2),
        (r"\b(forget|stored|memories|my preferences)\b", 1),
        (r"\b(do you know about|tell me what you know)\b", 2),
        (r"\b(where do i|what('?s| is) my|who('?s| is) my)\b", 2),
        (r"\b(my fav(ou?rite)?|my preferred)\b", 2),
        # Temporal recall that implies stored personal knowledge
        (r"\b(do you remember|you remember)\b", 3),
        (r"\b(i (told|mentioned|said|shared) (you|before|earlier|last))\b", 3),
        (r"\b(we (discussed|talked about|covered|went over))\b", 2),
        (r"\b(my (dog|cat|pet|name|address|job|work|coffee|car|phone))\b", 2),
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

# When no category matches, fall back to chat (no tools).
# Most unmatched prompts are conversational — defaulting to "web"
# caused unnecessary tool injection that confused the model.
DEFAULT_CATEGORIES = ["chat"]


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
        max_tools: int = 5,
    ) -> list[ToolDefinition]:
        """Select the most relevant tools for *message*.

        Strategy (Feb 2026 — "System Prompt Diet" / lean tool set)
        -----------------------------------------------------------
        1. If "chat" is primary intent (no web co-intent), return NO tools.
        2. If "memory" is primary (no web co-intent), return NO tools.
        3. Always include CORE_TOOL_NAMES (google_search + web_fetch).
        4. Primary category → up to 3 additional tools.
        5. Secondary categories → 1 tool each.
        6. Hard cap at *max_tools* (default 5 — optimized for Ollama).

        With max_tools=5, a typical selection looks like:
            [google_search, web_fetch, <primary_1>, <primary_2>, <secondary_1>]
        This is enough for any single-intent query while keeping the tool
        schema small enough for reliable native function calling.
        """
        # 1. Classify intent first
        categories = self.classify_intent(message)
        logger.info(f"Tool selection — intent: {categories}")

        # Chat-primary intent: no tools → Ollama uses fast streaming path
        # BUT if web is also detected (e.g. "what is the weather"), keep tools
        if categories and categories[0] == "chat" and "web" not in categories:
            logger.info("Selected 0 tools: chat intent (no tools needed)")
            return []

        # Memory-primary intent without explicit web need: no tools.
        if categories and categories[0] == "memory" and "web" not in categories:
            logger.info("Selected 0 tools: memory intent (RAG handles recall)")
            return []

        selected: dict[str, ToolDefinition] = {}

        # 2. Core essentials (web search + fetch) — skip when memory is primary
        if not (categories and categories[0] == "memory"):
            for tool_name in CORE_TOOL_NAMES:
                if tool_name in self._by_name:
                    selected[tool_name] = self._by_name[tool_name]

        # 3. Fill from matched categories — tighter budgets for lean tool set
        for i, category in enumerate(categories):
            tools_in_cat = self._by_category.get(category, [])

            if i == 0:
                # Primary category — up to 3 additional tools
                limit = min(3, max_tools - len(selected))
            else:
                # Secondary categories — 1 tool each
                limit = min(1, max_tools - len(selected))

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
