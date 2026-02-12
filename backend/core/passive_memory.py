"""Passive context learning system (Memory 2.0).

Automatically extracts and stores user preferences, project context,
and interaction patterns from conversations. Uses the existing DB tables:
- user_preferences
- project_contexts
- interaction_patterns
- knowledge_associations

This runs as a background task after each conversation turn, silently
building a rich context model without explicit user commands.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("nexus.passive_memory")

# Patterns that suggest preference statements
PREFERENCE_PATTERNS = [
    r"(?:i (?:prefer|like|love|always use|usually|want)|my (?:favorite|preferred|default))\s+(.+)",
    r"(?:please (?:always|never|don't))\s+(.+)",
    r"(?:i (?:don't like|hate|avoid|never use))\s+(.+)",
]

# Patterns that suggest project context
PROJECT_PATTERNS = [
    r"(?:working on|building|developing|creating|my project)\s+(.+)",
    r"(?:the (?:app|project|repo|codebase) (?:is|uses|runs on))\s+(.+)",
    r"(?:tech stack|framework|language|database)(?:\s+is)?\s+(.+)",
]


class PassiveMemoryExtractor:
    """Extract learnable context from conversation messages.

    Call `extract_and_store()` after each assistant response to silently
    learn from the conversation. Lightweight — designed to run inline
    without noticeably slowing down responses.
    """

    def __init__(self, db: Any):
        self.db = db

    async def extract_and_store(
        self,
        conv_id: str,
        user_message: str,
        assistant_message: str,
    ) -> dict:
        """Extract and store any learnable information from the exchange.

        Returns a summary of what was learned (for logging, not shown to user).
        """
        learned = {
            "preferences": [],
            "project_context": [],
            "patterns": [],
        }

        # Extract preferences from user messages
        preferences = self._extract_preferences(user_message)
        for pref in preferences:
            await self._store_preference(pref)
            learned["preferences"].append(pref)

        # Extract project context
        project_ctx = self._extract_project_context(user_message)
        for ctx in project_ctx:
            await self._store_project_context(ctx)
            learned["project_context"].append(ctx)

        # Track interaction patterns
        pattern = self._classify_interaction(user_message)
        if pattern:
            await self._store_interaction_pattern(conv_id, pattern)
            learned["patterns"].append(pattern)

        total = sum(len(v) for v in learned.values())
        if total > 0:
            logger.debug(f"Passive memory: learned {total} items from conv {conv_id}")

        return learned

    def _extract_preferences(self, text: str) -> list[dict]:
        """Extract user preferences from text."""
        preferences = []
        text_lower = text.lower()

        for pattern in PREFERENCE_PATTERNS:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                value = match.group(1).strip()[:200]
                if len(value) > 5:  # Skip very short matches
                    preferences.append({
                        "category": "general",
                        "key": self._normalize_key(value[:50]),
                        "value": value,
                        "source": "conversation",
                    })

        return preferences[:3]  # Cap at 3 per message

    def _extract_project_context(self, text: str) -> list[dict]:
        """Extract project-related context from text."""
        contexts = []
        text_lower = text.lower()

        for pattern in PROJECT_PATTERNS:
            matches = re.finditer(pattern, text_lower)
            for match in matches:
                value = match.group(1).strip()[:200]
                if len(value) > 5:
                    contexts.append({
                        "key": "project_detail",
                        "value": value,
                        "source": "conversation",
                    })

        return contexts[:2]

    def _classify_interaction(self, text: str) -> Optional[dict]:
        """Classify the type of interaction for pattern tracking."""
        text_lower = text.lower()

        # Classify interaction type
        if any(w in text_lower for w in ["fix", "bug", "error", "broken"]):
            return {"type": "debugging", "detail": text[:100]}
        elif any(w in text_lower for w in ["create", "build", "implement", "add"]):
            return {"type": "development", "detail": text[:100]}
        elif any(w in text_lower for w in ["search", "find", "look up", "what is"]):
            return {"type": "research", "detail": text[:100]}
        elif any(w in text_lower for w in ["explain", "how does", "why", "help me understand"]):
            return {"type": "learning", "detail": text[:100]}
        elif text.startswith("/"):
            return {"type": "command", "detail": text[:100]}

        return None

    def _normalize_key(self, text: str) -> str:
        """Normalize text into a key-friendly format."""
        return re.sub(r"[^a-z0-9_]", "_", text.lower().strip())[:50]

    async def _store_preference(self, pref: dict):
        """Store a preference in the database."""
        try:
            from sqlalchemy import text
            async with self.db._session_factory() as session:
                await session.execute(
                    text("""
                        INSERT INTO user_preferences (category, key, value, source, updated_at)
                        VALUES (:category, :key, :value, :source, NOW())
                        ON CONFLICT (key) DO UPDATE SET
                            value = :value,
                            source = :source,
                            confidence = user_preferences.confidence + 0.1,
                            updated_at = NOW()
                    """),
                    pref,
                )
                await session.commit()
        except Exception as e:
            logger.debug(f"Failed to store preference: {e}")

    async def _store_project_context(self, ctx: dict):
        """Store project context in the database."""
        try:
            from sqlalchemy import text
            async with self.db._session_factory() as session:
                await session.execute(
                    text("""
                        INSERT INTO project_contexts (key, value, source, updated_at)
                        VALUES (:key, :value, :source, NOW())
                        ON CONFLICT DO NOTHING
                    """),
                    ctx,
                )
                await session.commit()
        except Exception as e:
            logger.debug(f"Failed to store project context: {e}")

    async def _store_interaction_pattern(self, conv_id: str, pattern: dict):
        """Store interaction pattern for analytics."""
        try:
            from sqlalchemy import text
            async with self.db._session_factory() as session:
                await session.execute(
                    text("""
                        INSERT INTO interaction_patterns
                            (conversation_id, pattern_type, detail, created_at)
                        VALUES (:conv_id, :type, :detail, NOW())
                    """),
                    {"conv_id": conv_id, **pattern},
                )
                await session.commit()
        except Exception as e:
            logger.debug(f"Failed to store interaction pattern: {e}")

    async def get_context_for_prompt(self, limit: int = 10) -> str:
        """Build context string from stored memories for injection into system prompt.

        Returns a concise summary of known preferences and project context.
        """
        parts = []

        try:
            from sqlalchemy import text
            async with self.db._session_factory() as session:
                # Top preferences
                result = await session.execute(
                    text("""
                        SELECT key, value, confidence
                        FROM user_preferences
                        ORDER BY confidence DESC, updated_at DESC
                        LIMIT :limit
                    """),
                    {"limit": limit},
                )
                prefs = result.fetchall()
                if prefs:
                    pref_lines = [f"- {r[0]}: {r[1]}" for r in prefs]
                    parts.append("**User Preferences:**\n" + "\n".join(pref_lines))

                # Recent project context
                result2 = await session.execute(
                    text("""
                        SELECT key, value
                        FROM project_contexts
                        ORDER BY updated_at DESC
                        LIMIT :limit
                    """),
                    {"limit": limit},
                )
                projects = result2.fetchall()
                if projects:
                    proj_lines = [f"- {r[1]}" for r in projects]
                    parts.append("**Project Context:**\n" + "\n".join(proj_lines))

        except Exception as e:
            logger.debug(f"Failed to get context for prompt: {e}")

        return "\n\n".join(parts)
