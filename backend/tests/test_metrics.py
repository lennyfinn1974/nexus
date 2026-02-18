"""Tests for MetricsCollector, /admin/metrics, and /admin/memory/health.

Three test classes:
  1. TestMetricsCollector — unit tests for the core collector (no mocks)
  2. TestMetricsDashboardEndpoint — integration tests for /admin/metrics
  3. TestMemoryHealthEndpoint — integration tests for /admin/memory/health
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. MetricsCollector Unit Tests ──────────────────────────────


class TestMetricsCollector:
    """Unit tests for MetricsCollector — pure logic, no mocks needed."""

    def _make_collector(self):
        from core.metrics import MetricsCollector
        return MetricsCollector()

    def test_empty_percentiles(self):
        """Percentiles for an unrecorded metric should be all zeros."""
        c = self._make_collector()
        p = c.percentiles("nonexistent")
        assert p == {"p50": 0, "p95": 0, "p99": 0, "avg": 0, "count": 0}

    def test_single_value(self):
        """A single value should appear in all percentiles."""
        c = self._make_collector()
        c.record("latency", 42.0)
        p = c.percentiles("latency")
        assert p["count"] == 1
        assert p["p50"] == 42.0
        assert p["avg"] == 42.0

    def test_percentile_ordering(self):
        """p50 <= p95 <= p99 for a range of values."""
        c = self._make_collector()
        for i in range(100):
            c.record("latency", float(i))
        p = c.percentiles("latency")
        assert p["p50"] <= p["p95"] <= p["p99"]
        assert p["count"] == 100

    def test_p50_is_median(self):
        """p50 should be approximately the median for evenly distributed data."""
        c = self._make_collector()
        for i in range(1000):
            c.record("lat", float(i))
        p = c.percentiles("lat")
        assert 490 <= p["p50"] <= 510  # Median of 0..999 should be ~500

    def test_p95_is_high_tail(self):
        """p95 should be in the top 5% for evenly distributed data."""
        c = self._make_collector()
        for i in range(1000):
            c.record("lat", float(i))
        p = c.percentiles("lat")
        assert p["p95"] >= 940  # 95th percentile of 0..999

    def test_counter_increment(self):
        """record_count() should accumulate counts."""
        c = self._make_collector()
        assert c.get_count("calls") == 0
        c.record_count("calls")
        c.record_count("calls", 5)
        assert c.get_count("calls") == 6

    def test_record_also_increments_counter(self):
        """record() increments the internal counter for the metric."""
        c = self._make_collector()
        c.record("tool", 10.0)
        c.record("tool", 20.0)
        assert c.get_count("tool") == 2

    def test_all_metrics_returns_all_tracked(self):
        """all_metrics() should return percentiles for every recorded timing metric."""
        c = self._make_collector()
        c.record("a", 1.0)
        c.record("b", 2.0)
        c.record("c", 3.0)
        m = c.all_metrics()
        assert set(m.keys()) == {"a", "b", "c"}
        assert all(m[k]["count"] == 1 for k in m)

    def test_ring_buffer_caps_at_bucket_size(self):
        """After BUCKET_SIZE values, the buffer should not grow."""
        from core.metrics import BUCKET_SIZE
        c = self._make_collector()
        for i in range(BUCKET_SIZE + 500):
            c.record("full", float(i))
        hour = c._hour_key()
        bucket = c._buckets["full"][hour]
        assert len(bucket) == BUCKET_SIZE

    def test_dashboard_structure(self):
        """dashboard() should return uptime, latency dict, and counters dict."""
        c = self._make_collector()
        c.record("rag_retrieve", 25.0)
        c.record_count("turns", 3)
        c.record_count("tool_calls", 7)

        d = c.dashboard()
        assert "uptime_seconds" in d
        assert isinstance(d["uptime_seconds"], int)
        assert "latency" in d
        assert "rag_retrieve" in d["latency"]
        assert "counters" in d
        assert d["counters"]["total_turns"] == 3
        assert d["counters"]["total_tool_calls"] == 7

    def test_dashboard_skips_empty_latency(self):
        """Metrics with zero samples should not appear in latency dict."""
        c = self._make_collector()
        c.record("model_inference", 100.0)
        d = c.dashboard()
        assert "model_inference" in d["latency"]
        assert "rag_retrieve" not in d["latency"]  # Not recorded

    def test_uptime_increases(self):
        """uptime_seconds should be >= 0 and reflect time since creation."""
        c = self._make_collector()
        d = c.dashboard()
        assert d["uptime_seconds"] >= 0

    def test_all_counter_keys_present(self):
        """dashboard() should include all expected counter keys even when zero."""
        c = self._make_collector()
        d = c.dashboard()
        expected_keys = {
            "total_turns", "total_tool_calls", "tool_errors", "tool_timeouts",
            "idempotency_hits", "failovers", "ollama_calls", "claude_calls",
            "claude_code_calls", "aborts", "memories_pruned", "memories_archived",
        }
        assert set(d["counters"].keys()) == expected_keys
        assert all(v == 0 for v in d["counters"].values())


# ── 2. /admin/metrics Endpoint Tests ────────────────────────────


class TestMetricsDashboardEndpoint:
    """Tests for GET /admin/metrics endpoint enrichment logic.

    Mocks _get_app_state() to inject controlled subsystem mocks.
    """

    @pytest.mark.asyncio
    async def test_basic_dashboard_no_subsystems(self):
        """Endpoint should return core metrics even with no subsystems."""
        from core.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.record("model_inference", 50.0)
        collector.record_count("turns", 1)

        with patch("core.metrics.get_metrics", return_value=collector), \
             patch("admin._get_app_state", return_value=None):
            import admin
            response = await admin.get_metrics_dashboard()
            data = json.loads(response.body)

            assert "uptime_seconds" in data
            assert "latency" in data
            assert "model_inference" in data["latency"]
            assert data["counters"]["total_turns"] == 1
            # No subsystem keys when app_state is None
            assert "rag" not in data
            assert "knowledge_graph" not in data
            assert "plugin_audit" not in data

    @pytest.mark.asyncio
    async def test_enrichment_with_rag(self):
        """Endpoint should include RAG stats when rag_pipeline is available."""
        from core.metrics import MetricsCollector

        collector = MetricsCollector()
        mock_state = MagicMock()
        mock_state.rag_pipeline = MagicMock()
        mock_state.rag_pipeline.get_stats.return_value = {"index_size": 500, "avg_ms": 25}
        mock_state.knowledge_graph = None
        mock_state.memory_bulletin = None
        mock_state.plugin_manager = None
        mock_state.cluster_manager = None

        with patch("core.metrics.get_metrics", return_value=collector), \
             patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_metrics_dashboard()
            data = json.loads(response.body)
            assert data["rag"] == {"index_size": 500, "avg_ms": 25}

    @pytest.mark.asyncio
    async def test_enrichment_with_plugin_audit(self):
        """Endpoint should include plugin audit when plugin_manager is available."""
        from core.metrics import MetricsCollector

        collector = MetricsCollector()
        mock_state = MagicMock()
        mock_state.rag_pipeline = None
        mock_state.knowledge_graph = None
        mock_state.memory_bulletin = None
        mock_state.plugin_manager = MagicMock()
        mock_state.plugin_manager.get_audit_summary.return_value = {
            "brave": {"search": 42},
        }
        mock_state.cluster_manager = None

        with patch("core.metrics.get_metrics", return_value=collector), \
             patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_metrics_dashboard()
            data = json.loads(response.body)
            assert data["plugin_audit"] == {"brave": {"search": 42}}

    @pytest.mark.asyncio
    async def test_enrichment_with_memory_archive(self):
        """Endpoint should include archive stats when cluster + session_factory available."""
        from core.metrics import MetricsCollector

        collector = MetricsCollector()
        mock_state = MagicMock()
        mock_state.rag_pipeline = None
        mock_state.knowledge_graph = None
        mock_state.memory_bulletin = None
        mock_state.plugin_manager = None

        mock_idx = MagicMock()
        mock_idx.get_archive_stats = AsyncMock(return_value={"archived_count": 42})
        mock_state.cluster_manager = MagicMock()
        mock_state.cluster_manager.memory_index = mock_idx
        mock_state.session_factory = MagicMock()

        with patch("core.metrics.get_metrics", return_value=collector), \
             patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_metrics_dashboard()
            data = json.loads(response.body)
            assert data["memory_archive"] == {"archived_count": 42}

    @pytest.mark.asyncio
    async def test_archive_stats_exception_handled(self):
        """If get_archive_stats raises, endpoint should not crash."""
        from core.metrics import MetricsCollector

        collector = MetricsCollector()
        mock_state = MagicMock()
        mock_state.rag_pipeline = None
        mock_state.knowledge_graph = None
        mock_state.memory_bulletin = None
        mock_state.plugin_manager = None

        mock_idx = MagicMock()
        mock_idx.get_archive_stats = AsyncMock(side_effect=Exception("Redis down"))
        mock_state.cluster_manager = MagicMock()
        mock_state.cluster_manager.memory_index = mock_idx
        mock_state.session_factory = MagicMock()

        with patch("core.metrics.get_metrics", return_value=collector), \
             patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_metrics_dashboard()
            data = json.loads(response.body)
            # Should succeed without memory_archive key
            assert "memory_archive" not in data


# ── 3. /admin/memory/health Endpoint Tests ──────────────────────


class TestMemoryHealthEndpoint:
    """Tests for GET /admin/memory/health endpoint."""

    @pytest.mark.asyncio
    async def test_no_memory_index(self):
        """Should return status=no_memory_index when cluster_manager is None."""
        mock_state = MagicMock()
        mock_state.cluster_manager = None

        with patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_memory_health()
            data = json.loads(response.body)
            assert data["status"] == "no_memory_index"

    @pytest.mark.asyncio
    async def test_no_app_state(self):
        """Should return status=no_memory_index when app_state is None."""
        with patch("admin._get_app_state", return_value=None):
            import admin
            response = await admin.get_memory_health()
            data = json.loads(response.body)
            assert data["status"] == "no_memory_index"

    def _make_mock_idx(self, mems=None, types=None, archive_count=0):
        """Helper to create a configured mock MemoryIndex."""
        mock_idx = MagicMock()
        mock_idx._backend = "vsim"
        mock_idx.dedup_threshold = 0.12
        mock_idx._duplicates_found = 0
        mock_idx.count_memories = AsyncMock(return_value=len(mems or []))
        mock_idx.get_memory_types = AsyncMock(return_value=types or {})
        mock_idx.scan_all_with_access = AsyncMock(return_value=mems or [])
        mock_idx.compute_importance = MagicMock(return_value=0.5)
        mock_idx.get_archive_stats = AsyncMock(return_value={"archived_count": archive_count})
        return mock_idx

    def _make_mock_state(self, mock_idx):
        """Helper to wrap a mock memory index in a mock app state."""
        mock_state = MagicMock()
        mock_state.cluster_manager = MagicMock()
        mock_state.cluster_manager.memory_index = mock_idx
        mock_state.session_factory = MagicMock()
        return mock_state

    @pytest.mark.asyncio
    async def test_age_distribution_buckets(self):
        """Memories should be categorized into correct age buckets."""
        now = time.time()
        mock_mems = [
            {"id": "m1", "memory_type": "fact", "created_at": str(now - 86400 * 2), "access_count": "5"},
            {"id": "m2", "memory_type": "fact", "created_at": str(now - 86400 * 15), "access_count": "3"},
            {"id": "m3", "memory_type": "event", "created_at": str(now - 86400 * 60), "access_count": "1"},
            {"id": "m4", "memory_type": "pref", "created_at": str(now - 86400 * 120), "access_count": "8"},
        ]
        mock_idx = self._make_mock_idx(mock_mems, {"fact": 2, "event": 1, "pref": 1})
        mock_state = self._make_mock_state(mock_idx)

        with patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_memory_health()
            data = json.loads(response.body)

            assert data["status"] == "ok"
            assert data["total_active"] == 4
            assert data["age_distribution"]["0-7d"] == 1
            assert data["age_distribution"]["7-30d"] == 1
            assert data["age_distribution"]["30-90d"] == 1
            assert data["age_distribution"]["90d+"] == 1

    @pytest.mark.asyncio
    async def test_importance_stats(self):
        """Importance stats should reflect computed values."""
        now = time.time()
        mock_mems = [
            {"id": "m1", "memory_type": "fact", "created_at": str(now - 86400), "access_count": "10"},
            {"id": "m2", "memory_type": "fact", "created_at": str(now - 86400), "access_count": "2"},
        ]
        importances = iter([0.9, 0.3])

        mock_idx = self._make_mock_idx(mock_mems, {"fact": 2})
        mock_idx.compute_importance = MagicMock(side_effect=lambda m: next(importances))
        mock_state = self._make_mock_state(mock_idx)

        with patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_memory_health()
            data = json.loads(response.body)

            assert data["avg_importance"] == 0.6  # (0.9 + 0.3) / 2
            assert data["top_importance"] == 0.9
            assert data["bottom_importance"] == 0.3

    @pytest.mark.asyncio
    async def test_top_accessed_sorted(self):
        """top_accessed should be sorted by access_count descending."""
        now = time.time()
        mock_mems = [
            {"id": "low", "memory_type": "fact", "created_at": str(now), "access_count": "1"},
            {"id": "high", "memory_type": "fact", "created_at": str(now), "access_count": "50"},
            {"id": "mid", "memory_type": "fact", "created_at": str(now), "access_count": "10"},
        ]
        mock_idx = self._make_mock_idx(mock_mems, {"fact": 3})
        mock_state = self._make_mock_state(mock_idx)

        with patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_memory_health()
            data = json.loads(response.body)

            top = data["top_accessed"]
            assert len(top) == 3
            assert top[0]["id"] == "high"
            assert top[0]["access_count"] == 50
            assert top[1]["id"] == "mid"
            assert top[2]["id"] == "low"

    @pytest.mark.asyncio
    async def test_dedup_stats_included(self):
        """Should include dedup threshold and duplicates blocked count."""
        mock_idx = self._make_mock_idx()
        mock_idx.dedup_threshold = 0.15
        mock_idx._duplicates_found = 42
        mock_state = self._make_mock_state(mock_idx)

        with patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_memory_health()
            data = json.loads(response.body)

            assert data["dedup_threshold"] == 0.15
            assert data["duplicates_blocked"] == 42

    @pytest.mark.asyncio
    async def test_exception_during_scan(self):
        """If count_memories raises, should include error but not crash."""
        mock_idx = MagicMock()
        mock_idx._backend = "vsim"
        mock_idx.count_memories = AsyncMock(side_effect=Exception("Redis timeout"))

        mock_state = self._make_mock_state(mock_idx)

        with patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_memory_health()
            data = json.loads(response.body)

            # Should catch the error gracefully
            assert "error" in data
            assert "Redis timeout" in data["error"]

    @pytest.mark.asyncio
    async def test_empty_memory_index(self):
        """Should handle zero memories gracefully."""
        mock_idx = self._make_mock_idx(mems=[], types={})
        mock_state = self._make_mock_state(mock_idx)

        with patch("admin._get_app_state", return_value=mock_state):
            import admin
            response = await admin.get_memory_health()
            data = json.loads(response.body)

            assert data["status"] == "ok"
            assert data["total_active"] == 0
            assert data["by_type"] == {}
            assert data["age_distribution"] == {"0-7d": 0, "7-30d": 0, "30-90d": 0, "90d+": 0}
            # No importance stats when empty
            assert "avg_importance" not in data
