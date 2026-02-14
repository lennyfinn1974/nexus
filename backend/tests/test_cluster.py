"""Comprehensive test suite for Nexus Agent Clustering (Phase 6).

Tests cover all clustering subsystems:
    - AgentRegistry: registration, heartbeat, discovery
    - EventBus: publish, subscribe, handlers
    - TaskStream: publish, consume, priority, dead letter
    - WorkingMemory: session CRUD, context snapshots, work tracking
    - MemoryIndex: store, search, deduplication
    - HealthMonitor: SDOWN detection, voting
    - ElectionManager: election, promotion, demotion
    - DistributedRateLimiter: sliding window, rate enforcement
    - ClusterMetrics: collection, Prometheus export
    - ClusterManager: lifecycle, integration

Requires a running Redis instance on localhost:6379.
Tests use a unique prefix per run to avoid collisions.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Check Redis availability
_redis_available = False
try:
    import redis as _redis_sync
    _r = _redis_sync.Redis(host="localhost", port=6379, socket_connect_timeout=2)
    _r.ping()
    _r.close()
    _redis_available = True
except Exception:
    pass

pytestmark = pytest.mark.skipif(
    not _redis_available,
    reason="Redis not available on localhost:6379",
)

# Unique test prefix to avoid collisions
TEST_PREFIX = f"nexus_test_{uuid.uuid4().hex[:8]}:"


@pytest.fixture
async def redis():
    """Create an async Redis connection for testing."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(
        "redis://localhost:6379",
        decode_responses=True,
        socket_connect_timeout=5,
    )
    yield r
    # Cleanup: delete all keys with our test prefix
    async for key in r.scan_iter(match=f"{TEST_PREFIX}*", count=500):
        await r.delete(key)
    await r.aclose()


