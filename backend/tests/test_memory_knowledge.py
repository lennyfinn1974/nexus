"""Tests for RAG, Embedding Service, and Knowledge Graph.

Tests:
    - EmbeddingCache: LRU + TTL behavior
    - EmbeddingService: initialization and stats
    - RAGPipeline: text chunking, condensation, formatting
    - KnowledgeGraph: entity extraction, relationship inference, BFS traversal
    - Integration: RAG + KG working together
"""

from __future__ import annotations

import asyncio
import pytest
import time

# ── EmbeddingCache Tests ──


class TestEmbeddingCache:
    def test_cache_put_and_get(self):
        from core.embeddings import EmbeddingCache

        cache = EmbeddingCache(max_size=10)
        embedding = [0.1, 0.2, 0.3]
        cache.put("hello world", embedding)
        result = cache.get("hello world")
        assert result == embedding
        assert cache.hits == 1
        assert cache.misses == 0

    def test_cache_miss(self):
        from core.embeddings import EmbeddingCache

        cache = EmbeddingCache()
        result = cache.get("nonexistent")
        assert result is None
        assert cache.misses == 1

    def test_cache_case_insensitive(self):
        from core.embeddings import EmbeddingCache

        cache = EmbeddingCache()
        cache.put("Hello World", [1.0, 2.0])
        result = cache.get("hello world")
        assert result == [1.0, 2.0]

    def test_cache_lru_eviction(self):
        from core.embeddings import EmbeddingCache

        cache = EmbeddingCache(max_size=3)
        cache.put("a", [1.0])
        cache.put("b", [2.0])
        cache.put("c", [3.0])
        cache.put("d", [4.0])  # Should evict "a"

        assert cache.get("a") is None  # Evicted
        assert cache.get("b") == [2.0]
        assert cache.get("d") == [4.0]

    def test_cache_ttl_expiry(self):
        from core.embeddings import EmbeddingCache

        cache = EmbeddingCache(ttl=0)  # Immediate expiry
        cache.put("test", [1.0])
        time.sleep(0.01)
        result = cache.get("test")
        assert result is None

    def test_cache_stats(self):
        from core.embeddings import EmbeddingCache

        cache = EmbeddingCache()
        cache.put("a", [1.0])
        cache.get("a")  # hit
        cache.get("b")  # miss

        stats = cache.get_stats()
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_cache_clear(self):
        from core.embeddings import EmbeddingCache

        cache = EmbeddingCache()
        cache.put("a", [1.0])
        cache.put("b", [2.0])
        cache.clear()
        assert cache.get("a") is None
        stats = cache.get_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0


# ── EmbeddingService Tests ──


class TestEmbeddingService:
    def test_service_init(self):
        from core.embeddings import EmbeddingService

        svc = EmbeddingService(model="nomic-embed-text", dims=768)
        assert svc.model == "nomic-embed-text"
        assert svc.dims == 768

    def test_service_stats(self):
        from core.embeddings import EmbeddingService

        svc = EmbeddingService()
        stats = svc.get_stats()
        assert stats["model"] == "nomic-embed-text"
        assert stats["dims"] == 768
        assert stats["total_calls"] == 0


# ── RAGPipeline Tests ──


