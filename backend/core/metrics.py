"""Lightweight in-memory metrics collector with percentile tracking.

No external dependencies — uses a fixed-size ring buffer per metric.
Designed for production observability without adding latency.

Architecture:
    - MetricsCollector singleton created in app.py lifespan
    - record(metric, value_ms) called from hot paths (RAG, model, tools)
    - percentiles(metric) returns p50/p95/p99/avg/count
    - Hourly bucket rotation: keeps last 24 hours of data
    - GET /admin/metrics → dashboard data
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger("nexus.metrics")

# Ring buffer size per metric per hourly bucket
BUCKET_SIZE = 2000
# Keep this many hourly buckets
MAX_BUCKETS = 24

# Singleton
_collector: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """Get or create the global MetricsCollector singleton."""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector


class MetricsCollector:
    """In-memory percentile tracker with hourly rotation."""

    def __init__(self) -> None:
        # {metric_name: {hour_key: [values]}}
        self._buckets: dict[str, dict[int, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._counters: dict[str, int] = defaultdict(int)
        self._start_time = time.time()

    @staticmethod
    def _hour_key() -> int:
        """Current hour as integer (unix epoch // 3600)."""
        return int(time.time()) // 3600

    def record(self, metric: str, value_ms: float) -> None:
        """Record a timing value in milliseconds."""
        hour = self._hour_key()
        bucket = self._buckets[metric][hour]
        if len(bucket) < BUCKET_SIZE:
            bucket.append(value_ms)
        else:
            # Ring buffer: overwrite oldest
            idx = self._counters[metric] % BUCKET_SIZE
            bucket[idx] = value_ms
        self._counters[metric] += 1

        # Prune old buckets
        cutoff = hour - MAX_BUCKETS
        stale = [h for h in self._buckets[metric] if h < cutoff]
        for h in stale:
            del self._buckets[metric][h]

    def record_count(self, metric: str, count: int = 1) -> None:
        """Record a count (non-timing) metric."""
        self._counters[metric] += count

    def get_count(self, metric: str) -> int:
        """Get raw counter value."""
        return self._counters.get(metric, 0)

    def percentiles(self, metric: str) -> dict[str, float]:
        """Calculate percentiles for a metric across all retained buckets.

        Returns:
            {"p50": ..., "p95": ..., "p99": ..., "avg": ..., "count": ...}
        """
        # Collect all values across buckets
        values: list[float] = []
        for bucket in self._buckets.get(metric, {}).values():
            values.extend(bucket)

        if not values:
            return {"p50": 0, "p95": 0, "p99": 0, "avg": 0, "count": 0}

        values.sort()
        n = len(values)

        return {
            "p50": round(values[int(n * 0.50)], 1),
            "p95": round(values[int(n * 0.95)], 1),
            "p99": round(values[min(int(n * 0.99), n - 1)], 1),
            "avg": round(sum(values) / n, 1),
            "count": n,
        }

    def all_metrics(self) -> dict[str, dict[str, float]]:
        """Return percentiles for all tracked timing metrics."""
        result = {}
        for metric in self._buckets:
            result[metric] = self.percentiles(metric)
        return result

    def dashboard(self) -> dict[str, Any]:
        """Full dashboard payload for admin API."""
        latency = {}
        for metric in ("rag_retrieve", "model_inference", "tool_execution",
                        "total_turn", "embed", "kg_extraction",
                        "memory_ingest", "memory_prune", "memory_archive",
                        "fts_search", "ws_message", "db_query"):
            p = self.percentiles(metric)
            if p["count"] > 0:
                latency[metric] = p

        return {
            "uptime_seconds": int(time.time() - self._start_time),
            "latency": latency,
            "counters": {
                "total_turns": self.get_count("turns"),
                "total_tool_calls": self.get_count("tool_calls"),
                "tool_errors": self.get_count("tool_errors"),
                "tool_timeouts": self.get_count("tool_timeouts"),
                "idempotency_hits": self.get_count("idempotency_hits"),
                "failovers": self.get_count("failovers"),
                "ollama_calls": self.get_count("ollama_calls"),
                "claude_calls": self.get_count("claude_calls"),
                "claude_code_calls": self.get_count("claude_code_calls"),
                "aborts": self.get_count("aborts"),
                "memories_pruned": self.get_count("memories_pruned"),
                "memories_archived": self.get_count("memories_archived"),
            },
        }
