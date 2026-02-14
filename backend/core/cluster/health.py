"""Health Monitor — SDOWN/ODOWN failure detection inspired by Redis Sentinel.

Two-phase failure detection:
    SDOWN (Subjective Down): This agent alone detects missed heartbeats
    ODOWN (Objective Down): Quorum of agents agree the target is down

Flow:
    1. Health monitor runs every heartbeat_interval seconds
    2. For each peer, checks heartbeat age against failure_threshold
    3. If threshold exceeded → SDOWN, publish to event bus
    4. Collect SDOWN votes from other agents in Redis sorted set
    5. If votes >= quorum (N/2 + 1) → ODOWN, trigger election

Key: nexus:failover:votes:{target_id}  → Sorted set of agent votes
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("nexus.cluster.health")

# Type for failover callback
FailoverCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class HealthMonitor:
    """Monitors agent health and triggers failover via SDOWN/ODOWN.

    Usage:
        monitor = HealthMonitor(
            redis=redis, registry=registry, event_bus=event_bus,
            prefix="nexus:", agent_id="nexus-01",
            heartbeat_interval=2, failure_threshold=3,
        )
        monitor.set_failover_callback(on_primary_odown)
        await monitor.start()
    """

    def __init__(
        self,
        redis,
        registry,
        event_bus,
        prefix: str,
        agent_id: str,
        heartbeat_interval: int = 2,
        failure_threshold: int = 3,
    ):
        self._redis = redis
        self._registry = registry
        self._event_bus = event_bus
        self._prefix = prefix
        self.agent_id = agent_id
        self.heartbeat_interval = heartbeat_interval
        self.failure_threshold = failure_threshold

        # Track SDOWN state per agent (to avoid duplicate alerts)
        self._sdown_agents: dict[str, float] = {}  # agent_id → time first marked SDOWN
        self._odown_agents: set[str] = set()  # agents confirmed ODOWN

        # Callback for ODOWN on primary
        self._failover_callback: Optional[FailoverCallback] = None

        # Background task
        self._monitor_task: Optional[asyncio.Task] = None
        self._stopped = False

        # Stats
        self._checks = 0
        self._sdown_events = 0
        self._odown_events = 0

    # ── Key helpers ──────────────────────────────────────────────

    def _votes_key(self, target_id: str) -> str:
        """Sorted set key for ODOWN votes on a target agent."""
        return f"{self._prefix}failover:votes:{target_id}"

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the health monitoring loop."""
        # Register as health event handler (receive other agents' SDOWN reports)
        if self._event_bus:
            await self._event_bus.subscribe("health", self._handle_health_event)

        self._monitor_task = asyncio.create_task(self._monitor_loop())

        logger.info(
            f"Health monitor started: interval={self.heartbeat_interval}s "
            f"threshold={self.failure_threshold} "
            f"quorum=N/2+1"
        )

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._stopped = True
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        logger.info(
            f"Health monitor stopped: checks={self._checks} "
            f"sdown={self._sdown_events} odown={self._odown_events}"
        )

    def set_failover_callback(self, callback: FailoverCallback) -> None:
        """Set callback invoked when primary reaches ODOWN.

        Args:
            callback: async def callback(target_id: str, agent_info: dict) -> None
        """
        self._failover_callback = callback

    # ── Monitor Loop ─────────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        """Background loop: check peer health every heartbeat interval."""
        # Small initial delay to let agents register
        try:
            await asyncio.sleep(self.heartbeat_interval * 2)
        except asyncio.CancelledError:
            return

        while not self._stopped:
            try:
                await self._check_peers()
                self._checks += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Health check error: {e}")

            try:
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break

    async def _check_peers(self) -> None:
        """Check all registered agents for missed heartbeats."""
        agents = await self._registry.get_all_agents()
        now = int(time.time())
        active_ids = set()

        for agent in agents:
            agent_id = agent["id"]
            active_ids.add(agent_id)

            # Skip self
            if agent.get("is_self"):
                continue

            # Skip stopped/failed agents (already handled)
            if agent["status"] in ("stopped", "failed"):
                continue

            missed = agent.get("missed_heartbeats", 0)

            if missed >= self.failure_threshold:
                # Agent appears down
                await self._mark_sdown(agent_id, agent)
            else:
                # Agent is healthy — clear any SDOWN state
                await self._clear_sdown(agent_id)

        # Clear SDOWN for agents that are no longer registered
        stale_sdowns = [aid for aid in self._sdown_agents if aid not in active_ids]
        for aid in stale_sdowns:
            await self._clear_sdown(aid)

    # ── SDOWN ────────────────────────────────────────────────────

    async def _mark_sdown(self, target_id: str, agent_info: dict) -> None:
        """Mark an agent as Subjectively Down (SDOWN).

        Only fires once per target until they recover.
        """
        if target_id in self._sdown_agents:
            # Already marked — check if we should escalate to ODOWN
            await self._check_odown(target_id, agent_info)
            return

        self._sdown_agents[target_id] = time.time()
        self._sdown_events += 1

        logger.warning(
            f"SDOWN detected: {target_id} "
            f"(missed={agent_info.get('missed_heartbeats', '?')} heartbeats, "
            f"age={agent_info.get('heartbeat_age_seconds', '?')}s)"
        )

        # Publish SDOWN to event bus so other agents can see it
        if self._event_bus:
            await self._event_bus.publish("health", {
                "type": "agent_sdown",
                "target_id": target_id,
                "target_role": agent_info.get("role", "unknown"),
                "missed_heartbeats": agent_info.get("missed_heartbeats", 0),
                "heartbeat_age": agent_info.get("heartbeat_age_seconds", 0),
            })

        # Cast our vote for ODOWN
        await self._cast_vote(target_id)

        # Immediately check quorum (might already have enough votes)
        await self._check_odown(target_id, agent_info)

    async def _clear_sdown(self, target_id: str) -> None:
        """Clear SDOWN state — agent has recovered."""
        if target_id not in self._sdown_agents:
            return

        del self._sdown_agents[target_id]

        # Remove our vote
        try:
            await self._redis.zrem(self._votes_key(target_id), self.agent_id)
        except Exception:
            pass

        # If agent was ODOWN, clear that too
        if target_id in self._odown_agents:
            self._odown_agents.discard(target_id)
            logger.info(f"Agent recovered from ODOWN: {target_id}")

            # Publish recovery event
            if self._event_bus:
                await self._event_bus.publish("health", {
                    "type": "agent_recovered",
                    "target_id": target_id,
                })

    # ── Voting ───────────────────────────────────────────────────

    async def _cast_vote(self, target_id: str) -> None:
        """Cast a vote that target agent is down.

        Votes are stored in a sorted set with score = timestamp.
        Votes expire after 30 seconds (3x the check interval).
        """
        votes_key = self._votes_key(target_id)
        now = int(time.time())

        pipe = self._redis.pipeline()
        pipe.zadd(votes_key, {self.agent_id: now})
        # Expire old votes (older than 30 seconds)
        pipe.zremrangebyscore(votes_key, "-inf", now - 30)
        # Set TTL on the votes key itself
        pipe.expire(votes_key, 60)
        await pipe.execute()

    async def _count_votes(self, target_id: str) -> int:
        """Count current valid votes for a target being down."""
        votes_key = self._votes_key(target_id)
        now = int(time.time())

        # Clean stale votes first
        await self._redis.zremrangebyscore(votes_key, "-inf", now - 30)

        return await self._redis.zcard(votes_key)

    async def _get_voters(self, target_id: str) -> list[str]:
        """Get list of agents that voted target is down."""
        votes_key = self._votes_key(target_id)
        members = await self._redis.zrange(votes_key, 0, -1)
        return [m.decode("utf-8") if isinstance(m, bytes) else m for m in members]

    # ── ODOWN ────────────────────────────────────────────────────

    async def _check_odown(self, target_id: str, agent_info: dict) -> None:
        """Check if quorum agrees that target is down → ODOWN."""
        if target_id in self._odown_agents:
            return  # Already in ODOWN

        # Calculate quorum: N/2 + 1 (including self)
        agents = await self._registry.get_all_agents()
        total_agents = len([a for a in agents if a["status"] != "stopped"])

        # Need at least 2 agents for quorum; solo agent = always primary
        if total_agents < 2:
            return

        quorum = (total_agents // 2) + 1
        votes = await self._count_votes(target_id)

        if votes >= quorum:
            # ODOWN confirmed!
            self._odown_agents.add(target_id)
            self._odown_events += 1

            voters = await self._get_voters(target_id)

            logger.critical(
                f"ODOWN confirmed: {target_id} "
                f"(votes={votes}/{total_agents}, quorum={quorum}, "
                f"voters={voters})"
            )

            # Publish ODOWN event
            if self._event_bus:
                await self._event_bus.publish("health", {
                    "type": "agent_odown",
                    "target_id": target_id,
                    "target_role": agent_info.get("role", "unknown"),
                    "votes": votes,
                    "quorum": quorum,
                    "total_agents": total_agents,
                    "voters": voters,
                })

            # If the downed agent is primary → trigger failover
            if agent_info.get("role") == "primary":
                logger.critical(
                    f"PRIMARY DOWN: {target_id} — initiating failover"
                )
                if self._failover_callback:
                    try:
                        await self._failover_callback(target_id, agent_info)
                    except Exception as e:
                        logger.error(f"Failover callback failed: {e}")

    # ── Event Handler ────────────────────────────────────────────

    async def _handle_health_event(self, channel: str, event: dict) -> None:
        """Handle health events from other agents.

        When we receive an SDOWN report from another agent, we cast
        our own vote if we also see the target as unhealthy.
        """
        event_type = event.get("type", "")
        target_id = event.get("target_id", "")

        if not target_id or target_id == self.agent_id:
            return

        if event_type == "agent_sdown":
            # Another agent reports SDOWN — verify from our perspective
            agent = await self._registry.get_agent(target_id)
            if not agent:
                return

            # Check if we also see this agent as unhealthy
            now = int(time.time())
            heartbeat_age = now - agent.get("last_heartbeat", 0)
            missed = heartbeat_age // max(self.heartbeat_interval, 1)

            if missed >= self.failure_threshold:
                # We agree — cast our vote
                await self._cast_vote(target_id)

                # Check quorum
                agent_info = {
                    "role": agent.get("role", "unknown"),
                    "missed_heartbeats": missed,
                    "heartbeat_age_seconds": heartbeat_age,
                }
                await self._check_odown(target_id, agent_info)

    # ── Status ───────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get health monitor status."""
        return {
            "checks": self._checks,
            "sdown_events": self._sdown_events,
            "odown_events": self._odown_events,
            "sdown_agents": list(self._sdown_agents.keys()),
            "odown_agents": list(self._odown_agents),
        }

    async def get_vote_status(self) -> dict[str, dict]:
        """Get vote counts for all agents currently being voted on."""
        result = {}
        for target_id in list(self._sdown_agents.keys()):
            votes = await self._count_votes(target_id)
            voters = await self._get_voters(target_id)
            result[target_id] = {
                "votes": votes,
                "voters": voters,
                "odown": target_id in self._odown_agents,
                "sdown_since": self._sdown_agents.get(target_id, 0),
            }
        return result
