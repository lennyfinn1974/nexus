"""Memory Index — vector index for semantic memory across agents.

Provides semantic search over memories using HNSW vector index:
    - Store memories with embeddings as Redis Hashes + Vector Sets
    - Search by vector similarity (cosine distance)
    - Three-stage deduplication (ID, hash, semantic)
    - Cross-agent memory sharing

Memory storage format:
    nexus:mem:{memory_id} → Hash {
        id, text, embedding (BLOB), type, source_agent, source_conv,
        content_hash, created_at, access_count, last_accessed
    }

Search backends (auto-detected in priority order):
    1. Redis 8 VADD/VSIM (native vectorset module — fastest)
    2. RediSearch FT.CREATE/FT.SEARCH (Redis Stack — legacy)
    3. Brute-force SCAN + cosine similarity (fallback — slowest)
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
VECTORSET_NAME_SUFFIX = "mem_vecs"


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
    """Semantic memory index with auto-detected backend.

    Tries (in order):
        1. Redis 8 VADD/VSIM — native HNSW vectorset (sub-ms search)
        2. RediSearch FT.SEARCH — separate module (legacy Redis Stack)
        3. Brute-force scan — SCAN all hashes + cosine similarity

    Usage:
        idx = MemoryIndex(redis, prefix="nexus:", agent_id="nexus-01")
        await idx.start()

        # Store a memory
        mem_id = await idx.store(
            text="User prefers dark mode and vim keybindings",
            embedding=[0.1, 0.2, ...],  # 768-dim vector
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

    # Search backend modes
    BACKEND_VSIM = "vsim"         # Redis 8 native vectorset
    BACKEND_REDISEARCH = "redisearch"  # FT.CREATE / FT.SEARCH
    BACKEND_SCAN = "scan"         # Brute-force fallback

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
        self._vectorset_key = f"{prefix}{VECTORSET_NAME_SUFFIX}"
        self._backend = self.BACKEND_SCAN  # Default to worst case
        self._index_available = False  # Legacy compat flag

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
        """Detect best available search backend and initialize."""
        # Try Redis 8 VADD/VSIM first (fastest)
        if await self._try_vsim_backend():
            return

        # Try RediSearch FT.CREATE (legacy Redis Stack)
        if await self._try_redisearch_backend():
            return

        # Fallback to brute-force scan
        self._backend = self.BACKEND_SCAN
        self._index_available = False
        logger.warning(
            "No vector search backend available — using brute-force scan. "
            "For best performance, use Redis 8+ (has native VADD/VSIM)."
        )

    async def _try_vsim_backend(self) -> bool:
        """Try to use Redis 8's native VADD/VSIM vectorset."""
        try:
            # Probe: create a tiny test vectorset and remove it
            test_key = f"{self._prefix}_vsim_probe"
            await self._redis.execute_command(
                "VADD", test_key, "VALUES", "3", "1.0", "0.0", "0.0", "__probe__"
            )
            await self._redis.delete(test_key)

            self._backend = self.BACKEND_VSIM
            self._index_available = True

            # Ensure the vectorset exists (VADD creates it on first use)
            # Migrate any existing hash-only memories into the vectorset
            migrated = await self._migrate_hashes_to_vectorset()

            logger.info(
                f"Memory index started: backend=VSIM (Redis 8 native) "
                f"dims={self.vector_dims} key={self._vectorset_key}"
                + (f" migrated={migrated}" if migrated > 0 else "")
            )
            return True

        except Exception as e:
            err_str = str(e).lower()
            if "unknown command" in err_str or "err wrong" in err_str:
                logger.debug(f"VSIM not available: {e}")
            else:
                logger.debug(f"VSIM probe failed: {e}")
            return False

    async def _try_redisearch_backend(self) -> bool:
        """Try to use RediSearch FT.CREATE/FT.SEARCH."""
        try:
            await self._create_ft_index()
            self._backend = self.BACKEND_REDISEARCH
            self._index_available = True
            logger.info(
                f"Memory index started: backend=RediSearch "
                f"dims={self.vector_dims} index={self._index_name}"
            )
            return True

        except Exception as e:
            err_str = str(e).lower()
            if "unknown command" in err_str or "module" in err_str:
                return False
            elif "index already exists" in err_str:
                self._backend = self.BACKEND_REDISEARCH
                self._index_available = True
                logger.info(f"Memory index already exists: {self._index_name}")
                return True
            else:
                logger.debug(f"RediSearch probe failed: {e}")
                return False

    async def _migrate_hashes_to_vectorset(self) -> int:
        """Migrate existing hash-stored memories into the VADD vectorset.

        Only runs once — checks if vectorset has fewer items than hash store.
        Non-blocking: skips items that fail.
        """
        try:
            # Count existing hash memories
            hash_count = 0
            pattern = self._mem_pattern()
            async for _ in self._redis.scan_iter(match=pattern, count=100):
                hash_count += 1

            if hash_count == 0:
                return 0

            # Check vectorset size (VCARD returns cardinality)
            try:
                vs_count = await self._redis.execute_command("VCARD", self._vectorset_key)
                vs_count = int(vs_count or 0)
            except Exception:
                vs_count = 0

            if vs_count >= hash_count:
                return 0  # Already migrated

            # Migrate missing memories
            migrated = 0
            async for key in self._redis.scan_iter(match=pattern, count=100):
                try:
                    data = await self._redis.hmget(key, "id", "embedding")
                    mem_id = data[0]
                    emb_data = data[1]
                    if not mem_id or not emb_data:
                        continue

                    if isinstance(mem_id, bytes):
                        mem_id = mem_id.decode("utf-8")
                    if isinstance(emb_data, str):
                        emb_data = emb_data.encode("latin-1")

                    vec = _bytes_to_float_vector(emb_data)
                    # VADD with FP32 format: VADD key FP32 <blob> element
                    blob = _float_vector_to_bytes(vec)
                    await self._redis.execute_command(
                        "VADD", self._vectorset_key, "FP32", blob, mem_id
                    )
                    migrated += 1
                except Exception as e:
                    logger.debug(f"Migration skip for {key}: {e}")
                    continue

            return migrated

        except Exception as e:
            logger.warning(f"Migration error (non-fatal): {e}")
            return 0

    async def _create_ft_index(self) -> None:
        """Create the RediSearch HNSW vector index (legacy backend)."""
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

    async def stop(self) -> None:
        """Cleanup (index persists in Redis)."""
        logger.info(
            f"Memory index stopped: backend={self._backend} "
            f"stored={self._stored} searched={self._searched} "
            f"duplicates={self._duplicates_found}"
        )

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
            3. Semantic similarity check (if index available)

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
                await self._touch_memory(memory_id)
                self._duplicates_found += 1
                return None

        # Stage 2: Content hash dedup
        c_hash = _content_hash(text)
        existing_id = await self._redis.zscore(self._hash_index_key(), c_hash)
        if existing_id is not None:
            self._duplicates_found += 1
            logger.debug(f"Duplicate content hash: {c_hash[:8]}...")
            return None

        # Stage 3: Semantic dedup (if search backend available)
        if self._backend != self.BACKEND_SCAN:
            similar = await self.search(embedding, limit=1)
            if similar and similar[0]["score"] < SIMILARITY_THRESHOLD:
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

        # Add to vectorset (VSIM backend)
        if self._backend == self.BACKEND_VSIM:
            try:
                blob = _float_vector_to_bytes(embedding)
                # VADD key FP32 <blob> element [SETATTR json]
                attrs = json.dumps({
                    "memory_type": memory_type,
                    "source_conv": source_conv,
                    "created_at": now,
                })
                await self._redis.execute_command(
                    "VADD", self._vectorset_key,
                    "FP32", blob, memory_id,
                    "SETATTR", attrs,
                )
            except Exception as e:
                logger.warning(f"VADD failed for {memory_id} (hash still stored): {e}")

        self._stored += 1
        logger.debug(
            f"Memory stored: id={memory_id} type={memory_type} "
            f"backend={self._backend} hash={c_hash[:8]}..."
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

        Uses the best available backend (VSIM > RediSearch > scan).

        Args:
            query_embedding: Query vector (same dimensions as stored)
            limit: Maximum results to return
            memory_type: Optional filter by memory type tag
            source_conv: Optional filter by source conversation

        Returns:
            List of {id, text, score, memory_type, source_agent, ...} dicts
            sorted by similarity (lowest distance = most similar).
        """
        if self._backend == self.BACKEND_VSIM:
            return await self._vsim_search(query_embedding, limit, memory_type)
        elif self._backend == self.BACKEND_REDISEARCH:
            try:
                return await self._ft_search(query_embedding, limit, memory_type, source_conv)
            except Exception as e:
                logger.warning(f"FT.SEARCH error, falling back to scan: {e}")
                return await self._scan_search(query_embedding, limit)
        else:
            return await self._scan_search(query_embedding, limit)

    async def _vsim_search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        memory_type: str = None,
    ) -> list[dict[str, Any]]:
        """Search using Redis 8 VSIM (native HNSW, sub-ms).

        Uses pipelined HMGET to fetch all metadata in a single round-trip
        instead of N individual calls (eliminates N+1 query problem).
        """
        try:
            blob = _float_vector_to_bytes(query_embedding)

            # Build VSIM command
            cmd = [
                "VSIM", self._vectorset_key,
                "FP32", blob,
                "WITHSCORES",
                "COUNT", str(limit),  # Caller (RAG pipeline) already accounts for filtering headroom
            ]

            # Add FILTER for memory_type if specified
            if memory_type:
                cmd.extend(["FILTER", f".memory_type == '{memory_type}'"])

            t0 = time.time()
            raw = await self._redis.execute_command(*cmd)
            self._searched += 1
            vsim_ms = int((time.time() - t0) * 1000)

            if not raw:
                return []

            # Phase 1: Parse VSIM results into (mem_id, distance) pairs
            candidates = []
            i = 0
            while i < len(raw) - 1:
                mem_id = raw[i]
                score = raw[i + 1]
                i += 2

                if isinstance(mem_id, bytes):
                    mem_id = mem_id.decode("utf-8")
                if isinstance(score, bytes):
                    score = float(score.decode("utf-8"))
                elif isinstance(score, (int, float)):
                    score = float(score)

                # VSIM returns cosine similarity (1.0 = identical)
                # Convert to cosine distance for compatibility (lower = better)
                distance = 1.0 - score
                candidates.append((mem_id, distance))

            if not candidates:
                return []

            # Phase 2: Pipelined HMGET — fetch all metadata in ONE round-trip
            t1 = time.time()
            fields = ("id", "text", "memory_type", "source_agent",
                      "source_conv", "access_count", "created_at")
            pipe = self._redis.pipeline()
            for mem_id, _ in candidates:
                pipe.hmget(self._mem_key(mem_id), *fields)
            all_data = await pipe.execute()
            hmget_ms = int((time.time() - t1) * 1000)

            # Phase 3: Assemble results
            def _d(v):
                return v.decode("utf-8") if isinstance(v, bytes) else (v or "")

            results = []
            for (mem_id, distance), data in zip(candidates, all_data):
                if not data or not data[0]:
                    continue

                result = {
                    "id": _d(data[0]),
                    "text": _d(data[1]),
                    "score": distance,
                    "memory_type": _d(data[2]),
                    "source_agent": _d(data[3]),
                    "source_conv": _d(data[4]),
                    "access_count": _d(data[5]),
                    "created_at": _d(data[6]),
                }

                # Post-filter by memory_type if FILTER didn't work
                if memory_type and result["memory_type"] != memory_type:
                    continue

                results.append(result)

            if vsim_ms + hmget_ms > 50:
                logger.info(
                    f"VSIM search: {len(candidates)} candidates, "
                    f"{len(results)} results [vsim={vsim_ms}ms, hmget={hmget_ms}ms]"
                )

            return results

        except Exception as e:
            logger.warning(f"VSIM search error, falling back to scan: {e}")
            return await self._scan_search(query_embedding, limit)

    async def _ft_search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        memory_type: str = None,
        source_conv: str = None,
    ) -> list[dict[str, Any]]:
        """Search using RediSearch FT.SEARCH (legacy backend)."""
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
        return self._parse_ft_results(results)

    def _parse_ft_results(self, results) -> list[dict[str, Any]]:
        """Parse FT.SEARCH results into clean dicts."""
        if not results or results[0] == 0:
            return []

        parsed = []
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
        """Fallback: brute-force similarity search when no index is available.

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

                similarity = float(np.dot(query_vec, stored_vec) / (query_norm * stored_norm))
                distance = 1.0 - similarity

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
                    "created_at": _decode(data.get(b"created_at", data.get("created_at", "0"))),
                })

            except Exception as e:
                logger.warning(f"Scan search error on key {key}: {e}")
                continue

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

        await self._touch_memory(memory_id)
        return result

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory and remove from hash index + vectorset."""
        key = self._mem_key(memory_id)

        # Get content hash to remove from index
        c_hash = await self._redis.hget(key, "content_hash")
        if c_hash:
            if isinstance(c_hash, bytes):
                c_hash = c_hash.decode("utf-8")
            await self._redis.zrem(self._hash_index_key(), c_hash)

        # Remove from vectorset (VSIM backend)
        if self._backend == self.BACKEND_VSIM:
            try:
                await self._redis.execute_command(
                    "VREM", self._vectorset_key, memory_id
                )
            except Exception:
                pass

        result = await self._redis.delete(key)
        return bool(result)

    # Alias for rag.py pruning
    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID. Alias for delete_memory()."""
        return await self.delete_memory(memory_id)

    async def scan_all(self) -> list[dict[str, Any]]:
        """Scan all memories and return their metadata (no embeddings).

        Used by pruning — returns id, memory_type, created_at, access_count.
        """
        memories = []
        pattern = self._mem_pattern()

        async for key in self._redis.scan_iter(match=pattern, count=100):
            try:
                data = await self._redis.hmget(
                    key, "id", "memory_type", "created_at", "access_count"
                )
                if not data or not data[0]:
                    continue

                def _d(v):
                    if v is None:
                        return ""
                    return v.decode("utf-8") if isinstance(v, bytes) else v

                mem_id = _d(data[0])
                created_at = _d(data[2])
                access_count = _d(data[3])

                memories.append({
                    "id": mem_id,
                    "memory_type": _d(data[1]),
                    "created_at": float(created_at) if created_at else 0,
                    "access_count": int(access_count) if access_count else 0,
                })
            except Exception:
                continue

        return memories

    async def count_memories(self) -> int:
        """Count total memories in the index."""
        if self._backend == self.BACKEND_VSIM:
            try:
                count = await self._redis.execute_command("VCARD", self._vectorset_key)
                return int(count or 0)
            except Exception:
                pass

        # Fallback: scan
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
        if self._backend == self.BACKEND_REDISEARCH and memory_type:
            try:
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
                return self._parse_ft_results(results)
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
            "backend": self._backend,
            "vector_dims": self.vector_dims,
        }

    async def get_index_info(self) -> dict[str, Any]:
        """Get index info for the active backend."""
        if self._backend == self.BACKEND_VSIM:
            try:
                count = await self._redis.execute_command("VCARD", self._vectorset_key)
                return {
                    "available": True,
                    "backend": "vsim",
                    "num_vectors": int(count or 0),
                }
            except Exception as e:
                return {"available": True, "backend": "vsim", "error": str(e)}

        elif self._backend == self.BACKEND_REDISEARCH:
            try:
                info = await self._redis.execute_command(
                    "FT.INFO", self._index_name
                )
                result = {"available": True, "backend": "redisearch"}
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
                return {"available": True, "backend": "redisearch", "error": str(e)}

        return {"available": False, "backend": "scan"}
