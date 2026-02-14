"""Nexus Agent Clustering — Redis-based coordination layer.

Feature-flagged via CLUSTER_ENABLED setting. When disabled (default),
the entire module is inert — zero Redis dependency, zero behaviour change.

When enabled, provides:
  - Agent registry (heartbeat, discovery)
  - Event bus (Pub/Sub broadcast)
  - Task streams (Redis Streams distributed queue)
  - Working memory (session state in Redis JSON)
  - Semantic memory index (RediSearch vectors)
  - Primary election & failover
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

logger = logging.getLogger("nexus.cluster")


class ClusterManager:
    """Central coordinator for all clustering subsystems.

    Lifecycle:
        1. Created in app.py lifespan
        2. start() connects to Redis, registers agent, starts heartbeat
        3. stop() deregisters, drains tasks, closes connections
    """

    def __init__(self, config: dict[str, Any]):
        self.enabled = config.get("CLUSTER_ENABLED", False)

        if not self.enabled:
            logger.info("Clustering disabled (CLUSTER_ENABLED=False)")
            self._redis = None
            self._redis_binary = None
            self.registry = None
            self.event_bus = None
            self.task_stream = None
            self.working_memory = None
            self.memory_index = None
            self.health_monitor = None
            self.election_manager = None
            self.rate_limiter = None
            self.metrics = None
            self._started = False
            return

        # Core settings
        self.redis_url: str = config.get("REDIS_URL", "redis://localhost:6379")
        self.redis_password: str = config.get("REDIS_PASSWORD", "")
        self.redis_tls: bool = config.get("REDIS_TLS", False)
        self.redis_tls_ca: str = config.get("REDIS_TLS_CA_CERT", "")
        self.redis_tls_cert: str = config.get("REDIS_TLS_CLIENT_CERT", "")
        self.redis_tls_key: str = config.get("REDIS_TLS_CLIENT_KEY", "")
        self.redis_tls_verify: bool = config.get("REDIS_TLS_VERIFY", True)
        self.key_prefix: str = config.get("REDIS_KEY_PREFIX", "nexus:")

        # Agent identity
        self.agent_id: str = config.get("CLUSTER_AGENT_ID", "") or f"nexus-{uuid.uuid4().hex[:8]}"
        self.role: str = config.get("CLUSTER_ROLE", "auto")  # primary, secondary, auto
        self.max_load: int = int(config.get("CLUSTER_MAX_LOAD", 20))

        # Heartbeat / failover
        self.heartbeat_interval: int = int(config.get("CLUSTER_HEARTBEAT_INTERVAL", 2))
        self.failure_threshold: int = int(config.get("CLUSTER_FAILURE_THRESHOLD", 3))
        self.election_timeout: int = int(config.get("CLUSTER_ELECTION_TIMEOUT", 5))
        self.min_secondaries: int = int(config.get("CLUSTER_MIN_SECONDARIES", 1))

        # Memory
        self.working_memory_ttl: int = int(config.get("CLUSTER_WORKING_MEMORY_TTL", 3600))
        self.vector_dims: int = int(config.get("CLUSTER_VECTOR_DIMS", 1536))
        self.memory_promotion_delay: int = int(config.get("CLUSTER_MEMORY_PROMOTION_DELAY", 300))

        # State
        self._redis = None
        self._redis_binary = None  # Binary connection for vector storage
        self._redis_pubsub = None
        self.registry = None
        self.event_bus = None
        self.task_stream = None
        self.working_memory = None
        self.memory_index = None
        self.health_monitor = None
        self.election_manager = None
        self.rate_limiter = None
        self.metrics = None
        self._started = False

    async def start(self, host: str = "127.0.0.1", port: int = 8080,
                    models: list[str] = None, capabilities: list[str] = None) -> bool:
        """Connect to Redis and start all clustering subsystems."""
        if not self.enabled:
            return False

        try:
            import redis.asyncio as aioredis

            # Build connection kwargs
            conn_kwargs: dict[str, Any] = {
                "decode_responses": True,
                "socket_connect_timeout": 5,
                "socket_timeout": 5,
                "retry_on_timeout": True,
            }
            if self.redis_password:
                conn_kwargs["password"] = self.redis_password
            if self.redis_tls:
                import ssl as _ssl
                ssl_ctx = _ssl.create_default_context()
                if self.redis_tls_ca:
                    ssl_ctx.load_verify_locations(self.redis_tls_ca)
                if self.redis_tls_cert and self.redis_tls_key:
                    ssl_ctx.load_cert_chain(self.redis_tls_cert, self.redis_tls_key)
                if not self.redis_tls_verify:
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = _ssl.CERT_NONE
                conn_kwargs["ssl"] = ssl_ctx

            # Create connection pool
            self._redis = aioredis.from_url(
                self.redis_url,
                **conn_kwargs,
            )

            # Test connection
            pong = await self._redis.ping()
            if not pong:
                raise ConnectionError("Redis PING failed")

            redis_info = await self._redis.info("server")
            redis_version = redis_info.get("redis_version", "unknown")
            logger.info(f"Redis connected: {self.redis_url} (v{redis_version})")

            # Create a second connection WITHOUT decode_responses for binary data (embeddings)
            binary_kwargs = {k: v for k, v in conn_kwargs.items()}
            binary_kwargs["decode_responses"] = False
            self._redis_binary = aioredis.from_url(
                self.redis_url,
                **binary_kwargs,
            )

            # Initialize subsystems
            from .registry import AgentRegistry
            from .event_bus import EventBus
            from .task_stream import TaskStream
            from .working_memory import WorkingMemory
            from .memory_index import MemoryIndex
            from .health import HealthMonitor
            from .election import ElectionManager
            from .rate_limiter import DistributedRateLimiter
            from .metrics import ClusterMetrics

            self.registry = AgentRegistry(
                redis=self._redis,
                prefix=self.key_prefix,
                agent_id=self.agent_id,
                role=self.role,
                host=host,
                port=port,
                max_load=self.max_load,
                heartbeat_interval=self.heartbeat_interval,
                failure_threshold=self.failure_threshold,
                models=models or [],
                capabilities=capabilities or [],
            )

            self.event_bus = EventBus(
                redis=self._redis,
                prefix=self.key_prefix,
                agent_id=self.agent_id,
            )

            self.task_stream = TaskStream(
                redis=self._redis,
                prefix=self.key_prefix,
                agent_id=self.agent_id,
            )

            self.working_memory = WorkingMemory(
                redis=self._redis,
                prefix=self.key_prefix,
                agent_id=self.agent_id,
                session_ttl=self.working_memory_ttl,
                promotion_delay=self.memory_promotion_delay,
            )

            self.memory_index = MemoryIndex(
                redis=self._redis_binary,
                prefix=self.key_prefix,
                agent_id=self.agent_id,
                vector_dims=self.vector_dims,
            )

            self.election_manager = ElectionManager(
                redis=self._redis,
                registry=self.registry,
                event_bus=self.event_bus,
                prefix=self.key_prefix,
                agent_id=self.agent_id,
                election_timeout=self.election_timeout,
                min_secondaries=self.min_secondaries,
                working_memory=self.working_memory,
                task_stream=self.task_stream,
            )

            self.health_monitor = HealthMonitor(
                redis=self._redis,
                registry=self.registry,
                event_bus=self.event_bus,
                prefix=self.key_prefix,
                agent_id=self.agent_id,
                heartbeat_interval=self.heartbeat_interval,
                failure_threshold=self.failure_threshold,
            )

            self.rate_limiter = DistributedRateLimiter(
                redis=self._redis,
                prefix=self.key_prefix,
            )

            # Wire failover: health monitor ODOWN → triggers election
            self.health_monitor.set_failover_callback(
                self.election_manager.trigger_election
            )

            # Metrics collector (initialized after all subsystems)
            self.metrics = ClusterMetrics(self)

            # Start subsystems (order matters: registry & bus first, then consumers)
            await self.registry.start()
            await self.event_bus.start()
            await self.task_stream.start()
            await self.working_memory.start()
            await self.memory_index.start()
            await self.election_manager.start()
            await self.health_monitor.start()

            # Announce ourselves
            await self.event_bus.publish("agent", {
                "type": "agent_joined",
                "id": self.agent_id,
                "role": self.registry.role,
                "host": host,
                "port": port,
                "models": models or [],
                "capabilities": capabilities or [],
            })

            self._started = True
            logger.info(
                f"Cluster started: agent={self.agent_id} role={self.registry.role} "
                f"heartbeat={self.heartbeat_interval}s"
            )
            return True

        except ImportError:
            logger.error("redis package not installed. Run: pip3 install redis[hiredis]")
            self.enabled = False
            return False
        except Exception as e:
            logger.error(f"Cluster start failed: {e}")
            self.enabled = False
            return False

    async def stop(self) -> None:
        """Gracefully shut down all clustering subsystems."""
        if not self._started:
            return

        logger.info(f"Cluster stopping: agent={self.agent_id}")

        try:
            # Graceful drain: release work, trigger preemptive election if primary
            if self.election_manager:
                await self.election_manager.initiate_drain(reason="shutdown")

            # Announce departure
            if self.event_bus:
                await self.event_bus.publish("agent", {
                    "type": "agent_leaving",
                    "id": self.agent_id,
                    "reason": "shutdown",
                })

            # Stop subsystems (reverse order)
            if self.health_monitor:
                await self.health_monitor.stop()
            if self.election_manager:
                await self.election_manager.stop()
            if self.memory_index:
                await self.memory_index.stop()
            if self.working_memory:
                await self.working_memory.stop()
            if self.task_stream:
                await self.task_stream.stop()
            if self.event_bus:
                await self.event_bus.stop()
            if self.registry:
                await self.registry.stop()

            # Close Redis connections
            if self._redis_binary:
                await self._redis_binary.aclose()
            if self._redis:
                await self._redis.aclose()

        except Exception as e:
            logger.warning(f"Error during cluster shutdown: {e}")
        finally:
            self._started = False
            logger.info("Cluster stopped")

    @property
    def is_primary(self) -> bool:
        """Check if this agent is the current primary."""
        if not self.registry:
            return True  # single-agent mode = always primary
        return self.registry.role == "primary"

    @property
    def is_active(self) -> bool:
        """Check if clustering is active."""
        return self._started and self.enabled

    async def get_agents(self) -> list[dict]:
        """Get all registered agents."""
        if not self.registry:
            return []
        return await self.registry.get_all_agents()

    # ── Working Memory Shortcuts ─────────────────────────────────

    async def store_session(self, conv_id: str, data: dict) -> None:
        """Store session state in working memory (cross-agent visible)."""
        if self.working_memory:
            await self.working_memory.set_session(conv_id, data)

    async def get_session(self, conv_id: str) -> Optional[dict]:
        """Retrieve session state from working memory."""
        if self.working_memory:
            return await self.working_memory.get_session(conv_id)
        return None

    async def store_memory(
        self, text: str, embedding: list[float],
        memory_type: str = "general", source_conv: str = "",
    ) -> Optional[str]:
        """Store a memory in the semantic index (cross-agent searchable)."""
        if self.memory_index:
            return await self.memory_index.store(
                text=text, embedding=embedding,
                memory_type=memory_type, source_conv=source_conv,
            )
        return None

    async def search_memory(
        self, query_embedding: list[float], limit: int = 5,
    ) -> list[dict]:
        """Search memories by vector similarity."""
        if self.memory_index:
            return await self.memory_index.search(query_embedding, limit=limit)
        return []

    async def check_rate_limit(
        self, resource: str, limit: int = 60, window: int = 60
    ) -> bool:
        """Cluster-wide rate limit check. Falls back to True if unavailable."""
        if self.rate_limiter:
            return await self.rate_limiter.check(resource, limit, window)
        return True  # No cluster = no distributed limiting

    async def get_status(self) -> dict:
        """Get cluster status summary."""
        if not self.is_active:
            return {
                "enabled": False,
                "agent_id": None,
                "role": None,
                "agents": [],
                "redis_connected": False,
            }

        agents = await self.get_agents()
        status = {
            "enabled": True,
            "active": True,
            "agent_id": self.agent_id,
            "role": self.registry.role if self.registry else "unknown",
            "agents": agents,
            "agent_count": len(agents),
            "primary_id": next(
                (a["id"] for a in agents if a.get("role") == "primary"), None
            ),
            "redis_connected": True,
            "redis_url": self.redis_url.split("@")[-1] if "@" in self.redis_url else self.redis_url,
            "config_epoch": self.registry.config_epoch if self.registry else 0,
        }

        # Add task stream info
        if self.task_stream:
            try:
                status["task_streams"] = await self.task_stream.get_stream_info()
                status["task_stats"] = self.task_stream.get_stats()
            except Exception:
                pass

        # Add working memory info
        if self.working_memory:
            try:
                wm_stats = self.working_memory.get_stats()
                wm_stats["active_sessions"] = await self.working_memory.count_active_sessions()
                status["working_memory"] = wm_stats
            except Exception:
                pass

        # Add memory index info
        if self.memory_index:
            try:
                mi_stats = self.memory_index.get_stats()
                mi_stats["total_memories"] = await self.memory_index.count_memories()
                mi_stats["memory_types"] = await self.memory_index.get_memory_types()
                status["memory_index"] = mi_stats
            except Exception:
                pass

        # Add health monitor info
        if self.health_monitor:
            try:
                health_status = self.health_monitor.get_status()
                health_status["votes"] = await self.health_monitor.get_vote_status()
                status["health_monitor"] = health_status
            except Exception:
                pass

        # Add election info
        if self.election_manager:
            try:
                election_status = self.election_manager.get_status()
                election_status["min_secondaries_met"] = await self.election_manager.check_min_secondaries()
                status["election"] = election_status
            except Exception:
                pass

        return status
