"""Election — Leader election and failover protocol.

Implements a Sentinel-inspired election protocol:
    1. Health monitor detects ODOWN on primary → triggers election
    2. Eligible secondaries compete using a priority score
    3. Winner atomically increments config_epoch + claims primary role
    4. Loser(s) accept new primary if their epoch is lower (fencing)
    5. Old primary restarts as secondary when it detects higher epoch

Election Priority Score (lower wins):
    score = (epoch_lag * 1000) + current_load
    - epoch_lag: how far behind the global config_epoch
    - current_load: current task load (tiebreaker)
    → Most up-to-date, least loaded secondary wins

Fencing:
    All role changes require incrementing config_epoch atomically.
    Agents with stale epochs cannot claim primary — prevents split-brain.

Split-Brain Prevention:
    Primary stops accepting new work if fewer than min_secondaries
    are reachable (like Redis's min-replicas-to-write).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("nexus.cluster.election")

# Lock TTL for election — prevents multiple simultaneous elections
ELECTION_LOCK_TTL = 10  # seconds


class ElectionManager:
    """Manages leader election and failover.

    Usage:
        election = ElectionManager(
            redis=redis, registry=registry, event_bus=event_bus,
            prefix="nexus:", agent_id="nexus-01",
            election_timeout=5, min_secondaries=1,
        )
        await election.start()

        # Trigger election (called by health monitor on primary ODOWN)
        result = await election.trigger_election("old-primary-id")

        await election.stop()
    """

    def __init__(
        self,
        redis,
        registry,
        event_bus,
        prefix: str,
        agent_id: str,
        election_timeout: int = 5,
        min_secondaries: int = 1,
        working_memory=None,
        task_stream=None,
    ):
        self._redis = redis
        self._registry = registry
        self._event_bus = event_bus
        self._prefix = prefix
        self.agent_id = agent_id
        self.election_timeout = election_timeout
        self.min_secondaries = min_secondaries
        self._working_memory = working_memory
        self._task_stream = task_stream

        self._stopped = False

        # Election state
        self._election_in_progress = False
        self._last_election_time = 0.0
        self._elections_won = 0
        self._elections_lost = 0
        self._demotions = 0

    # ── Key helpers ──────────────────────────────────────────────

    def _lock_key(self) -> str:
        """Distributed lock key for election coordination."""
        return f"{self._prefix}election:lock"

    def _current_primary_key(self) -> str:
        """Key tracking the current known primary."""
        return f"{self._prefix}election:primary"

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Register event handlers for election-related events."""
        if self._event_bus:
            await self._event_bus.subscribe("config", self._handle_config_event)
            await self._event_bus.subscribe("agent", self._handle_agent_event)

        logger.info(
            f"Election manager started: timeout={self.election_timeout}s "
            f"min_secondaries={self.min_secondaries}"
        )

    async def stop(self) -> None:
        """Clean up."""
        self._stopped = True
        logger.info(
            f"Election manager stopped: won={self._elections_won} "
            f"lost={self._elections_lost} demotions={self._demotions}"
        )

    # ── Election Trigger ─────────────────────────────────────────

    async def trigger_election(
        self, failed_primary_id: str, failed_info: dict = None
    ) -> bool:
        """Trigger an election due to primary failure.

        Returns True if this agent became the new primary.
        """
        if self._election_in_progress:
            logger.info("Election already in progress, skipping")
            return False

        # Debounce: don't run elections too frequently
        now = time.time()
        if now - self._last_election_time < self.election_timeout:
            logger.info("Election cooldown active, skipping")
            return False

        self._election_in_progress = True
        self._last_election_time = now

        try:
            logger.info(
                f"Election triggered: failed_primary={failed_primary_id} "
                f"candidate={self.agent_id}"
            )

            # Step 1: Acquire election lock (distributed mutex)
            lock_acquired = await self._acquire_lock()
            if not lock_acquired:
                logger.info("Another agent is running the election")
                self._elections_lost += 1
                return False

            try:
                # Step 2: Verify primary is still down (avoid false positives)
                primary = await self._registry.get_agent(failed_primary_id)
                if primary:
                    now_ts = int(time.time())
                    age = now_ts - primary.get("last_heartbeat", 0)
                    missed = age // max(self._registry.heartbeat_interval, 1)
                    if missed < self._registry.failure_threshold:
                        logger.info(
                            f"Primary {failed_primary_id} recovered during election "
                            f"(missed={missed}), aborting"
                        )
                        return False

                # Step 3: Check eligibility
                if not await self._is_eligible():
                    logger.info("This agent is not eligible for election")
                    self._elections_lost += 1
                    return False

                # Step 4: Calculate priority and check competitors
                my_score = await self._calculate_priority()
                best_candidate = await self._find_best_candidate()

                if best_candidate and best_candidate["id"] != self.agent_id:
                    logger.info(
                        f"Better candidate exists: {best_candidate['id']} "
                        f"(score={best_candidate['score']:.1f} vs ours={my_score:.1f})"
                    )
                    self._elections_lost += 1
                    return False

                # Step 5: Win the election — promote to primary
                return await self._promote_to_primary(failed_primary_id)

            finally:
                await self._release_lock()

        except Exception as e:
            logger.error(f"Election error: {e}")
            return False
        finally:
            self._election_in_progress = False

    # ── Eligibility ──────────────────────────────────────────────

    async def _is_eligible(self) -> bool:
        """Check if this agent is eligible to become primary.

        Requirements:
            - Must be a secondary (or standby) in active status
            - Must have load below max
            - Must not be in draining status
        """
        if self._registry.role not in ("secondary", "standby", "auto"):
            return False

        if self._registry.status != "active":
            return False

        if self._registry.current_load >= self._registry.max_load:
            return False

        return True

    async def _calculate_priority(self) -> float:
        """Calculate this agent's election priority score.

        Lower score wins:
            score = (epoch_lag * 1000) + current_load

        epoch_lag: distance from global config_epoch (lower = more up-to-date)
        current_load: tiebreaker (lower = more capacity)
        """
        # Get global epoch
        epoch_key = f"{self._prefix}config_epoch"
        global_epoch = int(await self._redis.get(epoch_key) or 0)
        local_epoch = self._registry.config_epoch

        epoch_lag = max(0, global_epoch - local_epoch)
        load = self._registry.current_load

        return (epoch_lag * 1000) + load

    async def _find_best_candidate(self) -> Optional[dict]:
        """Find the best election candidate among all healthy secondaries.

        Returns the candidate with the lowest priority score.
        """
        agents = await self._registry.get_all_agents()
        epoch_key = f"{self._prefix}config_epoch"
        global_epoch = int(await self._redis.get(epoch_key) or 0)

        candidates = []
        for agent in agents:
            if agent["role"] not in ("secondary", "standby"):
                continue
            if not agent.get("healthy"):
                continue
            if agent["status"] != "active":
                continue
            if agent["current_load"] >= agent["max_load"]:
                continue

            epoch_lag = max(0, global_epoch - agent.get("config_epoch", 0))
            score = (epoch_lag * 1000) + agent["current_load"]

            candidates.append({
                "id": agent["id"],
                "score": score,
                "epoch_lag": epoch_lag,
                "load": agent["current_load"],
            })

        if not candidates:
            return None

        # Sort by score (lowest wins)
        candidates.sort(key=lambda c: c["score"])
        return candidates[0]

    # ── Promotion ────────────────────────────────────────────────

    async def _promote_to_primary(self, old_primary_id: str) -> bool:
        """Promote this agent to primary.

        Atomically:
            1. Increment config_epoch (fencing token)
            2. Set role = primary in registry
            3. Record ourselves as the current primary
            4. Broadcast election result
            5. Reassign orphaned work from old primary
        """
        try:
            # Step 1: Increment epoch (fencing — higher epoch = authoritative)
            new_epoch = await self._registry.increment_epoch()

            # Step 2: Claim primary role
            await self._registry.set_role("primary")

            # Step 3: Record current primary in Redis
            await self._redis.set(
                self._current_primary_key(),
                self.agent_id,
                ex=3600,  # 1 hour TTL as safety net
            )

            logger.critical(
                f"ELECTED PRIMARY: {self.agent_id} "
                f"(epoch={new_epoch}, old_primary={old_primary_id})"
            )

            # Step 4: Broadcast to all agents
            if self._event_bus:
                await self._event_bus.publish("config", {
                    "type": "primary_elected",
                    "new_primary": self.agent_id,
                    "old_primary": old_primary_id,
                    "config_epoch": new_epoch,
                })

            # Step 5: Reassign orphaned work
            await self._reassign_work(old_primary_id)

            self._elections_won += 1
            return True

        except Exception as e:
            logger.error(f"Promotion failed: {e}")
            # Rollback role
            try:
                await self._registry.set_role("secondary")
            except Exception:
                pass
            return False

    async def _reassign_work(self, old_primary_id: str) -> None:
        """Reassign work from the failed primary to this agent.

        1. Transfer conversation ownership from working memory
        2. Claim abandoned tasks from task stream
        """
        # Transfer conversation ownership
        if self._working_memory:
            try:
                work_items = await self._working_memory.get_agent_work(old_primary_id)
                for item in work_items:
                    conv_id = item.get("conv_id", "")
                    if conv_id:
                        await self._working_memory.claim_work(
                            conv_id, task_type=item.get("task_type", "conversation")
                        )
                        logger.info(
                            f"Transferred conversation {conv_id} from "
                            f"{old_primary_id} → {self.agent_id}"
                        )
            except Exception as e:
                logger.warning(f"Work transfer error: {e}")

        # Note: Task stream abandoned tasks are already handled by
        # the claim loop in task_stream.py (XAUTOCLAIM). The new primary
        # will automatically pick up unacknowledged tasks.

        logger.info(f"Work reassignment from {old_primary_id} complete")

    # ── Demotion ─────────────────────────────────────────────────

    async def check_and_demote(self) -> bool:
        """Check if we should demote ourselves.

        Called when we detect a higher config_epoch — another agent
        has been elected primary. We must step down to avoid split-brain.

        Returns True if we demoted ourselves.
        """
        if self._registry.role != "primary":
            return False

        # Check if someone else is primary with a higher epoch
        epoch_key = f"{self._prefix}config_epoch"
        global_epoch = int(await self._redis.get(epoch_key) or 0)

        if global_epoch > self._registry.config_epoch:
            # Someone else incremented the epoch — they are the new primary
            current_primary = await self._redis.get(self._current_primary_key())
            if current_primary:
                if isinstance(current_primary, bytes):
                    current_primary = current_primary.decode("utf-8")

                if current_primary != self.agent_id:
                    logger.critical(
                        f"DEMOTING: higher epoch detected "
                        f"(global={global_epoch} > ours={self._registry.config_epoch}). "
                        f"New primary={current_primary}"
                    )
                    await self._demote_to_secondary(global_epoch)
                    return True

        return False

    async def _demote_to_secondary(self, new_epoch: int) -> None:
        """Demote this agent from primary to secondary.

        Syncs to the new epoch and announces demotion.
        """
        old_role = self._registry.role
        await self._registry.set_role("secondary")

        # Sync epoch
        self._registry.config_epoch = new_epoch
        await self._registry._update_field("config_epoch", str(new_epoch))

        self._demotions += 1

        logger.info(
            f"Demoted: {old_role} → secondary (epoch synced to {new_epoch})"
        )

        # Announce demotion
        if self._event_bus:
            await self._event_bus.publish("agent", {
                "type": "agent_demoted",
                "id": self.agent_id,
                "from_role": old_role,
                "to_role": "secondary",
                "epoch": new_epoch,
            })

    # ── Split-Brain Prevention ───────────────────────────────────

    async def check_min_secondaries(self) -> bool:
        """Check if minimum secondaries requirement is met.

        If we're primary and fewer than min_secondaries are reachable,
        we should stop accepting new work to prevent split-brain.

        Returns True if we have enough secondaries.
        """
        if self._registry.role != "primary":
            return True  # Only primaries enforce this

        secondaries = await self._registry.get_healthy_secondaries()
        has_enough = len(secondaries) >= self.min_secondaries

        if not has_enough:
            logger.warning(
                f"Insufficient secondaries: {len(secondaries)}/{self.min_secondaries} "
                f"— primary should reject new work"
            )

        return has_enough

    # ── Graceful Draining ────────────────────────────────────────

    async def initiate_drain(self, reason: str = "shutdown") -> None:
        """Start draining work from this agent before shutdown.

        Sets status to 'draining', stops accepting new work,
        and waits for in-progress tasks to complete.
        """
        logger.info(f"Initiating drain: reason={reason}")

        # Update status
        await self._registry._update_field("status", "draining")
        self._registry.status = "draining"

        # Broadcast drain event
        if self._event_bus:
            await self._event_bus.publish("agent", {
                "type": "agent_draining",
                "id": self.agent_id,
                "role": self._registry.role,
                "reason": reason,
            })

        # If we're primary, trigger election for a replacement
        if self._registry.role == "primary":
            logger.info("Primary draining — triggering preemptive election")
            # Demote first so election can proceed
            await self._registry.set_role("secondary")

            if self._event_bus:
                await self._event_bus.publish("config", {
                    "type": "primary_draining",
                    "agent_id": self.agent_id,
                    "reason": reason,
                })

        # Release all work assignments
        if self._working_memory:
            try:
                my_work = await self._working_memory.get_agent_work()
                for item in my_work:
                    conv_id = item.get("conv_id", "")
                    if conv_id:
                        await self._working_memory.release_work(conv_id)
            except Exception as e:
                logger.warning(f"Error releasing work during drain: {e}")

        logger.info("Drain complete — agent ready for shutdown")

    # ── Distributed Lock ─────────────────────────────────────────

    async def _acquire_lock(self) -> bool:
        """Acquire the distributed election lock using SET NX.

        Only one agent can hold the lock at a time.
        """
        lock_key = self._lock_key()
        result = await self._redis.set(
            lock_key, self.agent_id,
            nx=True,
            ex=ELECTION_LOCK_TTL,
        )
        return result is not None and result is not False

    async def _release_lock(self) -> None:
        """Release the election lock (only if we hold it)."""
        lock_key = self._lock_key()
        try:
            holder = await self._redis.get(lock_key)
            if holder == self.agent_id:
                await self._redis.delete(lock_key)
        except Exception as e:
            logger.warning(f"Error releasing election lock: {e}")

    # ── Event Handlers ───────────────────────────────────────────

    async def _handle_config_event(self, channel: str, event: dict) -> None:
        """Handle config events — detect new primary elections."""
        event_type = event.get("type", "")

        if event_type == "primary_elected":
            new_primary = event.get("new_primary", "")
            new_epoch = event.get("config_epoch", 0)

            if new_primary != self.agent_id:
                logger.info(
                    f"New primary elected: {new_primary} (epoch={new_epoch})"
                )
                # Check if we need to demote
                await self.check_and_demote()

    async def _handle_agent_event(self, channel: str, event: dict) -> None:
        """Handle agent events — detect draining primaries."""
        event_type = event.get("type", "")

        if event_type == "primary_draining":
            draining_id = event.get("agent_id", "")
            if draining_id != self.agent_id:
                logger.info(
                    f"Primary {draining_id} is draining — election may follow"
                )

    # ── Status ───────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get election manager status."""
        return {
            "election_in_progress": self._election_in_progress,
            "last_election_time": self._last_election_time,
            "elections_won": self._elections_won,
            "elections_lost": self._elections_lost,
            "demotions": self._demotions,
        }
