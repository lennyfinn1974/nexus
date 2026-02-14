"""Working Memory — Redis JSON session state for cross-agent context.

Provides sub-millisecond access to hot session data that all agents need:
    - Conversation context (recent messages, tool results, model state)
    - User session state (current project, preferences, active goals)
    - Agent coordination state (who's working on what)

Storage format:
    nexus:session:{conv_id}  → JSON object with TTL
    nexus:context:{conv_id}  → Compact context snapshot for handoff
    nexus:agent_work:{agent_id} → Current work assignments

All keys have TTLs — working memory is ephemeral by design.
Long-term persistence lives in PostgreSQL; this layer is for speed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("nexus.cluster.working_memory")

# Default TTLs
SESSION_TTL = 3600       # 1 hour for active sessions
CONTEXT_TTL = 7200       # 2 hours for context snapshots
WORK_TTL = 1800          # 30 minutes for work assignments
PROMOTION_DELAY = 300    # 5 minutes before promoting to long-term


class WorkingMemory:
    """Redis-backed working memory for cross-agent session state.

    Usage:
        wm = WorkingMemory(redis, prefix="nexus:", agent_id="nexus-01")

        # Store session state
        await wm.set_session("conv-123", {
            "model": "kimi-k2.5",
            "messages_count": 15,
            "last_tool": "web_fetch",
            "active_plan": {"id": "plan-abc", "step": 3},
        })

        # Retrieve from any agent
        session = await wm.get_session("conv-123")

        # Store context snapshot for handoff
        await wm.set_context("conv-123", {
            "summary": "User is building a React dashboard...",
            "preferences": {"model": "local", "verbose": True},
            "active_tools": ["web_fetch", "file_read"],
        })
    """

    def __init__(
        self,
        redis,
        prefix: str,
        agent_id: str,
        session_ttl: int = SESSION_TTL,
        context_ttl: int = CONTEXT_TTL,
        promotion_delay: int = PROMOTION_DELAY,
    ):
        self._redis = redis
        self._prefix = prefix
        self.agent_id = agent_id
        self.session_ttl = session_ttl
        self.context_ttl = context_ttl
        self.promotion_delay = promotion_delay

        # Promotion queue: items waiting to be promoted to long-term memory
        self._promotion_queue: list[dict] = []
        self._promotion_task: Optional[asyncio.Task] = None
        self._stopped = False

        # Stats
        self._reads = 0
        self._writes = 0
        self._promotions = 0
        self._evictions = 0

    # ── Key helpers ──────────────────────────────────────────────

    def _session_key(self, conv_id: str) -> str:
        return f"{self._prefix}session:{conv_id}"

    def _context_key(self, conv_id: str) -> str:
        return f"{self._prefix}context:{conv_id}"

    def _work_key(self, agent_id: str = None) -> str:
        return f"{self._prefix}agent_work:{agent_id or self.agent_id}"

    def _all_sessions_key(self) -> str:
        """Sorted set tracking all active session IDs by last access time."""
        return f"{self._prefix}sessions:active"

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the promotion background loop."""
        self._promotion_task = asyncio.create_task(self._promotion_loop())
        logger.info(
            f"Working memory started: agent={self.agent_id} "
            f"session_ttl={self.session_ttl}s context_ttl={self.context_ttl}s"
        )

    async def stop(self) -> None:
        """Stop the promotion loop and flush pending promotions."""
        self._stopped = True
        if self._promotion_task and not self._promotion_task.done():
            self._promotion_task.cancel()
            try:
                await self._promotion_task
            except asyncio.CancelledError:
                pass

        logger.info(
            f"Working memory stopped: reads={self._reads} writes={self._writes} "
            f"promotions={self._promotions} evictions={self._evictions}"
        )

    # ── Session CRUD ─────────────────────────────────────────────

    async def set_session(
        self, conv_id: str, data: dict[str, Any], ttl: int = None
    ) -> None:
        """Store or update session state for a conversation.

        Args:
            conv_id: Conversation ID
            data: Session state dict (must be JSON-serializable)
            ttl: Optional custom TTL in seconds
        """
        key = self._session_key(conv_id)
        now = int(time.time())

        # Add metadata
        data["_updated_at"] = now
        data["_agent_id"] = self.agent_id
        data["_conv_id"] = conv_id

        payload = json.dumps(data)
        effective_ttl = ttl or self.session_ttl

        pipe = self._redis.pipeline()
        pipe.set(key, payload, ex=effective_ttl)
        # Track in active sessions sorted set (score = timestamp)
        pipe.zadd(self._all_sessions_key(), {conv_id: now})
        await pipe.execute()

        self._writes += 1
        logger.debug(f"Session stored: conv={conv_id} ttl={effective_ttl}s")

    async def get_session(self, conv_id: str) -> Optional[dict[str, Any]]:
        """Retrieve session state for a conversation.

        Returns None if the session has expired or doesn't exist.
        """
        key = self._session_key(conv_id)
        data = await self._redis.get(key)

        if data is None:
            return None

        self._reads += 1
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None

    async def update_session(
        self, conv_id: str, updates: dict[str, Any]
    ) -> bool:
        """Merge updates into an existing session.

        Returns True if the session existed and was updated.
        """
        existing = await self.get_session(conv_id)
        if existing is None:
            return False

        existing.update(updates)
        await self.set_session(conv_id, existing)
        return True

    async def delete_session(self, conv_id: str) -> None:
        """Delete a session (e.g., conversation ended)."""
        key = self._session_key(conv_id)
        pipe = self._redis.pipeline()
        pipe.delete(key)
        pipe.zrem(self._all_sessions_key(), conv_id)
        await pipe.execute()

        self._evictions += 1
        logger.debug(f"Session deleted: conv={conv_id}")

    async def touch_session(self, conv_id: str) -> bool:
        """Refresh the TTL on a session (keep-alive).

        Returns True if the session exists.
        """
        key = self._session_key(conv_id)
        result = await self._redis.expire(key, self.session_ttl)

        if result:
            # Update last-access time in sorted set
            await self._redis.zadd(
                self._all_sessions_key(),
                {conv_id: int(time.time())}
            )
        return bool(result)

    # ── Context Snapshots ────────────────────────────────────────

    async def set_context(
        self, conv_id: str, context: dict[str, Any], ttl: int = None
    ) -> None:
        """Store a compact context snapshot for agent handoff.

        Context snapshots are lighter than full sessions — they contain
        just enough info for another agent to pick up the conversation.
        """
        key = self._context_key(conv_id)
        now = int(time.time())

        context["_created_at"] = now
        context["_source_agent"] = self.agent_id

        payload = json.dumps(context)
        effective_ttl = ttl or self.context_ttl

        await self._redis.set(key, payload, ex=effective_ttl)
        self._writes += 1

        logger.debug(f"Context snapshot stored: conv={conv_id}")

    async def get_context(self, conv_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a context snapshot for a conversation."""
        key = self._context_key(conv_id)
        data = await self._redis.get(key)

        if data is None:
            return None

        self._reads += 1
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None

    # ── Agent Work Tracking ──────────────────────────────────────

    async def claim_work(
        self, conv_id: str, task_type: str = "conversation"
    ) -> None:
        """Record that this agent is working on a conversation/task."""
        key = self._work_key()
        now = int(time.time())

        work = {
            "conv_id": conv_id,
            "task_type": task_type,
            "started_at": now,
            "agent_id": self.agent_id,
        }

        # Use hash to track multiple concurrent work items
        await self._redis.hset(key, conv_id, json.dumps(work))
        await self._redis.expire(key, WORK_TTL)

        logger.debug(f"Work claimed: conv={conv_id} type={task_type}")

    async def release_work(self, conv_id: str) -> None:
        """Release a work assignment (task finished)."""
        key = self._work_key()
        await self._redis.hdel(key, conv_id)
        logger.debug(f"Work released: conv={conv_id}")

    async def get_agent_work(self, agent_id: str = None) -> list[dict]:
        """Get all work assignments for an agent."""
        key = self._work_key(agent_id)
        data = await self._redis.hgetall(key)

        results = []
        for _, value in data.items():
            v = value.decode("utf-8") if isinstance(value, bytes) else value
            try:
                results.append(json.loads(v))
            except (json.JSONDecodeError, TypeError):
                pass

        return results

    async def find_agent_for_conv(self, conv_id: str) -> Optional[str]:
        """Find which agent is currently working on a conversation.

        Scans all agent work keys to find the owner.
        """
        pattern = f"{self._prefix}agent_work:*"
        async for key in self._redis.scan_iter(match=pattern, count=100):
            data = await self._redis.hget(key, conv_id)
            if data:
                d = data.decode("utf-8") if isinstance(data, bytes) else data
                try:
                    work = json.loads(d)
                    return work.get("agent_id")
                except (json.JSONDecodeError, TypeError):
                    pass
        return None

    # ── Active Sessions ──────────────────────────────────────────

    async def get_active_sessions(self, limit: int = 50) -> list[dict]:
        """Get all active sessions sorted by last access (newest first).

        Returns a list of {conv_id, last_access, age_seconds} dicts.
        """
        key = self._all_sessions_key()
        now = int(time.time())

        # Get from sorted set (highest score = most recent)
        entries = await self._redis.zrevrange(
            key, 0, limit - 1, withscores=True
        )

        results = []
        for conv_id, score in entries:
            if isinstance(conv_id, bytes):
                conv_id = conv_id.decode("utf-8")
            results.append({
                "conv_id": conv_id,
                "last_access": int(score),
                "age_seconds": now - int(score),
            })

        return results

    async def count_active_sessions(self) -> int:
        """Count active sessions in working memory."""
        return await self._redis.zcard(self._all_sessions_key())

    # ── Promotion Pipeline ───────────────────────────────────────

    def queue_for_promotion(self, data: dict[str, Any]) -> None:
        """Add data to the promotion queue for eventual long-term storage.

        Data will be batched and promoted to PostgreSQL after
        the promotion delay (default 5 minutes).
        """
        self._promotion_queue.append({
            "data": data,
            "queued_at": time.time(),
            "content_hash": hashlib.sha256(
                json.dumps(data, sort_keys=True).encode()
            ).hexdigest()[:16],
        })

    async def _promotion_loop(self) -> None:
        """Background loop that promotes queued items to long-term storage.

        Items sit in the queue for `promotion_delay` seconds before
        being promoted. This debounces rapid updates.
        """
        while not self._stopped:
            try:
                now = time.time()
                ready = []
                remaining = []

                for item in self._promotion_queue:
                    age = now - item["queued_at"]
                    if age >= self.promotion_delay:
                        ready.append(item)
                    else:
                        remaining.append(item)

                self._promotion_queue = remaining

                if ready:
                    # Deduplicate by content hash
                    seen_hashes = set()
                    unique_items = []
                    for item in ready:
                        h = item["content_hash"]
                        if h not in seen_hashes:
                            seen_hashes.add(h)
                            unique_items.append(item)

                    for item in unique_items:
                        try:
                            await self._promote_item(item["data"])
                            self._promotions += 1
                        except Exception as e:
                            logger.warning(f"Promotion failed: {e}")

                    if unique_items:
                        logger.info(
                            f"Promoted {len(unique_items)} items to long-term memory "
                            f"(deduplicated from {len(ready)})"
                        )

                # Check every 30 seconds
                await asyncio.sleep(30)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Promotion loop error: {e}")
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    break

    async def _promote_item(self, data: dict[str, Any]) -> None:
        """Promote a single item to long-term storage.

        This is a hook point — the ClusterManager will wire this
        to the PersonalMemorySystem or PassiveMemoryExtractor for
        actual PostgreSQL persistence.
        """
        # Default: log and skip. Real promotion is wired externally.
        if self._promotion_callback:
            await self._promotion_callback(data)
        else:
            logger.debug(
                f"Promotion skipped (no callback): {data.get('type', 'unknown')}"
            )

    # Promotion callback — set by ClusterManager
    _promotion_callback = None

    def set_promotion_callback(self, callback) -> None:
        """Set the callback for promoting items to long-term storage.

        Args:
            callback: async def callback(data: dict) -> None
        """
        self._promotion_callback = callback
        logger.debug("Promotion callback registered")

    # ── Cleanup ──────────────────────────────────────────────────

    async def cleanup_stale_sessions(self, max_age: int = 7200) -> int:
        """Remove sessions from the active set that have expired.

        Returns the number of entries cleaned up.
        """
        key = self._all_sessions_key()
        cutoff = int(time.time()) - max_age

        # Remove entries with score < cutoff (older than max_age)
        removed = await self._redis.zremrangebyscore(key, "-inf", cutoff)

        if removed:
            self._evictions += removed
            logger.info(f"Cleaned up {removed} stale session entries")

        return removed

    # ── Stats ────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return working memory statistics."""
        return {
            "reads": self._reads,
            "writes": self._writes,
            "promotions": self._promotions,
            "evictions": self._evictions,
            "promotion_queue_size": len(self._promotion_queue),
        }
