"""Memory Bulletin — periodic LLM-curated knowledge digest.

Spacebot-inspired: The "Cortex" process periodically curates a knowledge
bulletin from the memory system and injects it into system prompts. This
gives the agent persistent self-awareness of what it knows without RAG
retrieval latency on every turn.

The bulletin is regenerated on a schedule (default: every 30 minutes) and
cached in-memory. It's a concise markdown summary of:
    - Key entities the user has mentioned (people, projects, tools)
    - Active project context
    - User preferences and patterns
    - Recent important memories

The bulletin is injected into the system prompt alongside (not replacing)
RAG context. RAG provides turn-specific relevance; the bulletin provides
persistent awareness.

Architecture:
    - `MemoryBulletin` singleton created in app.py lifespan
    - `refresh()` runs as a periodic task (every 30 min via TaskQueue)
    - `get_bulletin()` returns the cached bulletin string (sub-ms, no I/O)
    - System prompt builder calls `get_bulletin()` on every turn
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger("nexus.memory_bulletin")

# Default configuration
DEFAULT_REFRESH_INTERVAL = 1800  # 30 minutes
MAX_BULLETIN_CHARS = 2000        # Keep it tight for Ollama's context
MAX_ENTITIES = 10
MAX_PREFERENCES = 5
MAX_MEMORIES = 5


class MemoryBulletin:
    """Periodic LLM-curated knowledge digest.

    Lifecycle:
        1. Created in app.py with references to KG, passive memory, RAG
        2. refresh() called periodically via TaskQueue
        3. get_bulletin() called on every turn by system prompt builder
    """

    def __init__(
        self,
        knowledge_graph=None,
        passive_memory=None,
        rag_pipeline=None,
        model_router=None,
        database=None,
    ):
        self.kg = knowledge_graph
        self.passive_memory = passive_memory
        self.rag = rag_pipeline
        self.model_router = model_router
        self.db = database

        # Cached bulletin
        self._bulletin: str = ""
        self._last_refresh: float = 0
        self._refresh_count: int = 0
        self._refresh_ms: int = 0

    def get_bulletin(self) -> str:
        """Get the current cached bulletin (sub-ms, no I/O).

        Returns empty string if bulletin hasn't been generated yet.
        """
        return self._bulletin

    @property
    def is_stale(self) -> bool:
        """Check if the bulletin needs regeneration."""
        if not self._bulletin:
            return True
        age = time.time() - self._last_refresh
        return age > DEFAULT_REFRESH_INTERVAL

    async def refresh(self) -> str:
        """Regenerate the bulletin from all memory sources.

        Gathers data from:
            1. Knowledge graph (top entities by importance)
            2. Passive memory (user preferences, project context)
            3. Recent high-access memories from RAG

        Then either formats directly or uses LLM to curate.
        """
        start = time.time()

        try:
            sections: list[str] = []

            # 1. Knowledge Graph entities (top by importance)
            kg_section = await self._gather_kg_entities()
            if kg_section:
                sections.append(kg_section)

            # 2. User preferences and project context
            prefs_section = await self._gather_preferences()
            if prefs_section:
                sections.append(prefs_section)

            # 3. Recent high-value memories
            mem_section = await self._gather_top_memories()
            if mem_section:
                sections.append(mem_section)

            if not sections:
                self._bulletin = ""
                self._last_refresh = time.time()
                return ""

            # Combine sections
            raw_bulletin = "\n\n".join(sections)

            # If we have a model router and the bulletin is large, ask LLM to curate
            if self.model_router and len(raw_bulletin) > MAX_BULLETIN_CHARS * 1.5:
                curated = await self._curate_with_llm(raw_bulletin)
                if curated:
                    raw_bulletin = curated

            # Truncate to budget
            if len(raw_bulletin) > MAX_BULLETIN_CHARS:
                raw_bulletin = raw_bulletin[:MAX_BULLETIN_CHARS].rsplit("\n", 1)[0]

            self._bulletin = raw_bulletin
            self._last_refresh = time.time()
            self._refresh_count += 1
            elapsed = int((time.time() - start) * 1000)
            self._refresh_ms += elapsed

            logger.info(
                f"Memory bulletin refreshed: {len(self._bulletin)} chars "
                f"({len(sections)} sections) [{elapsed}ms]"
            )

            return self._bulletin

        except Exception as e:
            logger.warning(f"Memory bulletin refresh failed: {e}")
            self._last_refresh = time.time()  # Prevent rapid retry
            return self._bulletin  # Return stale bulletin

    async def _gather_kg_entities(self) -> str:
        """Gather top entities from the knowledge graph."""
        if not self.kg or self.kg.entity_count == 0:
            return ""

        entities = self.kg.search_entities(limit=MAX_ENTITIES)
        if not entities:
            return ""

        lines = []
        for e in entities:
            line = f"- **{e.name}** ({e.entity_type})"
            # Add key properties
            if e.properties:
                props = []
                for k, v in list(e.properties.items())[:3]:
                    props.append(f"{k}: {v}")
                if props:
                    line += f" — {', '.join(props)}"
            lines.append(line)

        return "**Known Entities:**\n" + "\n".join(lines)

    async def _gather_preferences(self) -> str:
        """Gather user preferences and project context from passive memory."""
        if not self.passive_memory:
            return ""

        try:
            context = await self.passive_memory.get_context_for_prompt(limit=MAX_PREFERENCES)
            return context if context else ""
        except Exception as e:
            logger.debug(f"Bulletin preferences gather failed: {e}")
            return ""

    async def _gather_top_memories(self) -> str:
        """Gather recent high-access memories from the RAG index."""
        if not self.rag or not self.rag.is_active:
            return ""

        try:
            memory_index = self.rag.cluster.memory_index
            if not memory_index:
                return ""

            # Get all memories and find the most accessed ones
            all_mems = await memory_index.scan_all()
            if not all_mems:
                return ""

            # Sort by access_count descending, take top N
            all_mems.sort(key=lambda m: m.get("access_count", 0), reverse=True)
            top = [m for m in all_mems if m.get("access_count", 0) > 0][:MAX_MEMORIES]

            if not top:
                return ""

            # Fetch full text for top memories
            lines = []
            for mem in top:
                mem_id = mem.get("id")
                if not mem_id:
                    continue
                full = await memory_index.get_memory(mem_id)
                if full:
                    text = full.get("text", "")[:200]
                    mem_type = full.get("memory_type", "")
                    accesses = mem.get("access_count", 0)
                    lines.append(f"- [{mem_type}] {text} (accessed {accesses}x)")

            if not lines:
                return ""

            return "**Frequently Referenced:**\n" + "\n".join(lines)

        except Exception as e:
            logger.debug(f"Bulletin memories gather failed: {e}")
            return ""

    async def _curate_with_llm(self, raw_bulletin: str) -> Optional[str]:
        """Use LLM to curate and condense the bulletin."""
        if not self.model_router:
            return None

        try:
            prompt = f"""Condense the following knowledge summary into a brief, well-organized digest.
Keep it under {MAX_BULLETIN_CHARS} characters. Focus on the most important and actionable information.
Use markdown bullet points. Remove redundancy. Keep entity names exact.

Raw knowledge:
{raw_bulletin[:4000]}

Condensed digest:"""

            result = await self.model_router.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a knowledge curator. Be concise and precise.",
                model_name="ollama",
            )

            content = result.get("content", "").strip()
            if content and len(content) > 50:
                return content

        except Exception as e:
            logger.debug(f"Bulletin LLM curation failed: {e}")

        return None

    def get_stats(self) -> dict:
        """Get bulletin statistics."""
        avg_ms = self._refresh_ms / self._refresh_count if self._refresh_count > 0 else 0
        return {
            "bulletin_length": len(self._bulletin),
            "last_refresh": self._last_refresh,
            "refresh_count": self._refresh_count,
            "avg_refresh_ms": round(avg_ms, 1),
            "is_stale": self.is_stale,
            "has_kg": self.kg is not None,
            "has_passive_memory": self.passive_memory is not None,
            "has_rag": self.rag is not None,
        }
