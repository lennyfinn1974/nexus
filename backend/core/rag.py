"""RAG Pipeline — Retrieval-Augmented Generation for Nexus.

Provides automatic context enrichment by:
    1. Embedding user queries via local Ollama model
    2. Searching the semantic MemoryIndex for relevant memories
    3. Formatting retrieved context for injection into the system prompt
    4. Ingesting conversations and documents into the memory index

The pipeline is model-aware: Ollama gets a tight budget (~2K tokens),
Claude gets a generous budget (~8K tokens).

Lifecycle:
    - Ingest: After each conversation turn, store key content
    - Retrieve: Before each agent response, search for relevant context
    - Prune: Background task removes stale/low-access memories
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

logger = logging.getLogger("nexus.rag")

# Model-aware context budgets (chars, not tokens)
RAG_CONTEXT_LIMITS = {
    "ollama": 3000,       # ~750 tokens — keep tight for fast 32K inference
    "claude": 24000,      # ~6000 tokens — generous for 200K
    "claude_code": 24000,
}

# Memory types used by RAG
MEMORY_TYPE_CONVERSATION = "conversation"
MEMORY_TYPE_DOCUMENT = "document"
MEMORY_TYPE_SKILL = "skill_knowledge"
MEMORY_TYPE_WEB = "web_content"
MEMORY_TYPE_FACT = "fact"

# Minimum quality thresholds
MIN_TEXT_LENGTH = 50          # Ignore very short snippets
MAX_SIMILARITY_SCORE = 0.85   # Cosine distance — lower is more similar
MIN_INGEST_LENGTH = 100       # Don't ingest messages shorter than this


class RAGPipeline:
    """Retrieval-Augmented Generation pipeline.

    Orchestrates:
        - Query embedding
        - Memory search
        - Context formatting
        - Conversation/document ingestion

    Requires:
        - EmbeddingService for vector generation
        - ClusterManager (with MemoryIndex) for storage/search
    """

    def __init__(self, embedding_service, cluster_manager):
        """Initialize RAG pipeline.

        Args:
            embedding_service: EmbeddingService instance for vector generation
            cluster_manager: ClusterManager with active MemoryIndex
        """
        self.embeddings = embedding_service
        self.cluster = cluster_manager
        self._total_retrievals = 0
        self._total_ingests = 0
        self._total_retrieve_ms = 0
        self._total_ingest_ms = 0

    @property
    def is_active(self) -> bool:
        """Check if RAG pipeline is operational."""
        return (
            self.embeddings is not None
            and self.cluster is not None
            and self.cluster.is_active
            and self.cluster.memory_index is not None
        )

    async def retrieve(
        self,
        query: str,
        model: str = "ollama",
        limit: int = 5,
        memory_types: list[str] | None = None,
        source_conv: str = "",
    ) -> str:
        """Retrieve relevant context for a user query.

        Args:
            query: The user's message to find context for
            model: Current model name (affects context budget)
            limit: Max results to return
            memory_types: Optional filter by memory type
            source_conv: Optional filter by conversation

        Returns:
            Formatted markdown context string, or empty string if no results
        """
        if not self.is_active:
            return ""

        if not query or len(query.strip()) < 10:
            return ""

        start = time.time()
        try:
            # 1. Embed the query
            query_embedding = await self.embeddings.embed(query)
            embed_ms = int((time.time() - start) * 1000)
            if query_embedding is None:
                return ""

            # 2. Search memory index
            # Fetch a broad candidate pool so type-aware selection can find
            # knowledge memories even when conversation memories dominate
            # the top similarity scores (common for vague queries).
            candidate_count = max(limit * 3, 20)
            t_search = time.time()
            results = await self.cluster.search_memory(
                query_embedding, limit=candidate_count
            )
            search_ms = int((time.time() - t_search) * 1000)

            if not results:
                logger.info(
                    f"RAG retrieve: no candidates for '{query[:60]}' "
                    f"[embed={embed_ms}ms, search={search_ms}ms]"
                )
                return ""

            # 3. Filter and rank
            filtered = []
            for r in results:
                # Skip low-quality matches
                score = r.get("score", 1.0)
                if score > MAX_SIMILARITY_SCORE:
                    continue

                # Filter by memory type if specified
                if memory_types and r.get("memory_type") not in memory_types:
                    continue

                # Filter out same-conversation results ONLY for conversation type
                # (web_content, skill_knowledge, fact should always surface)
                mem_type = r.get("memory_type", "")
                if (
                    source_conv
                    and r.get("source_conv") == source_conv
                    and mem_type == MEMORY_TYPE_CONVERSATION
                ):
                    continue

                text = r.get("text", "")
                if len(text) < MIN_TEXT_LENGTH:
                    continue

                # Boost structured knowledge types (lower score = more similar)
                # 0.8x gives knowledge a 20% advantage — helps it surface for
                # semi-specific queries without needing the slot reservation
                if mem_type in (MEMORY_TYPE_WEB, MEMORY_TYPE_SKILL, MEMORY_TYPE_FACT):
                    r["score"] = score * 0.8

                filtered.append(r)

            if not filtered:
                total_ms = int((time.time() - start) * 1000)
                logger.info(
                    f"RAG retrieve: 0 results for '{query[:60]}' "
                    f"({len(results)} candidates, all filtered) "
                    f"[embed={embed_ms}ms, search={search_ms}ms, total={total_ms}ms]"
                )
                return ""

            # 4. Type-aware selection — guarantee knowledge types surface
            #    Without this, vague queries return only conversation memories
            #    (which match on phrasing) and crowd out rich skill_knowledge.
            filtered.sort(key=lambda x: x.get("score", 1.0))

            # Check if knowledge types are already in the top N
            KNOWLEDGE_TYPES = {MEMORY_TYPE_SKILL, MEMORY_TYPE_WEB, MEMORY_TYPE_FACT, MEMORY_TYPE_DOCUMENT}
            top_n = filtered[:limit]
            has_knowledge_in_top = any(
                r.get("memory_type", "") in KNOWLEDGE_TYPES for r in top_n
            )
            knowledge_available = any(
                r.get("memory_type", "") in KNOWLEDGE_TYPES for r in filtered
            )

            if not has_knowledge_in_top and knowledge_available:
                # Knowledge exists in candidates but was crowded out by conversation.
                # Reserve 1 slot for the best knowledge result.
                knowledge = [r for r in filtered if r.get("memory_type", "") in KNOWLEDGE_TYPES]
                conversation = [r for r in filtered if r.get("memory_type", "") not in KNOWLEDGE_TYPES]
                # Best knowledge result + fill remaining with conversation
                selected = knowledge[:1] + conversation[: limit - 1]
                selected.sort(key=lambda x: x.get("score", 1.0))
                filtered = selected
            else:
                # Knowledge already surfaces naturally — just truncate
                filtered = filtered[:limit]

            # Touch accessed memories (fire-and-forget, non-blocking)
            if self.cluster and self.cluster.memory_index:
                try:
                    mem_idx = self.cluster.memory_index
                    pipe = mem_idx._redis.pipeline()
                    now_ts = str(int(time.time()))
                    for r in filtered:
                        mem_id = r.get("id")
                        if mem_id:
                            key = mem_idx._mem_key(mem_id)
                            pipe.hincrby(key, "access_count", 1)
                            pipe.hset(key, "last_accessed", now_ts)
                    await pipe.execute()
                except Exception:
                    pass  # Non-critical — never block retrieval

            # 5. Format for the model's context budget
            max_chars = RAG_CONTEXT_LIMITS.get(model, RAG_CONTEXT_LIMITS["ollama"])
            formatted = self._format_results(filtered, max_chars)

            total_ms = int((time.time() - start) * 1000)
            self._total_retrievals += 1
            self._total_retrieve_ms += total_ms

            types_found = ", ".join(
                sorted(set(r.get("memory_type", "?") for r in filtered))
            )
            logger.info(
                f"RAG retrieve: {len(filtered)} results for '{query[:60]}' "
                f"[types={types_found}] ({len(formatted)} chars) "
                f"[embed={embed_ms}ms, search={search_ms}ms, total={total_ms}ms]"
            )

            return formatted

        except Exception as e:
            logger.warning(f"RAG retrieval error: {e}")
            return ""

    async def ingest_conversation(
        self,
        conv_id: str,
        user_message: str,
        assistant_response: str,
        model_used: str = "",
    ) -> Optional[str]:
        """Ingest a conversation turn into the memory index.

        Extracts key information from the exchange and stores it
        with embeddings for future retrieval.

        Args:
            conv_id: Conversation ID
            user_message: The user's message
            assistant_response: The assistant's response
            model_used: Which model generated the response

        Returns:
            Memory ID if stored, None if skipped
        """
        if not self.is_active:
            return None

        # Skip very short or trivial messages
        if len(user_message) < MIN_INGEST_LENGTH and len(assistant_response) < MIN_INGEST_LENGTH:
            return None

        # Skip command-like messages
        if user_message.strip().startswith("/"):
            return None

        start = time.time()
        try:
            # Build a condensed representation of the exchange
            condensed = self._condense_exchange(user_message, assistant_response)
            if not condensed or len(condensed) < MIN_TEXT_LENGTH:
                return None

            # Generate embedding for the condensed text
            embedding = await self.embeddings.embed(condensed)
            if embedding is None:
                return None

            # Store in memory index
            memory_id = await self.cluster.store_memory(
                text=condensed,
                embedding=embedding,
                memory_type=MEMORY_TYPE_CONVERSATION,
                source_conv=conv_id,
            )

            self._total_ingests += 1
            self._total_ingest_ms += int((time.time() - start) * 1000)

            if memory_id:
                logger.debug(f"RAG ingested conversation turn ({len(condensed)} chars, {conv_id[:8]})")

            return memory_id

        except Exception as e:
            logger.warning(f"RAG ingest error: {e}")
            return None

    async def ingest_document(
        self,
        text: str,
        source: str = "",
        memory_type: str = MEMORY_TYPE_DOCUMENT,
        chunk_size: int = 1500,
        chunk_overlap: int = 200,
    ) -> list[str]:
        """Ingest a document by chunking and embedding.

        Splits the document into overlapping chunks and stores each
        with its embedding in the memory index.

        Args:
            text: Document text
            source: Source identifier (filename, URL, etc.)
            memory_type: Type classification for the memories
            chunk_size: Target chunk size in characters
            chunk_overlap: Overlap between chunks

        Returns:
            List of memory IDs for stored chunks
        """
        if not self.is_active:
            return []

        if not text or len(text) < MIN_TEXT_LENGTH:
            return []

        try:
            # Chunk the document
            chunks = self._chunk_text(text, chunk_size, chunk_overlap)
            if not chunks:
                return []

            # Batch embed all chunks
            embeddings = await self.embeddings.embed_batch(chunks)

            # Store each chunk
            memory_ids: list[str] = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                if embedding is None:
                    continue

                # Add source metadata to chunk
                chunk_text = chunk
                if source:
                    chunk_text = f"[Source: {source}]\n{chunk}"

                mid = await self.cluster.store_memory(
                    text=chunk_text,
                    embedding=embedding,
                    memory_type=memory_type,
                    source_conv=source,
                )
                if mid:
                    memory_ids.append(mid)

            logger.info(f"RAG ingested document: {len(memory_ids)}/{len(chunks)} chunks from {source}")
            return memory_ids

        except Exception as e:
            logger.warning(f"RAG document ingest error: {e}")
            return []

    async def ingest_skill_knowledge(
        self,
        skill_id: str,
        skill_name: str,
        content: str,
    ) -> list[str]:
        """Ingest skill knowledge for RAG retrieval.

        Args:
            skill_id: Skill identifier
            skill_name: Human-readable skill name
            content: Skill knowledge content

        Returns:
            List of memory IDs
        """
        return await self.ingest_document(
            text=content,
            source=f"skill:{skill_name}",
            memory_type=MEMORY_TYPE_SKILL,
            chunk_size=1000,
            chunk_overlap=150,
        )

    async def ingest_web_content(
        self,
        user_query: str,
        web_results: list[dict],
        conv_id: str = "",
    ) -> Optional[str]:
        """Ingest condensed web search results into memory.

        Condenses multiple web tool results into a single structured memory
        (~1500 chars) with one embedding call. Memory-efficient: no raw HTML dumps.

        Args:
            user_query: The user's original question
            web_results: List of dicts from AgentAttempt.web_results
            conv_id: Source conversation ID

        Returns:
            Memory ID if stored, None if skipped
        """
        if not self.is_active or not web_results:
            return None

        start = time.time()
        try:
            # Extract search query from google_search results
            search_query = ""
            fetch_contents: list[str] = []
            source_urls: list[str] = []

            for wr in web_results:
                tool = wr.get("tool", "")
                query_data = wr.get("query", {})
                result_text = wr.get("result", "")

                if tool == "google_search":
                    # Extract the search query
                    if isinstance(query_data, dict):
                        search_query = query_data.get("query", query_data.get("q", ""))
                    elif isinstance(query_data, str):
                        search_query = query_data

                elif tool in ("web_fetch", "web_fetch_rendered"):
                    # Extract URL and content
                    url = ""
                    if isinstance(query_data, dict):
                        url = query_data.get("url", "")
                    elif isinstance(query_data, str):
                        url = query_data
                    if url:
                        source_urls.append(url)

                    # Take first 600 chars of meaningful content
                    if result_text:
                        content = self._extract_key_content(result_text, max_chars=600)
                        if content and len(content) > MIN_TEXT_LENGTH:
                            fetch_contents.append(content)

            if not fetch_contents and not search_query:
                return None

            # Build condensed memory (target ~1500 chars)
            topic = search_query or user_query[:200]
            parts = [f"Topic: {topic}"]

            # Max 3 web results
            for i, content in enumerate(fetch_contents[:3]):
                parts.append(f"Content {i + 1}: {content}")

            if source_urls:
                parts.append("Sources: " + ", ".join(source_urls[:3]))

            condensed = "\n\n".join(parts)
            if len(condensed) > 2000:
                condensed = condensed[:2000]

            if len(condensed) < MIN_TEXT_LENGTH:
                return None

            # Embed and store
            embedding = await self.embeddings.embed(condensed)
            if embedding is None:
                return None

            memory_id = await self.cluster.store_memory(
                text=condensed,
                embedding=embedding,
                memory_type=MEMORY_TYPE_WEB,
                source_conv=conv_id,
            )

            self._total_ingests += 1
            self._total_ingest_ms += int((time.time() - start) * 1000)

            if memory_id:
                logger.info(
                    f"RAG ingested web content: {len(condensed)} chars, "
                    f"{len(fetch_contents)} pages ({conv_id[:8] if conv_id else 'no-conv'})"
                )

            return memory_id

        except Exception as e:
            logger.warning(f"RAG web content ingest error: {e}")
            return None

    async def prune_old_memories(
        self,
        web_max_days: int = 30,
        conv_max_days: int = 14,
    ) -> int:
        """Prune stale memories that have never been retrieved.

        - web_content older than web_max_days with 0 access → delete
        - conversation older than conv_max_days with 0 access → delete
        - skill_knowledge and fact types are never auto-pruned

        Returns:
            Number of memories pruned
        """
        if not self.is_active:
            return 0

        try:
            memory_index = self.cluster.memory_index
            if not memory_index:
                return 0

            pruned = 0
            now = time.time()
            web_cutoff = now - (web_max_days * 86400)
            conv_cutoff = now - (conv_max_days * 86400)

            # Scan all memories and collect prunable IDs
            all_memories = await memory_index.scan_all()
            prune_ids: list[str] = []

            for mem in all_memories:
                mem_type = mem.get("memory_type", "")
                created_at = mem.get("created_at", 0)
                access_count = mem.get("access_count", 0)
                mem_id = mem.get("id", "")

                if not mem_id or not created_at:
                    continue

                # Skip curated types
                if mem_type in (MEMORY_TYPE_SKILL, MEMORY_TYPE_FACT):
                    continue

                # Prune web content after web_max_days with no retrieval
                if mem_type == MEMORY_TYPE_WEB and created_at < web_cutoff and access_count == 0:
                    prune_ids.append(mem_id)

                # Prune conversations after conv_max_days with no retrieval
                elif mem_type == MEMORY_TYPE_CONVERSATION and created_at < conv_cutoff and access_count == 0:
                    prune_ids.append(mem_id)

            # Delete in batches
            for mem_id in prune_ids:
                try:
                    await memory_index.delete(mem_id)
                    pruned += 1
                except Exception:
                    pass

            if pruned > 0:
                logger.info(f"RAG pruned {pruned} stale memories (web:{web_max_days}d, conv:{conv_max_days}d)")

            return pruned

        except Exception as e:
            logger.warning(f"RAG pruning error: {e}")
            return 0

    def _condense_exchange(self, user_msg: str, assistant_msg: str) -> str:
        """Condense a conversation exchange into a storable format.

        Extracts the key information — not the full verbatim exchange.
        Limits output to ~2000 chars max.
        """
        # Clean and truncate
        user_clean = user_msg.strip()[:800]
        # For assistant response, take the most informative part
        # Skip code blocks and focus on explanatory text
        assistant_clean = self._extract_key_content(assistant_msg, max_chars=1200)

        if not assistant_clean:
            return ""

        return f"Q: {user_clean}\nA: {assistant_clean}"

    def _extract_key_content(self, text: str, max_chars: int = 1200) -> str:
        """Extract the most informative content from a response.

        Prioritizes explanatory text over code blocks.
        """
        if not text:
            return ""

        # Remove very long code blocks (keep short ones)
        cleaned = re.sub(
            r"```[\s\S]{500,}?```",
            "[code block omitted]",
            text,
        )

        # Remove tool call/result blocks
        cleaned = re.sub(
            r"<tool_call>[\s\S]*?</tool_call>",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"<tool_result>[\s\S]*?</tool_result>",
            "",
            cleaned,
        )

        # Remove excessive whitespace
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        if len(cleaned) > max_chars:
            # Truncate at paragraph boundary
            truncated = cleaned[:max_chars]
            last_para = truncated.rfind("\n\n")
            if last_para > max_chars * 0.5:
                truncated = truncated[:last_para]
            cleaned = truncated.strip()

        return cleaned

    def _chunk_text(
        self, text: str, chunk_size: int = 1500, overlap: int = 200,
    ) -> list[str]:
        """Split text into overlapping chunks at natural boundaries.

        Tries to split at paragraph boundaries, then sentence boundaries,
        then word boundaries.
        """
        if len(text) <= chunk_size:
            return [text.strip()] if text.strip() else []

        chunks: list[str] = []
        start = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))

            if end < len(text):
                # Try to find a natural break point
                # Priority: paragraph > sentence > word
                window = text[start:end]

                # Look for paragraph break in last 30% of chunk
                break_zone_start = int(len(window) * 0.7)
                para_break = window.rfind("\n\n", break_zone_start)
                if para_break > 0:
                    end = start + para_break + 2
                else:
                    # Look for sentence break
                    sent_break = max(
                        window.rfind(". ", break_zone_start),
                        window.rfind("! ", break_zone_start),
                        window.rfind("? ", break_zone_start),
                    )
                    if sent_break > 0:
                        end = start + sent_break + 2
                    else:
                        # Look for word break
                        word_break = window.rfind(" ", break_zone_start)
                        if word_break > 0:
                            end = start + word_break + 1

            chunk = text[start:end].strip()
            if chunk and len(chunk) >= MIN_TEXT_LENGTH:
                chunks.append(chunk)

            # Move start with overlap
            start = end - overlap if end < len(text) else end

        return chunks

    def _format_results(self, results: list[dict], max_chars: int) -> str:
        """Format retrieved memories as markdown context.

        Respects the character budget for the target model.
        """
        if not results:
            return ""

        sections: list[str] = []
        total_chars = 0

        for i, r in enumerate(results):
            text = r.get("text", "")
            score = r.get("score", 1.0)
            memory_type = r.get("memory_type", "unknown")
            relevance = f"{(1 - score) * 100:.0f}%"

            # Format each result
            section = f"**[{memory_type}]** (relevance: {relevance})\n{text}"

            # Check budget
            if total_chars + len(section) + 10 > max_chars:
                # Truncate this section to fit
                remaining = max_chars - total_chars - 50
                if remaining > MIN_TEXT_LENGTH:
                    section = section[:remaining] + "..."
                    sections.append(section)
                break

            sections.append(section)
            total_chars += len(section) + 5  # +5 for separators

        if not sections:
            return ""

        return "\n\n---\n\n".join(sections)

    def get_stats(self) -> dict:
        """Get pipeline statistics."""
        avg_retrieve = (
            self._total_retrieve_ms / self._total_retrievals
            if self._total_retrievals > 0
            else 0
        )
        avg_ingest = (
            self._total_ingest_ms / self._total_ingests
            if self._total_ingests > 0
            else 0
        )
        return {
            "active": self.is_active,
            "total_retrievals": self._total_retrievals,
            "total_ingests": self._total_ingests,
            "avg_retrieve_ms": round(avg_retrieve, 1),
            "avg_ingest_ms": round(avg_ingest, 1),
            "embedding": self.embeddings.get_stats() if self.embeddings else None,
        }