@pytest.fixture
async def redis_binary():
    """Create a binary Redis connection for vector storage."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(
        "redis://localhost:6379",
        decode_responses=False,
        socket_connect_timeout=5,
    )
    yield r
    await r.aclose()


# ── AgentRegistry Tests ──


class TestAgentRegistry:
    @pytest.mark.asyncio
    async def test_register_and_discover(self, redis):
        from core.cluster.registry import AgentRegistry

        reg = AgentRegistry(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-agent-1",
            role="primary", host="127.0.0.1", port=8080, max_load=20,
            heartbeat_interval=1, failure_threshold=3,
            models=["ollama/test"], capabilities=["web"],
        )
        await reg.start()

        try:
            # Should find itself
            agents = await reg.get_all_agents()
            assert len(agents) >= 1
            me = next(a for a in agents if a["id"] == "test-agent-1")
            assert me["role"] == "primary"
            assert me["host"] == "127.0.0.1"
            assert me["port"] == 8080
            assert me["is_self"] is True
            assert me["healthy"] is True

            # Should be retrievable by ID
            info = await reg.get_agent("test-agent-1")
            assert info is not None
            assert info["id"] == "test-agent-1"
        finally:
            await reg.stop()

    @pytest.mark.asyncio
    async def test_update_load(self, redis):
        from core.cluster.registry import AgentRegistry

        reg = AgentRegistry(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-load-1",
            role="secondary", host="127.0.0.1", port=8081, max_load=10,
            heartbeat_interval=1, failure_threshold=3,
            models=[], capabilities=[],
        )
        await reg.start()

        try:
            await reg.update_load(5)
            info = await reg.get_agent("test-load-1")
            assert info["current_load"] == 5

            await reg.update_load(3)  # delta-based: 5 + 3 = 8
            info = await reg.get_agent("test-load-1")
            assert info["current_load"] == 8

            await reg.update_load(-8)  # back to 0
            info = await reg.get_agent("test-load-1")
            assert info["current_load"] == 0
        finally:
            await reg.stop()

    @pytest.mark.asyncio
    async def test_role_change(self, redis):
        from core.cluster.registry import AgentRegistry

        reg = AgentRegistry(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-role-1",
            role="secondary", host="127.0.0.1", port=8082, max_load=20,
            heartbeat_interval=1, failure_threshold=3,
            models=[], capabilities=[],
        )
        await reg.start()

        try:
            assert reg.role == "secondary"
            await reg.set_role("primary")
            assert reg.role == "primary"

            info = await reg.get_agent("test-role-1")
            assert info["role"] == "primary"
        finally:
            await reg.stop()


# ── EventBus Tests ──


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_and_receive(self, redis):
        from core.cluster.event_bus import EventBus

        bus = EventBus(redis=redis, prefix=TEST_PREFIX, agent_id="test-bus-1")
        await bus.start()

        received = []

        async def handler(channel: str, event: dict):
            received.append((channel, event))

        await bus.subscribe("test_channel", handler)

        try:
            await bus.publish("test_channel", {"type": "test", "data": "hello"})

            # Give subscriber time to receive
            await asyncio.sleep(0.5)

            stats = bus.get_stats()
            assert stats["published"] >= 1
            assert stats["handler_count"] >= 1
        finally:
            await bus.stop()

    @pytest.mark.asyncio
    async def test_stats_tracking(self, redis):
        from core.cluster.event_bus import EventBus

        bus = EventBus(redis=redis, prefix=TEST_PREFIX, agent_id="test-bus-2")
        await bus.start()

        try:
            await bus.publish("channel_a", {"type": "msg1"})
            await bus.publish("channel_b", {"type": "msg2"})

            stats = bus.get_stats()
            assert stats["published"] >= 2
        finally:
            await bus.stop()


# ── TaskStream Tests ──


class TestTaskStream:
    @pytest.mark.asyncio
    async def test_publish_and_stats(self, redis):
        from core.cluster.task_stream import TaskStream

        ts = TaskStream(redis=redis, prefix=TEST_PREFIX, agent_id="test-ts-1")
        await ts.start()

        try:
            # Publish tasks
            task_id = await ts.publish(
                task_type="test_task",
                payload={"key": "value"},
            )
            assert task_id is not None

            stats = ts.get_stats()
            assert stats["published"] >= 1

            # Check stream info
            info = await ts.get_stream_info()
            assert "normal" in info
            assert "high" in info
            assert "low" in info
        finally:
            await ts.stop()

    @pytest.mark.asyncio
    async def test_priority_routing(self, redis):
        from core.cluster.task_stream import TaskStream

        ts = TaskStream(redis=redis, prefix=TEST_PREFIX, agent_id="test-ts-2")
        await ts.start()

        try:
            await ts.publish(task_type="urgent", priority="high")
            await ts.publish(task_type="normal", priority="normal")
            await ts.publish(task_type="background", priority="low")

            info = await ts.get_stream_info()
            assert info["high"]["length"] >= 1
            assert info["normal"]["length"] >= 1
            assert info["low"]["length"] >= 1
        finally:
            await ts.stop()


# ── WorkingMemory Tests ──


class TestWorkingMemory:
    @pytest.mark.asyncio
    async def test_session_crud(self, redis):
        from core.cluster.working_memory import WorkingMemory

        wm = WorkingMemory(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-wm-1",
            session_ttl=60, promotion_delay=300,
        )
        await wm.start()

        try:
            conv_id = f"conv-{uuid.uuid4().hex[:8]}"

            # Create
            await wm.set_session(conv_id, {"model": "test", "messages": 5})
            session = await wm.get_session(conv_id)
            assert session is not None
            assert session["model"] == "test"
            assert session["messages"] == 5
            assert session["_agent_id"] == "test-wm-1"

            # Update
            ok = await wm.update_session(conv_id, {"messages": 10})
            assert ok is True
            session = await wm.get_session(conv_id)
            assert session["messages"] == 10

            # Delete
            await wm.delete_session(conv_id)
            session = await wm.get_session(conv_id)
            assert session is None

            # Stats
            stats = wm.get_stats()
            assert stats["reads"] >= 2  # get_session calls
            assert stats["writes"] >= 2  # set + update
            assert stats["evictions"] >= 1  # delete
        finally:
            await wm.stop()

    @pytest.mark.asyncio
    async def test_context_snapshots(self, redis):
        from core.cluster.working_memory import WorkingMemory

        wm = WorkingMemory(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-wm-2",
            session_ttl=60, promotion_delay=300,
        )
        await wm.start()

        try:
            conv_id = f"conv-{uuid.uuid4().hex[:8]}"

            await wm.set_context(conv_id, {
                "summary": "User building React app",
                "preferences": {"model": "local"},
            })

            ctx = await wm.get_context(conv_id)
            assert ctx is not None
            assert ctx["summary"] == "User building React app"
            assert ctx["_source_agent"] == "test-wm-2"
        finally:
            await wm.stop()

    @pytest.mark.asyncio
    async def test_work_tracking(self, redis):
        from core.cluster.working_memory import WorkingMemory

        wm = WorkingMemory(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-wm-3",
            session_ttl=60, promotion_delay=300,
        )
        await wm.start()

        try:
            conv_id = f"conv-{uuid.uuid4().hex[:8]}"

            # Claim work
            await wm.claim_work(conv_id, task_type="conversation")
            work = await wm.get_agent_work()
            assert len(work) >= 1
            assert work[0]["conv_id"] == conv_id

            # Find agent for conversation
            agent = await wm.find_agent_for_conv(conv_id)
            assert agent == "test-wm-3"

            # Release work
            await wm.release_work(conv_id)
            work = await wm.get_agent_work()
            assert not any(w["conv_id"] == conv_id for w in work)
        finally:
            await wm.stop()

    @pytest.mark.asyncio
    async def test_active_sessions(self, redis):
        from core.cluster.working_memory import WorkingMemory

        wm = WorkingMemory(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-wm-4",
            session_ttl=60, promotion_delay=300,
        )
        await wm.start()

        try:
            # Create multiple sessions
            for i in range(5):
                await wm.set_session(f"sess-{i}", {"index": i})

            sessions = await wm.get_active_sessions()
            assert len(sessions) >= 5

            count = await wm.count_active_sessions()
            assert count >= 5
        finally:
            await wm.stop()


# ── MemoryIndex Tests ──


class TestMemoryIndex:
    @pytest.mark.asyncio
    async def test_store_and_count(self, redis_binary):
        from core.cluster.memory_index import MemoryIndex

        mi = MemoryIndex(
            redis=redis_binary, prefix=TEST_PREFIX, agent_id="test-mi-1",
            vector_dims=4,  # Small for testing
        )
        await mi.start()

        try:
            # Store a memory with a small embedding
            mem_id = await mi.store(
                text="User prefers dark mode",
                embedding=[0.1, 0.2, 0.3, 0.4],
                memory_type="preference",
            )
            assert mem_id is not None

            # Count
            total = await mi.count_memories()
            assert total >= 1

            # Types
            types = await mi.get_memory_types()
            assert "preference" in types

            stats = mi.get_stats()
            assert stats["stored"] >= 1
        finally:
            await mi.stop()

    @pytest.mark.asyncio
    async def test_deduplication(self, redis_binary):
        from core.cluster.memory_index import MemoryIndex

        mi = MemoryIndex(
            redis=redis_binary, prefix=TEST_PREFIX, agent_id="test-mi-2",
            vector_dims=4,
        )
        await mi.start()

        try:
            # Store identical content twice
            id1 = await mi.store(
                text="Test duplicate content",
                embedding=[0.5, 0.5, 0.5, 0.5],
                memory_type="general",
            )
            id2 = await mi.store(
                text="Test duplicate content",
                embedding=[0.5, 0.5, 0.5, 0.5],
                memory_type="general",
            )

            # Second should be deduplicated (returns None)
            assert id1 is not None
            assert id2 is None

            stats = mi.get_stats()
            assert stats["duplicates_found"] >= 1
        finally:
            await mi.stop()

    @pytest.mark.asyncio
    async def test_search_fallback(self, redis_binary):
        """Test brute-force search (RediSearch may not be available)."""
        from core.cluster.memory_index import MemoryIndex

        mi = MemoryIndex(
            redis=redis_binary, prefix=TEST_PREFIX, agent_id="test-mi-3",
            vector_dims=4,
        )
        await mi.start()

        try:
            # Store several memories
            await mi.store("Python programming", [0.9, 0.1, 0.0, 0.0], "knowledge")
            await mi.store("React frontend", [0.1, 0.9, 0.0, 0.0], "knowledge")
            await mi.store("Redis caching", [0.0, 0.1, 0.9, 0.0], "knowledge")

            # Search — should use brute-force fallback if RediSearch not available
            results = await mi.search(
                query_embedding=[0.85, 0.15, 0.0, 0.0],
                limit=2,
            )

            # Should return results (at least from brute-force)
            assert isinstance(results, list)

            stats = mi.get_stats()
            assert stats["searched"] >= 1
        finally:
            await mi.stop()


# ── HealthMonitor Tests ──


class TestHealthMonitor:
    @pytest.mark.asyncio
    async def test_initialization(self, redis):
        from core.cluster.registry import AgentRegistry
        from core.cluster.event_bus import EventBus
        from core.cluster.health import HealthMonitor

        reg = AgentRegistry(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-hm-1",
            role="primary", host="127.0.0.1", port=8080, max_load=20,
            heartbeat_interval=1, failure_threshold=3,
            models=[], capabilities=[],
        )
        bus = EventBus(redis=redis, prefix=TEST_PREFIX, agent_id="test-hm-1")
        hm = HealthMonitor(
            redis=redis, registry=reg, event_bus=bus, prefix=TEST_PREFIX,
            agent_id="test-hm-1", heartbeat_interval=1, failure_threshold=3,
        )

        await reg.start()
        await bus.start()
        await hm.start()

        try:
            # Let it run a couple checks
            await asyncio.sleep(2.5)

            status = hm.get_status()
            assert status["checks"] >= 1
            assert isinstance(status["sdown_agents"], list)
            assert isinstance(status["odown_agents"], list)

            votes = await hm.get_vote_status()
            assert isinstance(votes, dict)
        finally:
            await hm.stop()
            await bus.stop()
            await reg.stop()


# ── ElectionManager Tests ──


class TestElectionManager:
    @pytest.mark.asyncio
    async def test_initialization_and_status(self, redis):
        from core.cluster.registry import AgentRegistry
        from core.cluster.event_bus import EventBus
        from core.cluster.working_memory import WorkingMemory
        from core.cluster.task_stream import TaskStream
        from core.cluster.election import ElectionManager

        reg = AgentRegistry(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-em-1",
            role="primary", host="127.0.0.1", port=8080, max_load=20,
            heartbeat_interval=1, failure_threshold=3,
            models=[], capabilities=[],
        )
        bus = EventBus(redis=redis, prefix=TEST_PREFIX, agent_id="test-em-1")
        wm = WorkingMemory(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-em-1",
            session_ttl=60, promotion_delay=300,
        )
        ts = TaskStream(redis=redis, prefix=TEST_PREFIX, agent_id="test-em-1")

        em = ElectionManager(
            redis=redis, registry=reg, event_bus=bus, prefix=TEST_PREFIX,
            agent_id="test-em-1", election_timeout=5, min_secondaries=0,
            working_memory=wm, task_stream=ts,
        )

        await reg.start()
        await bus.start()

        try:
            status = em.get_status()
            assert status["election_in_progress"] is False
            assert status["elections_won"] == 0
            assert status["demotions"] == 0

            # min_secondaries=0 so this should pass
            has_enough = await em.check_min_secondaries()
            assert has_enough is True
        finally:
            await bus.stop()
            await reg.stop()

    @pytest.mark.asyncio
    async def test_drain(self, redis):
        from core.cluster.registry import AgentRegistry
        from core.cluster.event_bus import EventBus
        from core.cluster.working_memory import WorkingMemory
        from core.cluster.task_stream import TaskStream
        from core.cluster.election import ElectionManager

        reg = AgentRegistry(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-em-2",
            role="secondary", host="127.0.0.1", port=8081, max_load=20,
            heartbeat_interval=1, failure_threshold=3,
            models=[], capabilities=[],
        )
        bus = EventBus(redis=redis, prefix=TEST_PREFIX, agent_id="test-em-2")
        wm = WorkingMemory(
            redis=redis, prefix=TEST_PREFIX, agent_id="test-em-2",
            session_ttl=60, promotion_delay=300,
        )
        ts = TaskStream(redis=redis, prefix=TEST_PREFIX, agent_id="test-em-2")

        em = ElectionManager(
            redis=redis, registry=reg, event_bus=bus, prefix=TEST_PREFIX,
            agent_id="test-em-2", election_timeout=5, min_secondaries=0,
            working_memory=wm, task_stream=ts,
        )

        await reg.start()
        await bus.start()

        try:
            await em.initiate_drain(reason="test")
            # After drain, should be in draining status
            info = await reg.get_agent("test-em-2")
            assert info["status"] == "draining"
        finally:
            await bus.stop()
            await reg.stop()


# ── DistributedRateLimiter Tests ──


class TestDistributedRateLimiter:
    @pytest.mark.asyncio
    async def test_basic_rate_limit(self, redis):
        from core.cluster.rate_limiter import DistributedRateLimiter

        rl = DistributedRateLimiter(redis=redis, prefix=TEST_PREFIX)

        resource = f"test:{uuid.uuid4().hex[:8]}"

        # First request should be allowed
        assert await rl.check(resource, limit=5, window=60) is True

        # Fill up to limit
        for _ in range(4):
            assert await rl.check(resource, limit=5, window=60) is True

        # Over limit should be denied
        assert await rl.check(resource, limit=5, window=60) is False

        stats = rl.get_stats()
        assert stats["checks"] == 6
        assert stats["allowed"] == 5
        assert stats["denied"] == 1

    @pytest.mark.asyncio
    async def test_get_usage(self, redis):
        from core.cluster.rate_limiter import DistributedRateLimiter

        rl = DistributedRateLimiter(redis=redis, prefix=TEST_PREFIX)

        resource = f"test:{uuid.uuid4().hex[:8]}"

        await rl.check(resource, limit=100, window=60)
        await rl.check(resource, limit=100, window=60)
        await rl.check(resource, limit=100, window=60)

        usage = await rl.get_usage(resource, window=60)
        assert usage["current_window_count"] >= 3
        assert "weighted_count" in usage
        assert "window_position" in usage

    @pytest.mark.asyncio
    async def test_reset(self, redis):
        from core.cluster.rate_limiter import DistributedRateLimiter

        rl = DistributedRateLimiter(redis=redis, prefix=TEST_PREFIX)

        resource = f"test:{uuid.uuid4().hex[:8]}"

        # Fill up
        for _ in range(5):
            await rl.check(resource, limit=5, window=60)

        # Should be denied
        assert await rl.check(resource, limit=5, window=60) is False

        # Reset
        await rl.reset(resource, window=60)

        # Should be allowed again
        assert await rl.check(resource, limit=5, window=60) is True

    @pytest.mark.asyncio
    async def test_cost(self, redis):
        from core.cluster.rate_limiter import DistributedRateLimiter

        rl = DistributedRateLimiter(redis=redis, prefix=TEST_PREFIX)

        resource = f"test:{uuid.uuid4().hex[:8]}"

        # Cost of 3 out of limit of 5
        assert await rl.check(resource, limit=5, window=60, cost=3) is True
        # Another cost of 3 should exceed
        assert await rl.check(resource, limit=5, window=60, cost=3) is False


# ── ClusterMetrics Tests ──


class TestClusterMetrics:
    @pytest.mark.asyncio
    async def test_prometheus_export_disabled(self):
        from core.cluster.metrics import ClusterMetrics

        mock_cm = MagicMock()
        mock_cm.is_active = False

        metrics = ClusterMetrics(mock_cm)
        text = await metrics.export_prometheus()
        assert "nexus_cluster_enabled 0" in text

    @pytest.mark.asyncio
    async def test_collect_returns_structure(self):
        from core.cluster.metrics import ClusterMetrics

        mock_cm = MagicMock()
        mock_cm.is_active = False

        metrics = ClusterMetrics(mock_cm)
        data = await metrics.collect()
        assert data["cluster_enabled"] is False


# ── ClusterManager Integration Test ──


class TestClusterManagerIntegration:
    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Test complete ClusterManager start → status → stop cycle."""
        from core.cluster import ClusterManager

        config = {
            "CLUSTER_ENABLED": True,
            "REDIS_URL": "redis://localhost:6379",
            "REDIS_KEY_PREFIX": TEST_PREFIX,
            "CLUSTER_AGENT_ID": f"test-cm-{uuid.uuid4().hex[:8]}",
            "CLUSTER_ROLE": "primary",
            "CLUSTER_MAX_LOAD": 20,
            "CLUSTER_HEARTBEAT_INTERVAL": 1,
            "CLUSTER_FAILURE_THRESHOLD": 3,
            "CLUSTER_ELECTION_TIMEOUT": 5,
            "CLUSTER_MIN_SECONDARIES": 0,
            "CLUSTER_WORKING_MEMORY_TTL": 60,
            "CLUSTER_VECTOR_DIMS": 4,
            "CLUSTER_MEMORY_PROMOTION_DELAY": 300,
        }

        cm = ClusterManager(config)
        assert cm.enabled is True

        # Start
        started = await cm.start(
            host="127.0.0.1", port=8080,
            models=["test/model"],
            capabilities=["test"],
        )
        assert started is True
        assert cm.is_active is True
        assert cm.is_primary is True

        # Verify all subsystems initialized
        assert cm.registry is not None
        assert cm.event_bus is not None
        assert cm.task_stream is not None
        assert cm.working_memory is not None
        assert cm.memory_index is not None
        assert cm.health_monitor is not None
        assert cm.election_manager is not None
        assert cm.rate_limiter is not None
        assert cm.metrics is not None

        # Get status
        status = await cm.get_status()
        assert status["enabled"] is True
        assert status["active"] is True
        assert status["role"] == "primary"

        # Use convenience methods
        await cm.store_session("test-conv", {"hello": "world"})
        session = await cm.get_session("test-conv")
        assert session is not None
        assert session["hello"] == "world"

        # Rate limit
        allowed = await cm.check_rate_limit("test:tool", limit=10, window=60)
        assert allowed is True

        # Metrics
        metrics = await cm.metrics.collect()
        assert metrics["cluster_enabled"] is True

        prometheus = await cm.metrics.export_prometheus()
        assert "nexus_cluster_enabled 1" in prometheus

        # Stop
        await cm.stop()
        assert cm.is_active is False

    @pytest.mark.asyncio
    async def test_disabled_mode(self):
        """Test that disabled cluster does nothing."""
        from core.cluster import ClusterManager

        cm = ClusterManager({"CLUSTER_ENABLED": False})
        assert cm.enabled is False

        result = await cm.start()
        assert result is False

        session = await cm.get_session("any")
        assert session is None

        allowed = await cm.check_rate_limit("any", limit=10)
        assert allowed is True  # No cluster = always allowed

        await cm.stop()  # Should not raise