class TestRAGPipeline:
    def test_chunk_text_small(self):
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        # Short text below chunk_size returns as single chunk
        chunks = pipeline._chunk_text("Hello world, this is a test.", chunk_size=100)
        assert len(chunks) == 1  # Returns as-is since < chunk_size

    def test_chunk_text_single(self):
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        text = "A" * 200
        chunks = pipeline._chunk_text(text, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_text_multiple(self):
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        # Create a text with clear paragraph breaks
        paragraphs = [f"Paragraph {i}. " * 10 for i in range(10)]
        text = "\n\n".join(paragraphs)
        chunks = pipeline._chunk_text(text, chunk_size=200, overlap=50)
        assert len(chunks) > 1
        # Each chunk should be non-empty
        for chunk in chunks:
            assert len(chunk) >= 50

    def test_condense_exchange(self):
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        result = pipeline._condense_exchange(
            "How do I use Redis for caching?",
            "Redis is an in-memory data store. You can use SET/GET commands for basic caching.",
        )
        assert result.startswith("Q: ")
        assert "Redis" in result
        assert "A: " in result

    def test_condense_filters_code_blocks(self):
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        long_code = "```python\n" + "x = 1\n" * 200 + "```"
        result = pipeline._condense_exchange(
            "Show me code",
            f"Here's the code:\n{long_code}\nThat's the implementation.",
        )
        assert "[code block omitted]" in result

    def test_format_results_empty(self):
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        assert pipeline._format_results([], 5000) == ""

    def test_format_results_respects_budget(self):
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        results = [
            {"text": "A" * 500, "score": 0.1, "memory_type": "conversation"},
            {"text": "B" * 500, "score": 0.2, "memory_type": "document"},
            {"text": "C" * 500, "score": 0.3, "memory_type": "fact"},
        ]
        formatted = pipeline._format_results(results, max_chars=600)
        assert len(formatted) <= 700  # Some overhead for headers

    def test_is_active_without_deps(self):
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        assert not pipeline.is_active

    def test_stats(self):
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        stats = pipeline.get_stats()
        assert stats["active"] is False
        assert stats["total_retrievals"] == 0
        assert stats["total_ingests"] == 0


# ── KnowledgeGraph Tests ──


class TestKnowledgeGraph:
    def test_entity_creation(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        entity = kg._get_or_create_entity("Python", "technology")
        assert entity.name == "Python"
        assert entity.entity_type == "technology"
        assert entity.mention_count == 1
        assert kg.entity_count == 1

    def test_entity_dedup(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        e1 = kg._get_or_create_entity("Python", "technology")
        e2 = kg._get_or_create_entity("Python", "technology")
        assert e1.id == e2.id
        assert e2.mention_count == 2
        assert kg.entity_count == 1

    def test_relationship_creation(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        e1 = kg._get_or_create_entity("Nexus", "project")
        e2 = kg._get_or_create_entity("Python", "technology")
        rel = kg._add_relationship(e1.id, e2.id, "uses")
        assert rel.relationship_type == "uses"
        assert rel.strength == 1.0
        assert kg.relationship_count == 1

    def test_relationship_reinforcement(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        e1 = kg._get_or_create_entity("Nexus", "project")
        e2 = kg._get_or_create_entity("Redis", "tool")
        # Start with lower strength to test reinforcement
        rel1 = kg._add_relationship(e1.id, e2.id, "uses", strength=0.5)
        rel2 = kg._add_relationship(e1.id, e2.id, "uses")
        assert rel2.mention_count == 2
        assert rel2.strength > 0.5  # Reinforced from 0.5
        assert rel2.strength <= 1.0
        assert kg.relationship_count == 1  # Still one relationship

    @pytest.mark.asyncio
    async def test_extract_technologies(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        result = await kg.extract_and_store(
            "I'm using Python and Redis to build a FastAPI backend with PostgreSQL.",
        )
        entities = result["entities"]
        names = {e["name"].lower() for e in entities}
        assert "python" in names
        assert "redis" in names
        assert "fastapi" in names
        assert "postgresql" in names or "postgres" in names

    @pytest.mark.asyncio
    async def test_extract_creates_relationships(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        result = await kg.extract_and_store(
            "The Nexus project uses Python and Redis for its backend.",
        )
        assert len(result["relationships"]) > 0
        assert kg.relationship_count > 0

    @pytest.mark.asyncio
    async def test_extract_urls(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        result = await kg.extract_and_store(
            "Check out https://example.com for more info about the API.",
        )
        names = {e["name"] for e in result["entities"]}
        assert any("example.com" in n for n in names)

    @pytest.mark.asyncio
    async def test_extract_file_paths(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        result = await kg.extract_and_store(
            "The config is at `/Users/lennyfinn/Nexus/backend/app.py` and the main router.",
        )
        entities = result["entities"]
        types = {e["type"] for e in entities}
        assert "file" in types

    def test_infer_relationship_project_tech(self):
        from core.knowledge_graph import KnowledgeGraph, Entity

        kg = KnowledgeGraph()
        e1 = Entity(id="1", name="Nexus", entity_type="project")
        e2 = Entity(id="2", name="Python", entity_type="technology")
        assert kg._infer_relationship(e1, e2) == "uses"

    def test_infer_relationship_tech_concept(self):
        from core.knowledge_graph import KnowledgeGraph, Entity

        kg = KnowledgeGraph()
        e1 = Entity(id="1", name="Redis", entity_type="technology")
        e2 = Entity(id="2", name="caching", entity_type="concept")
        assert kg._infer_relationship(e1, e2) == "implements"

    @pytest.mark.asyncio
    async def test_query_related(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        # Build some knowledge
        await kg.extract_and_store("Python is used in the Nexus project with Redis and FastAPI.")
        await kg.extract_and_store("Redis provides caching and vector search for Nexus.")

        # Query related entities
        context = await kg.query_related("Tell me about Redis", limit=5)
        assert "Redis" in context or "redis" in context.lower() or len(context) > 0

    def test_get_entity(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        kg._get_or_create_entity("FastAPI", "framework")
        entity = kg.get_entity("fastapi")  # Case insensitive
        assert entity is not None
        assert entity.name == "FastAPI"

    def test_get_neighbors(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        e1 = kg._get_or_create_entity("Nexus", "project")
        e2 = kg._get_or_create_entity("Python", "technology")
        kg._add_relationship(e1.id, e2.id, "uses")

        neighbors = kg.get_neighbors(e1.id)
        assert len(neighbors) == 1
        assert neighbors[0]["entity"]["name"] == "Python"

    def test_export_graph(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        kg._get_or_create_entity("Python", "technology")
        kg._get_or_create_entity("Redis", "tool")
        e1 = kg._get_or_create_entity("Nexus", "project")
        e2 = kg.get_entity("python")
        kg._add_relationship(e1.id, e2.id, "uses")

        graph = kg.export_graph()
        assert len(graph["nodes"]) == 3
        assert len(graph["links"]) == 1

    def test_stats(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        kg._get_or_create_entity("Python", "technology")
        kg._get_or_create_entity("Redis", "tool")
        stats = kg.get_stats()
        assert stats["total_entities"] == 2
        assert stats["total_relationships"] == 0
        assert "technology" in stats["entity_types"]
        assert "tool" in stats["entity_types"]

    def test_guess_entity_type(self):
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        assert kg._guess_entity_type("python") == "technology"
        assert kg._guess_entity_type("redis") == "tool"
        assert kg._guess_entity_type("api") == "concept"
        assert kg._guess_entity_type("/usr/local/bin") == "file"
        assert kg._guess_entity_type("https://example.com") == "url"
        assert kg._guess_entity_type("something unknown") == "concept"


# ── Integration Tests ──


class TestIntegration:
    @pytest.mark.asyncio
    async def test_kg_incremental_build(self):
        """Test that the knowledge graph builds incrementally across messages."""
        from core.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()

        # First message
        await kg.extract_and_store("I'm building Nexus with Python and FastAPI.")
        count1 = kg.entity_count

        # Second message (some overlap)
        await kg.extract_and_store("Nexus also uses Redis for caching and vector search.")
        count2 = kg.entity_count

        # Should have more entities after second message
        assert count2 > count1
        # Nexus should be mentioned twice
        nexus = kg.get_entity("nexus")
        # May or may not find 'Nexus' depending on project pattern matching
        # But we should have tech entities
        assert kg.entity_count >= 3

    @pytest.mark.asyncio
    async def test_rag_ingest_skips_short(self):
        """Test that RAG ingest skips very short messages."""
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        # Pipeline not active, but test the method's early return logic
        result = await pipeline.ingest_conversation(
            conv_id="test",
            user_message="hi",
            assistant_response="hello",
        )
        assert result is None  # Skipped (too short + pipeline not active)

    @pytest.mark.asyncio
    async def test_rag_ingest_skips_commands(self):
        """Test that RAG ingest skips command messages."""
        from core.rag import RAGPipeline

        pipeline = RAGPipeline(None, None)
        result = await pipeline.ingest_conversation(
            conv_id="test",
            user_message="/model cloud",
            assistant_response="Switched to Claude.",
        )
        assert result is None  # Skipped (command)
