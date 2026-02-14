"""Agent Registry — registration, heartbeat, and discovery via Redis Hashes.

Each agent registers as a Redis Hash:
    nexus:agent:{agent_id} → {id, role, status, host, port, models, ...}

Heartbeat loop runs every N seconds updating last_heartbeat timestamp.
Discovery scans all nexus:agent:* keys to find peers.

Role assignment:
    - "auto" (default): first agent becomes primary, subsequent → secondary
    - "primary" / "secondary": forced role
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("nexus.cluster.registry")


class AgentRegistry:
    """Manages agent registration, heartbeat, and peer discovery."""

    def __init__(
        self,
        redis,
        prefix: str,
        agent_id: str,
        role: str,
        host: str,
        port: int,
        max_load: int,
        heartbeat_interval: int,
        failure_threshold: int,
        models: list[str],
        capabilities: list[str],
    ):
        self._redis = redis
        self._prefix = prefix
        self.agent_id = agent_id
        self.role = role  # will be resolved in start()
        self.host = host
        self.port = port
        self.max_load = max_load
        self.heartbeat_interval = heartbeat_interval
        self.failure_threshold = failure_threshold
        self.models = models
        self.capabilities = capabilities

        self.status = "starting"
        self.current_load = 0
        self.config_epoch = 0
        self.started_at = 0

        self._heartbeat_task: Optional[asyncio.Task] = None
        self._stopped = False

    def _key(self, agent_id: str = None) -> str:
        """Redis key for an agent."""
        return f"{self._prefix}agent:{agent_id or self.agent_id}"

    def _agents_pattern(self) -> str:
        """Glob pattern for all agent keys."""
        return f"{self._prefix}agent:*"

    async def start(self) -> None:
        """Register this agent and start heartbeat loop."""
        self.started_at = int(time.time())

        # Resolve role
        if self.role == "auto":
            self.role = await self._auto_assign_role()

        # Fetch or initialize config epoch
        epoch_key = f"{self._prefix}config_epoch"
        current_epoch = await self._redis.get(epoch_key)
        if current_epoch is None:
            await self._redis.set(epoch_key, 0)
            self.config_epoch = 0
        else:
            self.config_epoch = int(current_epoch)

        # Register in Redis
        await self._write_registration()
        self.status = "active"
        await self._update_field("status", "active")

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info(
            f"Agent registered: id={self.agent_id} role={self.role} "
            f"host={self.host}:{self.port} epoch={self.config_epoch}"
        )

    async def stop(self) -> None:
        """Deregister this agent and stop heartbeat."""
        self._stopped = True

        # Cancel heartbeat
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Update status and set short TTL (cleanup if agent doesn't restart)
        try:
            await self._update_field("status", "stopped")
            await self._redis.expire(self._key(), 30)  # cleanup in 30s
        except Exception as e:
            logger.warning(f"Error during deregistration: {e}")

        logger.info(f"Agent deregistered: {self.agent_id}")

    async def _auto_assign_role(self) -> str:
        """Auto-assign role: first agent = primary, rest = secondary."""
        agents = await self.get_all_agents()
        active_primaries = [
            a for a in agents
            if a.get("role") == "primary" and a.get("status") == "active"
        ]

        if not active_primaries:
            logger.info("No active primary found — claiming primary role")
            return "primary"
        else:
            logger.info(
                f"Primary exists ({active_primaries[0]['id']}) — joining as secondary"
            )
            return "secondary"

    async def _write_registration(self) -> None:
        """Write full agent registration to Redis Hash."""
        data = {
            "id": self.agent_id,
            "role": self.role,
            "status": self.status,
            "host": self.host,
            "port": str(self.port),
            "models": json.dumps(self.models),
            "capabilities": json.dumps(self.capabilities),
            "current_load": str(self.current_load),
            "max_load": str(self.max_load),
            "last_heartbeat": str(int(time.time())),
            "started_at": str(self.started_at),
            "config_epoch": str(self.config_epoch),
        }
        await self._redis.hset(self._key(), mapping=data)
        # Set TTL as safety net (heartbeat refreshes it)
        ttl = self.heartbeat_interval * self.failure_threshold * 3
        await self._redis.expire(self._key(), ttl)

    async def _update_field(self, field: str, value: str) -> None:
        """Update a single field in the agent's registration."""
        await self._redis.hset(self._key(), field, value)

    async def heartbeat(self) -> None:
        """Send a single heartbeat — update timestamp and refresh TTL."""
        now = str(int(time.time()))
        pipe = self._redis.pipeline()
        pipe.hset(self._key(), "last_heartbeat", now)
        pipe.hset(self._key(), "current_load", str(self.current_load))
        ttl = self.heartbeat_interval * self.failure_threshold * 3
        pipe.expire(self._key(), ttl)
        await pipe.execute()

    async def _heartbeat_loop(self) -> None:
        """Background heartbeat loop."""
        while not self._stopped:
            try:
                await self.heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e}")

            try:
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break

    async def get_all_agents(self) -> list[dict[str, Any]]:
        """Discover all registered agents by scanning keys."""
        agents = []
        pattern = self._agents_pattern()
        now = int(time.time())

        async for key in self._redis.scan_iter(match=pattern, count=100):
            try:
                data = await self._redis.hgetall(key)
                if not data:
                    continue

                agent = {
                    "id": data.get("id", ""),
                    "role": data.get("role", "unknown"),
                    "status": data.get("status", "unknown"),
                    "host": data.get("host", ""),
                    "port": int(data.get("port", 0)),
                    "models": json.loads(data.get("models", "[]")),
                    "capabilities": json.loads(data.get("capabilities", "[]")),
                    "current_load": int(data.get("current_load", 0)),
                    "max_load": int(data.get("max_load", 0)),
                    "last_heartbeat": int(data.get("last_heartbeat", 0)),
                    "started_at": int(data.get("started_at", 0)),
                    "config_epoch": int(data.get("config_epoch", 0)),
                    "is_self": data.get("id", "") == self.agent_id,
                }

                # Calculate health
                heartbeat_age = now - agent["last_heartbeat"]
                missed = heartbeat_age // max(self.heartbeat_interval, 1)
                agent["heartbeat_age_seconds"] = heartbeat_age
                agent["missed_heartbeats"] = missed
                agent["healthy"] = missed < self.failure_threshold

                agents.append(agent)
            except Exception as e:
                logger.warning(f"Error reading agent key {key}: {e}")

        # Sort: primary first, then by agent_id
        agents.sort(key=lambda a: (0 if a["role"] == "primary" else 1, a["id"]))
        return agents

    async def get_agent(self, agent_id: str) -> Optional[dict[str, Any]]:
        """Get a specific agent's registration."""
        data = await self._redis.hgetall(self._key(agent_id))
        if not data:
            return None

        return {
            "id": data.get("id", ""),
            "role": data.get("role", "unknown"),
            "status": data.get("status", "unknown"),
            "host": data.get("host", ""),
            "port": int(data.get("port", 0)),
            "models": json.loads(data.get("models", "[]")),
            "capabilities": json.loads(data.get("capabilities", "[]")),
            "current_load": int(data.get("current_load", 0)),
            "max_load": int(data.get("max_load", 0)),
            "last_heartbeat": int(data.get("last_heartbeat", 0)),
            "started_at": int(data.get("started_at", 0)),
            "config_epoch": int(data.get("config_epoch", 0)),
        }

    async def update_load(self, delta: int) -> None:
        """Increment/decrement the current load counter."""
        self.current_load = max(0, self.current_load + delta)
        await self._update_field("current_load", str(self.current_load))

    async def set_role(self, new_role: str) -> None:
        """Change this agent's role (used during election/failover)."""
        old_role = self.role
        self.role = new_role
        await self._update_field("role", new_role)
        logger.info(f"Role changed: {old_role} → {new_role}")

    async def increment_epoch(self) -> int:
        """Atomically increment the global config epoch and update local copy."""
        epoch_key = f"{self._prefix}config_epoch"
        new_epoch = await self._redis.incr(epoch_key)
        self.config_epoch = new_epoch
        await self._update_field("config_epoch", str(new_epoch))
        return new_epoch

    async def get_primary(self) -> Optional[dict[str, Any]]:
        """Find the current primary agent."""
        agents = await self.get_all_agents()
        for agent in agents:
            if agent["role"] == "primary" and agent["healthy"]:
                return agent
        return None

    async def get_healthy_secondaries(self) -> list[dict[str, Any]]:
        """Get all healthy secondary agents."""
        agents = await self.get_all_agents()
        return [
            a for a in agents
            if a["role"] == "secondary" and a["healthy"]
        ]
