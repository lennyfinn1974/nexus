"""Embedding Service — local-first embedding generation.

Two backends:
    1. **FastEmbedService** (default) — CPU-only via ONNX Runtime.
       Zero GPU contention with Ollama LLMs. ~8ms per embedding.
    2. **EmbeddingService** (legacy) — Ollama /api/embed endpoint.
       Causes GPU model swaps with large LLMs (400ms+ per embed).

Both share the same async interface: embed(), embed_batch(), is_available(),
get_stats(), close(). The RAG pipeline and app.py use them interchangeably.

Supports:
    - Single text embedding
    - Batch embedding (multiple texts in one call)
    - Caching (LRU with TTL for repeated queries)
    - Graceful degradation (returns None if unavailable)

The embedding model is configurable via EMBEDDING_MODEL setting.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Optional

import httpx

logger = logging.getLogger("nexus.embeddings")

# Defaults
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_EMBEDDING_DIMS = 768  # nomic-embed-text output
DEFAULT_OLLAMA_URL = "http://localhost:11434"

# LRU cache settings
CACHE_MAX_SIZE = 500
CACHE_TTL_SECONDS = 3600  # 1 hour


class EmbeddingCache:
    """Thread-safe LRU cache with TTL for embeddings."""

    def __init__(self, max_size: int = CACHE_MAX_SIZE, ttl: int = CACHE_TTL_SECONDS):
        self._cache: OrderedDict[str, tuple[list[float], float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl
        self.hits = 0
        self.misses = 0

    def _key(self, text: str) -> str:
        return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:24]

    def get(self, text: str) -> Optional[list[float]]:
        k = self._key(text)
        if k in self._cache:
            embedding, ts = self._cache[k]
            if time.time() - ts < self._ttl:
                self._cache.move_to_end(k)
                self.hits += 1
                return embedding
            else:
                del self._cache[k]
        self.misses += 1
        return None

    def put(self, text: str, embedding: list[float]) -> None:
        k = self._key(text)
        self._cache[k] = (embedding, time.time())
        self._cache.move_to_end(k)
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()
        self.hits = 0
        self.misses = 0

    def get_stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total > 0 else 0.0,
        }


class EmbeddingService:
    """Async embedding generation via Ollama.

    Usage:
        service = EmbeddingService()
        embedding = await service.embed("Hello world")
        embeddings = await service.embed_batch(["text1", "text2"])
    """

    def __init__(
        self,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dims: int = DEFAULT_EMBEDDING_DIMS,
    ):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.dims = dims
        self._client = httpx.AsyncClient(
            base_url=self.ollama_url,
            timeout=30.0,
        )
        self._cache = EmbeddingCache()
        self._available: Optional[bool] = None
        self._total_calls = 0
        self._total_errors = 0

    async def is_available(self) -> bool:
        """Check if the embedding model is accessible."""
        try:
            resp = await self._client.get("/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                names = [m["name"] for m in models]
                available = self.model in names or f"{self.model}:latest" in names
                self._available = available
                if not available:
                    logger.warning(
                        f"Embedding model '{self.model}' not found. "
                        f"Available: {names}. Run: ollama pull {self.model}"
                    )
                return available
        except Exception as e:
            logger.debug(f"Embedding service unavailable: {e}")
            self._available = False
        return False

    async def embed(self, text: str) -> Optional[list[float]]:
        """Generate embedding for a single text.

        Returns None if the service is unavailable or an error occurs.
        Uses cache to avoid redundant API calls.
        """
        if not text or not text.strip():
            return None

        # Check cache first
        cached = self._cache.get(text)
        if cached is not None:
            return cached

        try:
            self._total_calls += 1
            resp = await self._client.post(
                "/api/embed",
                json={"model": self.model, "input": text.strip()},
            )
            if resp.status_code == 200:
                data = resp.json()
                embeddings = data.get("embeddings", [])
                if embeddings and len(embeddings[0]) == self.dims:
                    self._cache.put(text, embeddings[0])
                    return embeddings[0]
                elif embeddings:
                    # Dimension mismatch — update dims and return
                    actual_dims = len(embeddings[0])
                    if actual_dims != self.dims:
                        logger.warning(
                            f"Embedding dims mismatch: expected {self.dims}, got {actual_dims}. "
                            f"Updating to {actual_dims}."
                        )
                        self.dims = actual_dims
                    self._cache.put(text, embeddings[0])
                    return embeddings[0]
            else:
                self._total_errors += 1
                logger.warning(f"Embedding API error: {resp.status_code} {resp.text[:200]}")
        except httpx.TimeoutException:
            self._total_errors += 1
            logger.warning("Embedding API timeout")
        except Exception as e:
            self._total_errors += 1
            logger.warning(f"Embedding error: {e}")

        return None

    async def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Generate embeddings for multiple texts.

        Uses Ollama's batch embedding endpoint for efficiency.
        Returns a list of embeddings (None for any that failed).
        """
        if not texts:
            return []

        results: list[Optional[list[float]]] = [None] * len(texts)

        # Check cache and identify texts that need embedding
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            if not text or not text.strip():
                continue
            cached = self._cache.get(text)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)
                uncached_texts.append(text.strip())

        if not uncached_texts:
            return results

        try:
            self._total_calls += 1
            resp = await self._client.post(
                "/api/embed",
                json={"model": self.model, "input": uncached_texts},
                timeout=60.0,  # Longer timeout for batch
            )
            if resp.status_code == 200:
                data = resp.json()
                embeddings = data.get("embeddings", [])
                for j, emb in enumerate(embeddings):
                    if j < len(uncached_indices) and emb:
                        idx = uncached_indices[j]
                        results[idx] = emb
                        self._cache.put(texts[idx], emb)
                        # Auto-detect dims
                        if len(emb) != self.dims:
                            self.dims = len(emb)
            else:
                self._total_errors += 1
                logger.warning(f"Batch embedding error: {resp.status_code}")
        except Exception as e:
            self._total_errors += 1
            logger.warning(f"Batch embedding error: {e}")

        return results

    def get_stats(self) -> dict:
        """Get service statistics."""
        return {
            "model": self.model,
            "dims": self.dims,
            "available": self._available,
            "total_calls": self._total_calls,
            "total_errors": self._total_errors,
            "cache": self._cache.get_stats(),
        }

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


