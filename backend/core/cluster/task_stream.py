"""Task Stream — Redis Streams–based distributed task queue.

Three priority streams:
    nexus:tasks:high     — abort signals, urgent failover tasks
    nexus:tasks:normal   — standard conversations, sub-agents, plans
    nexus:tasks:low      — background research, maintenance, reminders

Consumer Group: nexus:workers
    Each agent joins as a consumer identified by agent_id.
    Tasks claimed via XREADGROUP, processed, then XACK'd.
    Unclaimed tasks after timeout are auto-reassigned (pending entries list).

Dead Letter: nexus:tasks:dead
    Tasks that fail after max_retries attempts are moved here for inspection.

Result Store: nexus:result:{task_id}
    Task results are stored as Redis keys with a TTL for the orchestrator
    to collect after completion.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("nexus.cluster.task_stream")

# Type alias for task handlers
TaskHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, Any]]

PRIORITIES = ("high", "normal", "low")
DEFAULT_GROUP = "nexus:workers"
RESULT_TTL = 3600  # 1 hour TTL for result keys
MAX_RETRIES = 3
CLAIM_TIMEOUT_MS = 60_000  # 60 seconds before a task can be reclaimed


@dataclass
class TaskMessage:
    """Parsed task from a Redis Stream message."""

    task_id: str
    stream_id: str  # Redis stream message ID (e.g., "1739456789-0")
    priority: str
    task_type: str
    payload: dict[str, Any]
    conv_id: str = ""
    user_id: str = ""
    model_hint: str = ""
    parent_id: str = ""
    role: str = ""
    max_tokens: int = 4096
    timeout_ms: int = 60_000
    created_at: int = 0
    attempt: int = 0

    @classmethod
    def from_stream(cls, stream_id: str, data: dict, priority: str) -> "TaskMessage":
        """Parse a Redis stream message into a TaskMessage."""
        payload = {}
        try:
            payload = json.loads(data.get("payload", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass

        return cls(
            task_id=data.get("task_id", ""),
            stream_id=stream_id,
            priority=priority,
            task_type=data.get("type", ""),
            payload=payload,
            conv_id=data.get("conv_id", ""),
            user_id=data.get("user_id", ""),
            model_hint=data.get("model_hint", ""),
            parent_id=data.get("parent_id", ""),
            role=data.get("role", ""),
            max_tokens=int(data.get("max_tokens", 4096)),
            timeout_ms=int(data.get("timeout_ms", 60000)),
            created_at=int(data.get("created_at", 0)),
            attempt=int(data.get("attempt", 0)),
        )


class TaskStream:
    """Redis Streams–based distributed task queue.

    Usage:
        stream = TaskStream(redis, prefix="nexus:", agent_id="nexus-01")
        await stream.start()

        # Register handlers
        stream.register_handler("research", handle_research)
        stream.register_handler("sub_agent", handle_sub_agent)

        # Publish a task
        task_id = await stream.publish(
            task_type="research",
            payload={"topic": "market analysis"},
            priority="normal",
        )

        # Wait for result
        result = await stream.await_result(task_id, timeout=60)

        await stream.stop()
    """

    def __init__(
        self,
        redis,
        prefix: str,
        agent_id: str,
        consumer_group: str = DEFAULT_GROUP,
    ):
        self._redis = redis
        self._prefix = prefix
        self.agent_id = agent_id
        self.consumer_group = consumer_group

        # Task handlers by type
        self._handlers: dict[str, TaskHandler] = {}

        # Worker state
        self._worker_task: Optional[asyncio.Task] = None
        self._claim_task: Optional[asyncio.Task] = None
        self._stopped = False

        # Stats
        self._published = 0
        self._consumed = 0
        self._completed = 0
        self._failed = 0
        self._dead_lettered = 0

    # ── Key helpers ──────────────────────────────────────────────

    def _stream_key(self, priority: str) -> str:
        return f"{self._prefix}tasks:{priority}"

    def _result_key(self, task_id: str) -> str:
        return f"{self._prefix}result:{task_id}"

    def _dead_letter_key(self) -> str:
        return f"{self._prefix}tasks:dead"

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Create consumer groups and start worker + claim loops."""
        # Ensure consumer groups exist on all priority streams
        for priority in PRIORITIES:
            key = self._stream_key(priority)
            try:
                await self._redis.xgroup_create(
                    key, self.consumer_group, id="0", mkstream=True
                )
                logger.debug(f"Created consumer group on {key}")
            except Exception as e:
                # Group already exists — fine
                if "BUSYGROUP" not in str(e):
                    logger.warning(f"Error creating group on {key}: {e}")

        # Start worker loop
        self._worker_task = asyncio.create_task(self._worker_loop())

        # Start abandoned task claimer
        self._claim_task = asyncio.create_task(self._claim_loop())

        logger.info(
            f"Task stream started: agent={self.agent_id} "
            f"group={self.consumer_group} handlers={list(self._handlers.keys())}"
        )

    async def stop(self) -> None:
        """Stop worker and claim loops."""
        self._stopped = True

        for task in [self._worker_task, self._claim_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        logger.info(
            f"Task stream stopped: published={self._published} "
            f"consumed={self._consumed} completed={self._completed} "
            f"failed={self._failed} dead={self._dead_lettered}"
        )

    def register_handler(self, task_type: str, handler: TaskHandler) -> None:
        """Register a handler for a task type."""
        self._handlers[task_type] = handler
        logger.debug(f"Registered task handler: {task_type}")

    # ── Publish ──────────────────────────────────────────────────

    async def publish(
        self,
        task_type: str,
        payload: dict[str, Any] = None,
        priority: str = "normal",
        conv_id: str = "",
        user_id: str = "",
        model_hint: str = "",
        parent_id: str = "",
        role: str = "",
        max_tokens: int = 4096,
        timeout_ms: int = 60_000,
    ) -> str:
        """Publish a task to the stream.

        Returns the task_id (not the Redis stream message ID).
        """
        task_id = f"task-{uuid.uuid4().hex[:12]}"

        message = {
            "task_id": task_id,
            "type": task_type,
            "payload": json.dumps(payload or {}),
            "conv_id": conv_id,
            "user_id": user_id,
            "model_hint": model_hint,
            "parent_id": parent_id,
            "role": role,
            "max_tokens": str(max_tokens),
            "timeout_ms": str(timeout_ms),
            "created_at": str(int(time.time())),
            "attempt": "0",
            "publisher": self.agent_id,
        }

        key = self._stream_key(priority)
        stream_id = await self._redis.xadd(key, message)

        self._published += 1
        logger.info(
            f"Published task {task_id} ({task_type}) to {priority} "
            f"stream_id={stream_id}"
        )

        return task_id

    # ── Consume ──────────────────────────────────────────────────

    async def _worker_loop(self) -> None:
        """Background loop: read tasks from streams and process them."""
        # Read from all priority streams, high first
        streams = {self._stream_key(p): ">" for p in PRIORITIES}

        while not self._stopped:
            try:
                # Block-read with 2 second timeout
                messages = await self._redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.agent_id,
                    streams=streams,
                    count=1,  # Process one at a time for fairness
                    block=2000,
                )

                if not messages:
                    continue

                for stream_key, msg_list in messages:
                    # Determine priority from stream key
                    if isinstance(stream_key, bytes):
                        stream_key = stream_key.decode("utf-8")
                    priority = stream_key.split(":")[-1]

                    for stream_id, data in msg_list:
                        if isinstance(stream_id, bytes):
                            stream_id = stream_id.decode("utf-8")
                        # Decode bytes values
                        decoded = {}
                        for k, v in data.items():
                            k = k.decode("utf-8") if isinstance(k, bytes) else k
                            v = v.decode("utf-8") if isinstance(v, bytes) else v
                            decoded[k] = v

                        task = TaskMessage.from_stream(stream_id, decoded, priority)
                        self._consumed += 1

                        # Process in background so we can continue reading
                        asyncio.create_task(
                            self._process_task(task)
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Worker loop error: {e}")
                try:
                    await asyncio.sleep(2)
                except asyncio.CancelledError:
                    break

    async def _process_task(self, task: TaskMessage) -> None:
        """Execute a task and store result / acknowledge."""
        handler = self._handlers.get(task.task_type)
        if not handler:
            logger.warning(
                f"No handler for task type '{task.task_type}' "
                f"(task_id={task.task_id})"
            )
            # ACK anyway to prevent redelivery of unknown types
            await self._ack(task)
            return

        try:
            logger.info(f"Processing task {task.task_id} ({task.task_type})")

            # Execute with timeout
            timeout_s = task.timeout_ms / 1000
            result = await asyncio.wait_for(
                handler(task.payload),
                timeout=timeout_s,
            )

            # Store result
            await self._store_result(task.task_id, {
                "status": "completed",
                "result": result if isinstance(result, (str, dict, list)) else str(result),
                "agent_id": self.agent_id,
                "completed_at": int(time.time()),
            })

            # Acknowledge
            await self._ack(task)
            self._completed += 1

            logger.info(f"Completed task {task.task_id}")

        except asyncio.TimeoutError:
            logger.warning(f"Task {task.task_id} timed out after {task.timeout_ms}ms")
            await self._handle_failure(task, "timeout")

        except Exception as e:
            logger.error(f"Task {task.task_id} failed: {e}")
            await self._handle_failure(task, str(e))

    async def _ack(self, task: TaskMessage) -> None:
        """Acknowledge a task (remove from pending entries list)."""
        key = self._stream_key(task.priority)
        try:
            await self._redis.xack(key, self.consumer_group, task.stream_id)
        except Exception as e:
            logger.warning(f"ACK failed for {task.task_id}: {e}")

    async def _handle_failure(self, task: TaskMessage, error: str) -> None:
        """Handle a failed task — retry or dead letter."""
        self._failed += 1
        attempt = task.attempt + 1

        if attempt >= MAX_RETRIES:
            # Dead letter
            await self._dead_letter(task, error)
            await self._ack(task)
            return

        # Store failure info and let the claim loop pick it up for retry
        # The task stays in the pending entries list (not ACK'd)
        await self._store_result(task.task_id, {
            "status": "failed",
            "error": error,
            "attempt": attempt,
            "agent_id": self.agent_id,
            "failed_at": int(time.time()),
        })

        logger.info(
            f"Task {task.task_id} failed (attempt {attempt}/{MAX_RETRIES}), "
            f"will be reclaimed"
        )

    async def _dead_letter(self, task: TaskMessage, error: str) -> None:
        """Move a task to the dead letter stream after max retries."""
        dead_key = self._dead_letter_key()

        message = {
            "task_id": task.task_id,
            "type": task.task_type,
            "payload": json.dumps(task.payload),
            "conv_id": task.conv_id,
            "user_id": task.user_id,
            "error": error,
            "attempts": str(task.attempt + 1),
            "original_priority": task.priority,
            "dead_at": str(int(time.time())),
            "last_agent": self.agent_id,
        }

        await self._redis.xadd(dead_key, message)
        self._dead_lettered += 1

        logger.warning(
            f"Dead-lettered task {task.task_id} after {task.attempt + 1} attempts: {error}"
        )

    # ── Claim abandoned tasks ────────────────────────────────────

    async def _claim_loop(self) -> None:
        """Periodically check for abandoned tasks and reclaim them.

        Uses XAUTOCLAIM to find tasks that have been pending for too long
        (the original consumer died or timed out).
        """
        while not self._stopped:
            try:
                for priority in PRIORITIES:
                    key = self._stream_key(priority)
                    try:
                        # XAUTOCLAIM: reclaim messages idle for > CLAIM_TIMEOUT_MS
                        result = await self._redis.xautoclaim(
                            key,
                            self.consumer_group,
                            self.agent_id,
                            min_idle_time=CLAIM_TIMEOUT_MS,
                            start_id="0-0",
                            count=5,
                        )

                        if result and len(result) >= 2:
                            claimed_messages = result[1]
                            if claimed_messages:
                                for stream_id, data in claimed_messages:
                                    if isinstance(stream_id, bytes):
                                        stream_id = stream_id.decode("utf-8")
                                    decoded = {}
                                    for k, v in data.items():
                                        k = k.decode("utf-8") if isinstance(k, bytes) else k
                                        v = v.decode("utf-8") if isinstance(v, bytes) else v
                                        decoded[k] = v

                                    # Increment attempt counter
                                    attempt = int(decoded.get("attempt", 0)) + 1
                                    decoded["attempt"] = str(attempt)

                                    task = TaskMessage.from_stream(
                                        stream_id, decoded, priority
                                    )

                                    logger.info(
                                        f"Reclaimed abandoned task {task.task_id} "
                                        f"(attempt {attempt})"
                                    )

                                    asyncio.create_task(self._process_task(task))

                    except Exception as e:
                        # XAUTOCLAIM might not be available on older Redis
                        if "unknown command" in str(e).lower():
                            logger.debug("XAUTOCLAIM not available, skipping claim loop")
                            return
                        logger.warning(f"Claim error on {priority}: {e}")

                # Check every 30 seconds
                await asyncio.sleep(30)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Claim loop error: {e}")
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    break

    # ── Results ──────────────────────────────────────────────────

    async def _store_result(self, task_id: str, result: dict) -> None:
        """Store a task result in Redis with TTL."""
        key = self._result_key(task_id)
        await self._redis.set(key, json.dumps(result), ex=RESULT_TTL)

    async def get_result(self, task_id: str) -> Optional[dict]:
        """Get a task result (if available)."""
        key = self._result_key(task_id)
        data = await self._redis.get(key)
        if data:
            return json.loads(data)
        return None

    async def await_result(
        self, task_id: str, timeout: float = 60, poll_interval: float = 0.5
    ) -> Optional[dict]:
        """Wait for a task result with polling.

        Args:
            task_id: The task to wait for
            timeout: Max seconds to wait
            poll_interval: Seconds between polls

        Returns:
            Result dict or None if timed out.
        """
        deadline = time.time() + timeout

        while time.time() < deadline:
            result = await self.get_result(task_id)
            if result and result.get("status") in ("completed", "failed"):
                return result

            try:
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                return None

        logger.warning(f"Timed out waiting for task {task_id} result")
        return None

    async def await_results(
        self, task_ids: list[str], timeout: float = 60
    ) -> dict[str, Optional[dict]]:
        """Wait for multiple task results concurrently.

        Returns a dict mapping task_id → result (or None if timed out).
        """
        async def _wait_one(tid: str):
            return tid, await self.await_result(tid, timeout=timeout)

        results_list = await asyncio.gather(
            *[_wait_one(tid) for tid in task_ids],
            return_exceptions=True,
        )

        results = {}
        for item in results_list:
            if isinstance(item, Exception):
                continue
            tid, result = item
            results[tid] = result

        return results

    # ── Stream Info ──────────────────────────────────────────────

    async def get_stream_info(self) -> dict[str, Any]:
        """Get info about all task streams (lengths, pending, etc.)."""
        info = {}

        for priority in PRIORITIES:
            key = self._stream_key(priority)
            try:
                length = await self._redis.xlen(key)
                pending = 0
                try:
                    pending_info = await self._redis.xpending(
                        key, self.consumer_group
                    )
                    if pending_info:
                        pending = pending_info.get("pending", 0) if isinstance(pending_info, dict) else (pending_info[0] if pending_info else 0)
                except Exception:
                    pass

                info[priority] = {
                    "length": length,
                    "pending": pending,
                }
            except Exception as e:
                info[priority] = {"length": 0, "pending": 0, "error": str(e)}

        # Dead letter count
        try:
            dead_len = await self._redis.xlen(self._dead_letter_key())
        except Exception:
            dead_len = 0

        info["dead_letter"] = {"length": dead_len}

        return info

    async def get_dead_letters(self, count: int = 20) -> list[dict]:
        """Get recent dead letter entries for inspection."""
        key = self._dead_letter_key()
        try:
            # Read last N entries (newest first)
            messages = await self._redis.xrevrange(key, count=count)
            results = []
            for stream_id, data in messages:
                if isinstance(stream_id, bytes):
                    stream_id = stream_id.decode("utf-8")
                decoded = {"stream_id": stream_id}
                for k, v in data.items():
                    k = k.decode("utf-8") if isinstance(k, bytes) else k
                    v = v.decode("utf-8") if isinstance(v, bytes) else v
                    decoded[k] = v
                results.append(decoded)
            return results
        except Exception:
            return []

    def get_stats(self) -> dict[str, int]:
        """Return task stream statistics."""
        return {
            "published": self._published,
            "consumed": self._consumed,
            "completed": self._completed,
            "failed": self._failed,
            "dead_lettered": self._dead_lettered,
            "handler_types": list(self._handlers.keys()),
        }
