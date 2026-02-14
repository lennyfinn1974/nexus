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
    "ollama": 6000,       # ~1500 tokens — tight for 32K context
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
            if query_embedding is None:
                return ""

            # 2. Search memory index
            results = await self.cluster.search_memory(
                query_embedding, limit=limit * 2  # Fetch extra for filtering
            )

            if not results:
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

                # Filter by source conversation if specified
                if source_conv and r.get("source_conv") == source_conv:
                    # Skip results from the SAME conversation (already in context)
                    continue

                text = r.get("text", "")
                if len(text) < MIN_TEXT_LENGTH:
                    continue

                filtered.append(r)

            if not filtered:
                return ""

            # 4. Truncate to limit
            filtered = filtered[:limit]

            # 5. Format for the model's context budget
            max_chars = RAG_CONTEXT_LIMITS.get(model, RAG_CONTEXT_LIMITS["ollama"])
            formatted = self._format_results(filtered, max_chars)

            self._total_retrievals += 1
            self._total_retrieve_ms += int((time.time() - start) * 1000)

            if formatted:
                logger.debug(
                    f"RAG retrieved {len(filtered)} results for query "
                    f"({len(formatted)} chars, {int((time.time() - start) * 1000)}ms)"
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