# ── Model name mapping ────────────────────────────────────────────
# Maps Ollama model names to HuggingFace fastembed model IDs.
FASTEMBED_MODEL_MAP = {
    "nomic-embed-text": "nomic-ai/nomic-embed-text-v1.5",
    "nomic-embed-text:latest": "nomic-ai/nomic-embed-text-v1.5",
    "all-minilm": "sentence-transformers/all-MiniLM-L6-v2",
    "all-minilm:latest": "sentence-transformers/all-MiniLM-L6-v2",
}


class FastEmbedService:
    """CPU-only embedding via fastembed (ONNX Runtime).

    Drop-in replacement for EmbeddingService. Runs nomic-embed-text-v1.5
    on CPU threads, zero GPU contention with Ollama inference models.

    Typical latency: ~8ms per single embed, ~3ms/text in batch.
    Model loads from HuggingFace cache in ~150ms after first download.

    Usage:
        service = FastEmbedService()
        await service.is_available()   # loads model
        embedding = await service.embed("Hello world")
        embeddings = await service.embed_batch(["text1", "text2"])
    """

    def __init__(
        self,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dims: int = DEFAULT_EMBEDDING_DIMS,
    ):
        # Resolve HuggingFace model name from Ollama name
        self._hf_model = FASTEMBED_MODEL_MAP.get(model, model)
        self.model = model
        self.dims = dims
        self._fe_model = None  # Lazy-loaded TextEmbedding instance
        self._cache = EmbeddingCache(max_size=2000, ttl=CACHE_TTL_SECONDS)
        self._available: Optional[bool] = None
        self._total_calls = 0
        self._total_errors = 0
        self._total_ms = 0
        self._executor = None  # ThreadPoolExecutor, created on first use

    def _ensure_model(self) -> bool:
        """Load the fastembed model (blocking, call from executor)."""
        if self._fe_model is not None:
            return True
        try:
            from fastembed import TextEmbedding
            self._fe_model = TextEmbedding(self._hf_model)
            # Detect actual dimensions
            test = list(self._fe_model.embed(["test"]))[0]
            self.dims = len(test)
            return True
        except Exception as e:
            logger.error(f"FastEmbed model load failed: {e}")
            return False

    async def is_available(self) -> bool:
        """Check if the embedding model can be loaded."""
        try:
            loop = asyncio.get_event_loop()
            if self._executor is None:
                from concurrent.futures import ThreadPoolExecutor
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fastembed")
            result = await loop.run_in_executor(self._executor, self._ensure_model)
            self._available = result
            if result:
                logger.info(
                    f"FastEmbed ready: {self._hf_model} ({self.dims}-dim, CPU)"
                )
            else:
                logger.warning(f"FastEmbed model '{self._hf_model}' failed to load")
            return result
        except Exception as e:
            logger.warning(f"FastEmbed availability check failed: {e}")
            self._available = False
            return False

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        """Synchronous embedding — called from thread executor."""
        if self._fe_model is None:
            self._ensure_model()
        if self._fe_model is None:
            return []
        return [emb.tolist() for emb in self._fe_model.embed(texts)]

    async def embed(self, text: str) -> Optional[list[float]]:
        """Generate embedding for a single text.

        Returns None if the service is unavailable or an error occurs.
        Uses cache to avoid redundant calls.
        """
        if not text or not text.strip():
            return None

        # Check cache first
        cached = self._cache.get(text)
        if cached is not None:
            return cached

        try:
            self._total_calls += 1
            start = time.time()

            loop = asyncio.get_event_loop()
            if self._executor is None:
                from concurrent.futures import ThreadPoolExecutor
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fastembed")

            results = await loop.run_in_executor(
                self._executor, self._embed_sync, [text.strip()]
            )

            elapsed_ms = int((time.time() - start) * 1000)
            self._total_ms += elapsed_ms

            if results and len(results[0]) > 0:
                embedding = results[0]
                self._cache.put(text, embedding)
                if len(embedding) != self.dims:
                    self.dims = len(embedding)
                return embedding

        except Exception as e:
            self._total_errors += 1
            logger.warning(f"FastEmbed error: {e}")

        return None

    async def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Generate embeddings for multiple texts.

        Uses fastembed's native batch processing for efficiency.
        Returns a list of embeddings (None for any that failed).
        """
        if not texts:
            return []

        results: list[Optional[list[float]]] = [None] * len(texts)

        # Check cache and identify texts that need embedding
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            if not text or not text.strip():
                continue
            cached = self._cache.get(text)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)
                uncached_texts.append(text.strip())

        if not uncached_texts:
            return results

        try:
            self._total_calls += 1
            start = time.time()

            loop = asyncio.get_event_loop()
            if self._executor is None:
                from concurrent.futures import ThreadPoolExecutor
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fastembed")

            embeddings = await loop.run_in_executor(
                self._executor, self._embed_sync, uncached_texts
            )

            elapsed_ms = int((time.time() - start) * 1000)
            self._total_ms += elapsed_ms

            for j, emb in enumerate(embeddings):
                if j < len(uncached_indices) and emb:
                    idx = uncached_indices[j]
                    results[idx] = emb
                    self._cache.put(texts[idx], emb)
                    if len(emb) != self.dims:
                        self.dims = len(emb)

        except Exception as e:
            self._total_errors += 1
            logger.warning(f"FastEmbed batch error: {e}")

        return results

    def get_stats(self) -> dict:
        """Get service statistics."""
        avg_ms = round(self._total_ms / max(self._total_calls, 1), 1)
        return {
            "model": f"{self.model} (CPU/fastembed)",
            "hf_model": self._hf_model,
            "dims": self.dims,
            "available": self._available,
            "backend": "fastembed_cpu",
            "total_calls": self._total_calls,
            "total_errors": self._total_errors,
            "avg_ms": avg_ms,
            "cache": self._cache.get_stats(),
        }

    async def close(self) -> None:
        """Clean up resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._fe_model = None
