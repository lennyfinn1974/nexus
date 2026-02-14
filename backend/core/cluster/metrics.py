"""Cluster Metrics — Prometheus-compatible metrics export.

Collects and exposes cluster health, performance, and resource metrics
in Prometheus text exposition format (OpenMetrics compatible).

Metrics cover:
    - Agent registry (count, roles, health)
    - Task streams (published, consumed, failed, queue depth)
    - Working memory (reads, writes, sessions, promotions)
    - Memory index (stored, searched, duplicates)
    - Health monitor (checks, SDOWN/ODOWN events)
    - Election (elections won/lost, demotions)
    - Redis connection health
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger("nexus.cluster.metrics")


class ClusterMetrics:
    """Collects cluster metrics and exports in Prometheus text format.

    Usage:
        metrics = ClusterMetrics(cluster_manager)
        text = await metrics.export_prometheus()

    Metrics naming follows Prometheus conventions:
        - nexus_cluster_agents_total
        - nexus_cluster_task_stream_{published,consumed,failed}_total
        - nexus_cluster_working_memory_{reads,writes}_total
        - etc.
    """

    def __init__(self, cluster_manager):
        self._cm = cluster_manager
        self._start_time = time.time()

        # Rolling counters for rate calculation
        self._snapshots: list[dict[str, Any]] = []
        self._max_snapshots = 60  # 1 minute of history at 1s resolution

    async def collect(self) -> dict[str, Any]:
        """Collect all cluster metrics into a structured dict.

        Returns:
            Dict with metric groups: agents, tasks, memory, health, election, redis
        """
        if not self._cm or not self._cm.is_active:
            return {"cluster_enabled": False}

        metrics: dict[str, Any] = {
            "cluster_enabled": True,
            "agent_id": self._cm.agent_id,
            "uptime_seconds": time.time() - self._start_time,
            "timestamp": time.time(),
        }

        # Agent metrics
        try:
            agents = await self._cm.get_agents()
            metrics["agents"] = {
                "total": len(agents),
                "primary": sum(1 for a in agents if a.get("role") == "primary"),
                "secondary": sum(1 for a in agents if a.get("role") == "secondary"),
                "standby": sum(1 for a in agents if a.get("role") == "standby"),
                "healthy": sum(1 for a in agents if a.get("healthy", False)),
                "unhealthy": sum(1 for a in agents if not a.get("healthy", False)),
                "total_load": sum(a.get("current_load", 0) for a in agents),
                "total_capacity": sum(a.get("max_load", 0) for a in agents),
            }
            if agents:
                total_cap = metrics["agents"]["total_capacity"]
                metrics["agents"]["load_ratio"] = (
                    metrics["agents"]["total_load"] / total_cap if total_cap > 0 else 0
                )
        except Exception as e:
            logger.debug(f"Agent metrics error: {e}")
            metrics["agents"] = {"total": 0, "error": str(e)}

        # Task stream metrics
        if self._cm.task_stream:
            try:
                stream_info = await self._cm.task_stream.get_stream_info()
                stats = self._cm.task_stream.get_stats()
                metrics["tasks"] = {
                    "published_total": stats.get("published", 0),
                    "consumed_total": stats.get("consumed", 0),
                    "completed_total": stats.get("completed", 0),
                    "failed_total": stats.get("failed", 0),
                    "dead_lettered_total": stats.get("dead_lettered", 0),
                    "queue_high": stream_info.get("high", {}).get("length", 0),
                    "queue_normal": stream_info.get("normal", {}).get("length", 0),
                    "queue_low": stream_info.get("low", {}).get("length", 0),
                    "queue_dead_letter": stream_info.get("dead_letter", {}).get("length", 0),
                    "pending_high": stream_info.get("high", {}).get("pending", 0),
                    "pending_normal": stream_info.get("normal", {}).get("pending", 0),
                    "pending_low": stream_info.get("low", {}).get("pending", 0),
                }
                # Total queue depth
                metrics["tasks"]["queue_depth"] = (
                    metrics["tasks"]["queue_high"]
                    + metrics["tasks"]["queue_normal"]
                    + metrics["tasks"]["queue_low"]
                )
            except Exception as e:
                logger.debug(f"Task metrics error: {e}")
                metrics["tasks"] = {"error": str(e)}

        # Working memory metrics
        if self._cm.working_memory:
            try:
                wm = self._cm.working_memory.get_stats()
                active = await self._cm.working_memory.count_active_sessions()
                metrics["working_memory"] = {
                    "reads_total": wm.get("reads", 0),
                    "writes_total": wm.get("writes", 0),
                    "promotions_total": wm.get("promotions", 0),
                    "evictions_total": wm.get("evictions", 0),
                    "promotion_queue_size": wm.get("promotion_queue_size", 0),
                    "active_sessions": active,
                }
            except Exception as e:
                logger.debug(f"Working memory metrics error: {e}")
                metrics["working_memory"] = {"error": str(e)}

        # Memory index metrics
        if self._cm.memory_index:
            try:
                mi = self._cm.memory_index.get_stats()
                total = await self._cm.memory_index.count_memories()
                metrics["memory_index"] = {
                    "stored_total": mi.get("stored", 0),
                    "searched_total": mi.get("searched", 0),
                    "duplicates_found_total": mi.get("duplicates_found", 0),
                    "index_available": 1 if mi.get("index_available") else 0,
                    "total_memories": total,
                    "vector_dims": mi.get("vector_dims", 0),
                }
            except Exception as e:
                logger.debug(f"Memory index metrics error: {e}")
                metrics["memory_index"] = {"error": str(e)}

        # Health monitor metrics
        if self._cm.health_monitor:
            try:
                hm = self._cm.health_monitor.get_status()
                metrics["health"] = {
                    "checks_total": hm.get("checks", 0),
                    "sdown_events_total": hm.get("sdown_events", 0),
                    "odown_events_total": hm.get("odown_events", 0),
                    "sdown_agents": len(hm.get("sdown_agents", [])),
                    "odown_agents": len(hm.get("odown_agents", [])),
                }
            except Exception as e:
                logger.debug(f"Health metrics error: {e}")
                metrics["health"] = {"error": str(e)}

        # Election metrics
        if self._cm.election_manager:
            try:
                em = self._cm.election_manager.get_status()
                min_sec = await self._cm.election_manager.check_min_secondaries()
                metrics["election"] = {
                    "in_progress": 1 if em.get("election_in_progress") else 0,
                    "elections_won_total": em.get("elections_won", 0),
                    "elections_lost_total": em.get("elections_lost", 0),
                    "demotions_total": em.get("demotions", 0),
                    "min_secondaries_met": 1 if min_sec else 0,
                    "last_election_seconds_ago": (
                        time.time() - em["last_election_time"]
                        if em.get("last_election_time", 0) > 0 else -1
                    ),
                }
            except Exception as e:
                logger.debug(f"Election metrics error: {e}")
                metrics["election"] = {"error": str(e)}

        # Event bus metrics
        if self._cm.event_bus:
            try:
                eb = self._cm.event_bus.get_stats()
                metrics["event_bus"] = {
                    "published_total": eb.get("published", 0),
                    "received_total": eb.get("received", 0),
                    "errors_total": eb.get("errors", 0),
                    "handler_count": eb.get("handler_count", 0),
                }
            except Exception as e:
                logger.debug(f"Event bus metrics error: {e}")
                metrics["event_bus"] = {"error": str(e)}

        # Redis connection metrics
        try:
            redis_info = await self._cm._redis.info("memory")
            metrics["redis"] = {
                "connected": 1,
                "used_memory_bytes": redis_info.get("used_memory", 0),
                "used_memory_peak_bytes": redis_info.get("used_memory_peak", 0),
                "used_memory_rss_bytes": redis_info.get("used_memory_rss", 0),
            }
            # Add client info
            client_info = await self._cm._redis.info("clients")
            metrics["redis"]["connected_clients"] = client_info.get("connected_clients", 0)
        except Exception as e:
            logger.debug(f"Redis metrics error: {e}")
            metrics["redis"] = {"connected": 0, "error": str(e)}

        # Store snapshot for rate calculations
        self._snapshots.append(metrics)
        if len(self._snapshots) > self._max_snapshots:
            self._snapshots = self._snapshots[-self._max_snapshots:]

        return metrics

    async def export_prometheus(self) -> str:
        """Export metrics in Prometheus text exposition format.

        Returns:
            String in Prometheus text format, ready for /metrics endpoint.
        """
        metrics = await self.collect()

        if not metrics.get("cluster_enabled"):
            return (
                "# HELP nexus_cluster_enabled Whether clustering is enabled\n"
                "# TYPE nexus_cluster_enabled gauge\n"
                "nexus_cluster_enabled 0\n"
            )

        lines: list[str] = []

        def _gauge(name: str, help_text: str, value, labels: str = ""):
            label_str = f"{{{labels}}}" if labels else ""
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name}{label_str} {value}")

        def _counter(name: str, help_text: str, value, labels: str = ""):
            label_str = f"{{{labels}}}" if labels else ""
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name}{label_str} {value}")

        agent_id = metrics.get("agent_id", "unknown")
        base_labels = f'agent_id="{agent_id}"'

        # Cluster info
        _gauge("nexus_cluster_enabled", "Whether clustering is enabled", 1)
        _gauge("nexus_cluster_uptime_seconds", "Cluster uptime in seconds",
               f"{metrics.get('uptime_seconds', 0):.1f}", base_labels)

        # Agent metrics
        agents = metrics.get("agents", {})
        if "error" not in agents:
            _gauge("nexus_cluster_agents_total", "Total registered agents",
                   agents.get("total", 0))
            _gauge("nexus_cluster_agents_healthy", "Healthy agents",
                   agents.get("healthy", 0))
            _gauge("nexus_cluster_agents_unhealthy", "Unhealthy agents",
                   agents.get("unhealthy", 0))
            for role in ("primary", "secondary", "standby"):
                _gauge("nexus_cluster_agents_by_role",
                       f"Agents with role {role}",
                       agents.get(role, 0),
                       f'role="{role}"')
            _gauge("nexus_cluster_load_total", "Total current load across cluster",
                   agents.get("total_load", 0))
            _gauge("nexus_cluster_capacity_total", "Total capacity across cluster",
                   agents.get("total_capacity", 0))
            _gauge("nexus_cluster_load_ratio", "Cluster load ratio (0-1)",
                   f"{agents.get('load_ratio', 0):.3f}")

        # Task stream metrics
        tasks = metrics.get("tasks", {})
        if "error" not in tasks:
            _counter("nexus_cluster_tasks_published_total",
                     "Total tasks published", tasks.get("published_total", 0))
            _counter("nexus_cluster_tasks_consumed_total",
                     "Total tasks consumed", tasks.get("consumed_total", 0))
            _counter("nexus_cluster_tasks_completed_total",
                     "Total tasks completed", tasks.get("completed_total", 0))
            _counter("nexus_cluster_tasks_failed_total",
                     "Total tasks failed", tasks.get("failed_total", 0))
            _counter("nexus_cluster_tasks_dead_lettered_total",
                     "Total tasks dead-lettered", tasks.get("dead_lettered_total", 0))
            _gauge("nexus_cluster_task_queue_depth",
                   "Total tasks waiting in all queues", tasks.get("queue_depth", 0))
            for priority in ("high", "normal", "low"):
                _gauge("nexus_cluster_task_queue_length",
                       f"Queue length for {priority} priority",
                       tasks.get(f"queue_{priority}", 0),
                       f'priority="{priority}"')
                _gauge("nexus_cluster_task_pending",
                       f"Pending tasks for {priority} priority",
                       tasks.get(f"pending_{priority}", 0),
                       f'priority="{priority}"')

        # Working memory metrics
        wm = metrics.get("working_memory", {})
        if "error" not in wm:
            _counter("nexus_cluster_working_memory_reads_total",
                     "Working memory reads", wm.get("reads_total", 0))
            _counter("nexus_cluster_working_memory_writes_total",
                     "Working memory writes", wm.get("writes_total", 0))
            _counter("nexus_cluster_working_memory_promotions_total",
                     "Items promoted to long-term memory", wm.get("promotions_total", 0))
            _counter("nexus_cluster_working_memory_evictions_total",
                     "Sessions evicted", wm.get("evictions_total", 0))
            _gauge("nexus_cluster_working_memory_active_sessions",
                   "Active sessions in working memory", wm.get("active_sessions", 0))
            _gauge("nexus_cluster_working_memory_promotion_queue",
                   "Items waiting for promotion", wm.get("promotion_queue_size", 0))

        # Memory index metrics
        mi = metrics.get("memory_index", {})
        if "error" not in mi:
            _counter("nexus_cluster_memory_index_stored_total",
                     "Memories stored in index", mi.get("stored_total", 0))
            _counter("nexus_cluster_memory_index_searched_total",
                     "Semantic searches performed", mi.get("searched_total", 0))
            _counter("nexus_cluster_memory_index_duplicates_total",
                     "Duplicate memories detected", mi.get("duplicates_found_total", 0))
            _gauge("nexus_cluster_memory_index_available",
                   "Whether RediSearch index is available", mi.get("index_available", 0))
            _gauge("nexus_cluster_memory_index_total_memories",
                   "Total memories in index", mi.get("total_memories", 0))

        # Health monitor metrics
        health = metrics.get("health", {})
        if "error" not in health:
            _counter("nexus_cluster_health_checks_total",
                     "Health checks performed", health.get("checks_total", 0))
            _counter("nexus_cluster_health_sdown_total",
                     "Subjective-down events", health.get("sdown_events_total", 0))
            _counter("nexus_cluster_health_odown_total",
                     "Objective-down events", health.get("odown_events_total", 0))
            _gauge("nexus_cluster_health_sdown_agents",
                   "Agents currently in SDOWN state", health.get("sdown_agents", 0))
            _gauge("nexus_cluster_health_odown_agents",
                   "Agents currently in ODOWN state", health.get("odown_agents", 0))

        # Election metrics
        election = metrics.get("election", {})
        if "error" not in election:
            _gauge("nexus_cluster_election_in_progress",
                   "Whether an election is currently running", election.get("in_progress", 0))
            _counter("nexus_cluster_elections_won_total",
                     "Elections won by this agent", election.get("elections_won_total", 0))
            _counter("nexus_cluster_elections_lost_total",
                     "Elections lost by this agent", election.get("elections_lost_total", 0))
            _counter("nexus_cluster_demotions_total",
                     "Times this agent was demoted", election.get("demotions_total", 0))
            _gauge("nexus_cluster_min_secondaries_met",
                   "Whether minimum secondary count is met", election.get("min_secondaries_met", 0))

        # Event bus metrics
        eb = metrics.get("event_bus", {})
        if "error" not in eb:
            _counter("nexus_cluster_events_published_total",
                     "Events published to bus", eb.get("published_total", 0))
            _counter("nexus_cluster_events_received_total",
                     "Events received from bus", eb.get("received_total", 0))
            _counter("nexus_cluster_event_errors_total",
                     "Event processing errors", eb.get("errors_total", 0))
            _gauge("nexus_cluster_event_handlers",
                   "Registered event handlers", eb.get("handler_count", 0))

        # Redis metrics
        redis_m = metrics.get("redis", {})
        _gauge("nexus_cluster_redis_connected",
               "Whether Redis is connected", redis_m.get("connected", 0))
        if redis_m.get("connected"):
            _gauge("nexus_cluster_redis_memory_bytes",
                   "Redis used memory in bytes", redis_m.get("used_memory_bytes", 0))
            _gauge("nexus_cluster_redis_memory_peak_bytes",
                   "Redis peak memory in bytes", redis_m.get("used_memory_peak_bytes", 0))
            _gauge("nexus_cluster_redis_memory_rss_bytes",
                   "Redis RSS memory in bytes", redis_m.get("used_memory_rss_bytes", 0))
            _gauge("nexus_cluster_redis_clients",
                   "Connected Redis clients", redis_m.get("connected_clients", 0))

        return "\n".join(lines) + "\n"

    def get_rates(self, window_seconds: int = 60) -> dict[str, float]:
        """Calculate per-second rates over a time window.

        Useful for dashboard sparklines and alerting.

        Returns:
            Dict of metric_name → rate_per_second
        """
        if len(self._snapshots) < 2:
            return {}

        now = time.time()
        cutoff = now - window_seconds

        # Find oldest snapshot within window
        oldest = None
        for snap in self._snapshots:
            if snap.get("timestamp", 0) >= cutoff:
                oldest = snap
                break

        if oldest is None or oldest is self._snapshots[-1]:
            return {}

        latest = self._snapshots[-1]
        elapsed = latest.get("timestamp", 0) - oldest.get("timestamp", 0)
        if elapsed <= 0:
            return {}

        rates = {}

        # Task rates
        t_old = oldest.get("tasks", {})
        t_new = latest.get("tasks", {})
        for key in ("published_total", "consumed_total", "completed_total", "failed_total"):
            old_val = t_old.get(key, 0)
            new_val = t_new.get(key, 0)
            if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                rates[f"tasks_{key}_per_sec"] = (new_val - old_val) / elapsed

        # Working memory rates
        wm_old = oldest.get("working_memory", {})
        wm_new = latest.get("working_memory", {})
        for key in ("reads_total", "writes_total"):
            old_val = wm_old.get(key, 0)
            new_val = wm_new.get(key, 0)
            if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                rates[f"wm_{key}_per_sec"] = (new_val - old_val) / elapsed

        # Event bus rates
        eb_old = oldest.get("event_bus", {})
        eb_new = latest.get("event_bus", {})
        for key in ("published_total", "received_total"):
            old_val = eb_old.get(key, 0)
            new_val = eb_new.get(key, 0)
            if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                rates[f"events_{key}_per_sec"] = (new_val - old_val) / elapsed

        # Health check rate
        h_old = oldest.get("health", {})
        h_new = latest.get("health", {})
        old_checks = h_old.get("checks_total", 0)
        new_checks = h_new.get("checks_total", 0)
        if isinstance(old_checks, (int, float)) and isinstance(new_checks, (int, float)):
            rates["health_checks_per_sec"] = (new_checks - old_checks) / elapsed

        return rates
