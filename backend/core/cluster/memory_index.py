"""Memory Index — RediSearch vector index for semantic memory across agents.

Provides semantic search over memories using HNSW vector index:
    - Store memories with embeddings as Redis Hashes
    - Search by vector similarity (cosine distance)
    - Three-stage deduplication (ID, hash, semantic)
    - Cross-agent memory sharing

Memory storage format:
    nexus:mem:{memory_id} → Hash {
        id, text, embedding (BLOB), type, source_agent, source_conv,
        content_hash, created_at, access_count, last_accessed
    }

Index:
    nexus:mem_idx → RediSearch HNSW index on embedding field

Requires RediSearch module (included in Redis Stack / Redis 8).
Gracefully degrades to hash-only storage if RediSearch is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import struct
import time
import uuid
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("nexus.cluster.memory_index")

# Defaults
DEFAULT_VECTOR_DIMS = 1536  # OpenAI/Ollama embedding dimension
SIMILARITY_THRESHOLD = 0.12  # Cosine distance below this = duplicate
MAX_SEARCH_RESULTS = 20
MEMORY_PREFIX = "mem"
INDEX_NAME_SUFFIX = "mem_idx"


def _float_vector_to_bytes(vector: list[float]) -> bytes:
    """Convert a float vector to bytes for Redis storage."""
    return struct.pack(f"{len(vector)}f", *vector)


def _bytes_to_float_vector(data: bytes) -> list[float]:
    """Convert bytes back to a float vector."""
    n = len(data) // 4  # 4 bytes per float32
    return list(struct.unpack(f"{n}f", data))


def _content_hash(text: str) -> str:
    """Generate a content hash for deduplication."""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:32]


class MemoryIndex:
    """RediSearch-backed semantic memory index.

    Usage:
        idx = MemoryIndex(redis, prefix="nexus:", agent_id="nexus-01")
        await idx.start()

        # Store a memory
        mem_id = await idx.store(
            text="User prefers dark mode and vim keybindings",
            embedding=[0.1, 0.2, ...],  # 1536-dim vector
            memory_type="preference",
            source_conv="conv-123",
        )

        # Semantic search
        results = await idx.search(
            query_embedding=[0.1, 0.2, ...],
            limit=5,
        )
        # Returns: [{"id": "mem-xxx", "text": "...", "score": 0.95, ...}, ...]

        await idx.stop()
    """

    def __init__(
        self,
        redis,
        prefix: str,
        agent_id: str,
        vector_dims: int = DEFAULT_VECTOR_DIMS,
    ):
        self._redis = redis
        self._prefix = prefix
        self.agent_id = agent_id
        self.vector_dims = vector_dims

        self._index_name = f"{prefix}{INDEX_NAME_SUFFIX}"
        self._index_available = False

        # Stats
        self._stored = 0
        self._searched = 0
        self._duplicates_found = 0

    # ── Key helpers ──────────────────────────────────────────────

    def _mem_key(self, memory_id: str) -> str:
        return f"{self._prefix}{MEMORY_PREFIX}:{memory_id}"

    def _mem_pattern(self) -> str:
        return f"{self._prefix}{MEMORY_PREFIX}:*"

    def _hash_index_key(self) -> str:
        """Sorted set of content hashes → memory IDs for hash-based dedup."""
        return f"{self._prefix}mem_hashes"

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Create the RediSearch index if it doesn't exist."""
        try:
            await self._create_index()
            self._index_available = True
            logger.info(
                f"Memory index started: dims={self.vector_dims} "
                f"index={self._index_name}"
            )
        except Exception as e:
            if "unknown command" in str(e).lower() or "module" in str(e).lower():
                logger.warning(
                    "RediSearch not available — falling back to hash-only storage. "
                    "Install Redis Stack for semantic search."
                )
                self._index_available = False
            else:
                # Index might already exist
                if "Index already exists" in str(e):
                    self._index_available = True
                    logger.info(f"Memory index already exists: {self._index_name}")
                else:
                    logger.warning(f"Error creating memory index: {e}")
                    self._index_available = False

    async def stop(self) -> None:
        """Cleanup (index persists in Redis)."""
        logger.info(
            f"Memory index stopped: stored={self._stored} "
            f"searched={self._searched} duplicates={self._duplicates_found}"
        )

    async def _create_index(self) -> None:
        """Create the RediSearch HNSW vector index.

        Uses FT.CREATE with VECTOR field type for HNSW similarity search.
        """
        # Build the FT.CREATE command manually
        # Schema: text TEXT, memory_type TAG, source_agent TAG,
        #         source_conv TAG, embedding VECTOR HNSW
        cmd = [
            "FT.CREATE", self._index_name,
            "ON", "HASH",
            "PREFIX", "1", f"{self._prefix}{MEMORY_PREFIX}:",
            "SCHEMA",
            "text", "TEXT", "WEIGHT", "1.0",
            "memory_type", "TAG",
            "source_agent", "TAG",
            "source_conv", "TAG",
            "created_at", "NUMERIC", "SORTABLE",
            "access_count", "NUMERIC", "SORTABLE",
            "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32",
            "DIM", str(self.vector_dims),
            "DISTANCE_METRIC", "COSINE",
        ]

        await self._redis.execute_command(*cmd)
        logger.info(f"Created RediSearch index: {self._index_name}")

    # ── Store ────────────────────────────────────────────────────

    async def store(
        self,
        text: str,
        embedding: list[float],
        memory_type: str = "general",
        source_conv: str = "",
        metadata: dict[str, Any] = None,
        memory_id: str = None,
    ) -> Optional[str]:
        """Store a memory with its embedding vector.

        Performs three-stage deduplication:
            1. ID check (if memory_id provided)
            2. Content hash check (exact text match)
            3. Semantic similarity check (if RediSearch available)

        Args:
            text: The memory text content
            embedding: Vector embedding (must match vector_dims)
            memory_type: Category tag (preference, project, pattern, fact, etc.)
            source_conv: Conversation ID where this was learned
            metadata: Additional JSON metadata
            memory_id: Optional explicit ID (auto-generated if not provided)

        Returns:
            memory_id if stored, None if deduplicated
        """
        if len(embedding) != self.vector_dims:
            logger.warning(
                f"Embedding dimension mismatch: got {len(embedding)}, "
                f"expected {self.vector_dims}. Skipping."
            )
            return None

        # Stage 1: ID dedup
        if memory_id:
            existing = await self._redis.exists(self._mem_key(memory_id))
            if existing:
                # Update access count instead of creating duplicate
                await self._touch_memory(memory_id)
                self._duplicates_found += 1
                return None

        # Stage 2: Content hash dedup
        c_hash = _content_hash(text)
        existing_id = await self._redis.zscore(self._hash_index_key(), c_hash)
        if existing_id is not None:
            # Exact content match exists
            self._duplicates_found += 1
            logger.debug(f"Duplicate content hash: {c_hash[:8]}...")
            return None

        # Stage 3: Semantic dedup (if index available)
        if self._index_available:
            similar = await self.search(embedding, limit=1)
            if similar and similar[0]["score"] < SIMILARITY_THRESHOLD:
                # Too similar to existing memory
                self._duplicates_found += 1
                logger.debug(
                    f"Semantic duplicate found: score={similar[0]['score']:.4f} "
                    f"existing={similar[0]['id']}"
                )
                return None

        # No duplicates — store
        if not memory_id:
            memory_id = f"mem-{uuid.uuid4().hex[:12]}"

        now = int(time.time())
        mem_data = {
            "id": memory_id,
            "text": text,
            "embedding": _float_vector_to_bytes(embedding),
            "memory_type": memory_type,
            "source_agent": self.agent_id,
            "source_conv": source_conv,
            "content_hash": c_hash,
            "metadata": json.dumps(metadata or {}),
            "created_at": str(now),
            "access_count": "0",
            "last_accessed": str(now),
        }

        key = self._mem_key(memory_id)
        await self._redis.hset(key, mapping=mem_data)

        # Register content hash
        await self._redis.zadd(self._hash_index_key(), {c_hash: now})

        self._stored += 1
        logger.debug(
            f"Memory stored: id={memory_id} type={memory_type} "
            f"hash={c_hash[:8]}..."
        )

        return memory_id

    async def _touch_memory(self, memory_id: str) -> None:
        """Update access count and last_accessed timestamp."""
        key = self._mem_key(memory_id)
        pipe = self._redis.pipeline()
        pipe.hincrby(key, "access_count", 1)
        pipe.hset(key, "last_accessed", str(int(time.time())))
        await pipe.execute()

    # ── Search ───────────────────────────────────────────────────

    async def search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        memory_type: str = None,
        source_conv: str = None,
    ) -> list[dict[str, Any]]:
        """Semantic search over stored memories.

        Args:
            query_embedding: Query vector (same dimensions as stored)
            limit: Maximum results to return
            memory_type: Optional filter by memory type tag
            source_conv: Optional filter by source conversation

        Returns:
            List of {id, text, score, memory_type, source_agent, ...} dicts
            sorted by similarity (lowest distance = most similar).
        """
        if not self._index_available:
            logger.debug("Index unavailable, falling back to scan search")
            return await self._scan_search(query_embedding, limit)

        try:
            # Build FT.SEARCH query with KNN
            query_blob = _float_vector_to_bytes(query_embedding)

            # Build filter
            filters = "*"
            if memory_type:
                filters = f"@memory_type:{{{memory_type}}}"
            if source_conv:
                conv_filter = f"@source_conv:{{{source_conv}}}"
                if filters == "*":
                    filters = conv_filter
                else:
                    filters = f"({filters} {conv_filter})"

            # FT.SEARCH with KNN
            # Syntax: FT.SEARCH idx "@field:[VECTOR_RANGE $N @embedding $BLOB]"
            # or: FT.SEARCH idx "*=>[KNN $K @embedding $BLOB AS score]"
            query = f"{filters}=>[KNN {limit} @embedding $query_vec AS score]"

            results = await self._redis.execute_command(
                "FT.SEARCH", self._index_name,
                query,
                "PARAMS", "2", "query_vec", query_blob,
                "SORTBY", "score",
                "LIMIT", "0", str(limit),
                "RETURN", "7",
                "id", "text", "score", "memory_type",
                "source_agent", "source_conv", "access_count",
                "DIALECT", "2",
            )

            self._searched += 1
            return self._parse_search_results(results)

        except Exception as e:
            logger.warning(f"Search error: {e}")
            return await self._scan_search(query_embedding, limit)

    def _parse_search_results(self, results) -> list[dict[str, Any]]:
        """Parse FT.SEARCH results into clean dicts."""
        if not results or results[0] == 0:
            return []

        parsed = []
        total = results[0]
        i = 1

        while i < len(results):
            doc_key = results[i]
            if isinstance(doc_key, bytes):
                doc_key = doc_key.decode("utf-8")
            i += 1

            if i >= len(results):
                break

            fields = results[i]
            i += 1

            if not isinstance(fields, list):
                continue

            doc = {}
            for j in range(0, len(fields), 2):
                k = fields[j]
                v = fields[j + 1] if j + 1 < len(fields) else ""
                if isinstance(k, bytes):
                    k = k.decode("utf-8")
                if isinstance(v, bytes):
                    v = v.decode("utf-8")
                doc[k] = v

            # Convert score to float
            if "score" in doc:
                try:
                    doc["score"] = float(doc["score"])
                except (ValueError, TypeError):
                    doc["score"] = 1.0

            parsed.append(doc)

        return parsed

    async def _scan_search(
        self,
        query_embedding: list[float],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Fallback: brute-force similarity search when RediSearch is unavailable.

        Scans all memory hashes and computes cosine similarity.
        Only practical for small memory sets (< 10K items).
        """
        query_vec = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        results = []
        pattern = self._mem_pattern()

        async for key in self._redis.scan_iter(match=pattern, count=100):
            try:
                data = await self._redis.hgetall(key)
                if not data:
                    continue

                # Get embedding
                emb_data = data.get(b"embedding") or data.get("embedding")
                if not emb_data:
                    continue

                if isinstance(emb_data, str):
                    emb_data = emb_data.encode("latin-1")

                stored_vec = np.array(
                    _bytes_to_float_vector(emb_data), dtype=np.float32
                )
                stored_norm = np.linalg.norm(stored_vec)
                if stored_norm == 0:
                    continue

                # Cosine distance
                similarity = float(np.dot(query_vec, stored_vec) / (query_norm * stored_norm))
                distance = 1.0 - similarity

                # Decode fields
                def _decode(val):
                    return val.decode("utf-8") if isinstance(val, bytes) else val

                results.append({
                    "id": _decode(data.get(b"id", data.get("id", ""))),
                    "text": _decode(data.get(b"text", data.get("text", ""))),
                    "score": distance,
                    "memory_type": _decode(data.get(b"memory_type", data.get("memory_type", ""))),
                    "source_agent": _decode(data.get(b"source_agent", data.get("source_agent", ""))),
                    "source_conv": _decode(data.get(b"source_conv", data.get("source_conv", ""))),
                    "access_count": _decode(data.get(b"access_count", data.get("access_count", "0"))),
                })

            except Exception as e:
                logger.warning(f"Scan search error on key {key}: {e}")
                continue

        # Sort by distance (lowest = most similar) and limit
        results.sort(key=lambda r: r["score"])
        self._searched += 1

        return results[:limit]

    # ── Memory Management ────────────────────────────────────────

    async def get_memory(self, memory_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a specific memory by ID."""
        key = self._mem_key(memory_id)
        data = await self._redis.hgetall(key)

        if not data:
            return None

        def _decode(val):
            return val.decode("utf-8") if isinstance(val, bytes) else val

        result = {}
        for k, v in data.items():
            k = _decode(k)
            if k == "embedding":
                continue  # Skip binary embedding in response
            result[k] = _decode(v)

        # Touch the memory (update access stats)
        await self._touch_memory(memory_id)

        return result

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory and remove from hash index."""
        key = self._mem_key(memory_id)

        # Get content hash to remove from index
        c_hash = await self._redis.hget(key, "content_hash")
        if c_hash:
            if isinstance(c_hash, bytes):
                c_hash = c_hash.decode("utf-8")
            await self._redis.zrem(self._hash_index_key(), c_hash)

        result = await self._redis.delete(key)
        return bool(result)

    async def count_memories(self) -> int:
        """Count total memories in the index."""
        count = 0
        pattern = self._mem_pattern()
        async for _ in self._redis.scan_iter(match=pattern, count=100):
            count += 1
        return count

    async def get_memory_types(self) -> dict[str, int]:
        """Get counts of memories grouped by type."""
        types: dict[str, int] = {}
        pattern = self._mem_pattern()

        async for key in self._redis.scan_iter(match=pattern, count=100):
            try:
                mtype = await self._redis.hget(key, "memory_type")
                if mtype:
                    if isinstance(mtype, bytes):
                        mtype = mtype.decode("utf-8")
                    types[mtype] = types.get(mtype, 0) + 1
            except Exception:
                pass

        return types

    async def get_recent_memories(
        self, limit: int = 20, memory_type: str = None
    ) -> list[dict[str, Any]]:
        """Get most recently created memories."""
        if self._index_available and memory_type:
            try:
                # Use FT.SEARCH with sort
                query = f"@memory_type:{{{memory_type}}}"
                results = await self._redis.execute_command(
                    "FT.SEARCH", self._index_name,
                    query,
                    "SORTBY", "created_at", "DESC",
                    "LIMIT", "0", str(limit),
                    "RETURN", "6",
                    "id", "text", "memory_type", "source_agent",
                    "created_at", "access_count",
                    "DIALECT", "2",
                )
                return self._parse_search_results(results)
            except Exception:
                pass

        # Fallback: scan and sort
        memories = []
        pattern = self._mem_pattern()

        async for key in self._redis.scan_iter(match=pattern, count=100):
            try:
                data = await self._redis.hmget(
                    key, "id", "text", "memory_type", "source_agent",
                    "created_at", "access_count"
                )
                if data[0]:
                    def _d(v):
                        return v.decode("utf-8") if isinstance(v, bytes) else (v or "")

                    mem = {
                        "id": _d(data[0]),
                        "text": _d(data[1]),
                        "memory_type": _d(data[2]),
                        "source_agent": _d(data[3]),
                        "created_at": _d(data[4]),
                        "access_count": _d(data[5]),
                    }

                    if memory_type and mem["memory_type"] != memory_type:
                        continue

                    memories.append(mem)
            except Exception:
                continue

        # Sort by created_at DESC
        memories.sort(key=lambda m: m.get("created_at", "0"), reverse=True)
        return memories[:limit]

    # ── Stats ────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return memory index statistics."""
        return {
            "stored": self._stored,
            "searched": self._searched,
            "duplicates_found": self._duplicates_found,
            "index_available": self._index_available,
            "vector_dims": self.vector_dims,
        }

    async def get_index_info(self) -> dict[str, Any]:
        """Get RediSearch index info (if available)."""
        if not self._index_available:
            return {"available": False}

        try:
            info = await self._redis.execute_command(
                "FT.INFO", self._index_name
            )
            # Parse the flat list into a dict
            result = {"available": True}
            if isinstance(info, list):
                for i in range(0, len(info) - 1, 2):
                    k = info[i]
                    v = info[i + 1]
                    if isinstance(k, bytes):
                        k = k.decode("utf-8")
                    if isinstance(v, bytes):
                        v = v.decode("utf-8")
                    if k in ("num_docs", "num_records", "num_terms",
                             "total_indexing_time", "bytes_per_record_avg"):
                        result[k] = v
            return result
        except Exception as e:
            return {"available": True, "error": str(e)}
