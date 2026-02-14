"""Async task queue for background research and maintenance.

Supports both one-shot tasks (submit) and periodic tasks (schedule).
Periodic tasks run at fixed intervals using asyncio — no APScheduler needed.

When clustering is enabled (set_task_stream called), tasks are published
to Redis Streams for distributed execution across the agent cluster.
Local handlers are still registered — they run on whichever agent claims
the task from the stream.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("nexus.tasks")


@dataclass
class PeriodicTask:
    """A recurring task definition."""
    task_type: str
    interval_seconds: int
    payload: dict
    enabled: bool = True
    last_run: float = 0.0
    run_count: int = 0
    last_error: str = ""


class TaskQueue:
    """Simple async task queue using asyncio — no Redis/Celery needed.

    Features:
    - One-shot tasks via submit()
    - Periodic/scheduled tasks via register_periodic()
    - Concurrency-limited execution via semaphore
    - Background scheduler loop for periodic tasks
    """

    def __init__(self, db, max_concurrent: int = 3):
        self.db = db
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: dict = {}
        self._handlers: dict = {}
        self._periodic: dict[str, PeriodicTask] = {}
        self._scheduler_task: Optional[asyncio.Task] = None
        self._shutdown = False
        self._task_stream = None  # Set when clustering enabled

    def set_task_stream(self, task_stream) -> None:
        """Connect to a distributed TaskStream for clustered execution.

        When set, submit() publishes to Redis Streams instead of
        running locally. Handlers are still registered locally so
        this agent can consume tasks from the stream.
        """
        self._task_stream = task_stream
        # Register all existing handlers on the stream too
        for task_type, handler in self._handlers.items():
            task_stream.register_handler(task_type, handler)
        logger.info(f"TaskQueue connected to distributed TaskStream")

    @property
    def is_distributed(self) -> bool:
        """True when tasks are being distributed via Redis Streams."""
        return self._task_stream is not None

    def register_handler(self, task_type: str, handler: callable):
        """Register an async handler function for a task type."""
        self._handlers[task_type] = handler
        # Also register on stream if connected
        if self._task_stream:
            self._task_stream.register_handler(task_type, handler)
        logger.info(f"Registered task handler: {task_type}")

    def register_periodic(
        self,
        name: str,
        task_type: str,
        interval_seconds: int,
        payload: dict = None,
        enabled: bool = True,
    ):
        """Register a periodic task that runs at a fixed interval.

        Args:
            name: Unique name for this scheduled task
            task_type: The handler type to invoke
            interval_seconds: How often to run (in seconds)
            payload: Arguments to pass to the handler
            enabled: Whether the task starts enabled
        """
        self._periodic[name] = PeriodicTask(
            task_type=task_type,
            interval_seconds=interval_seconds,
            payload=payload or {},
            enabled=enabled,
        )
        logger.info(f"Registered periodic task: {name} (every {interval_seconds}s, type={task_type})")

    def start_scheduler(self):
        """Start the background scheduler loop for periodic tasks."""
        if self._scheduler_task is None or self._scheduler_task.done():
            self._shutdown = False
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
            logger.info("Periodic task scheduler started")

    def stop_scheduler(self):
        """Stop the background scheduler."""
        self._shutdown = True
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            logger.info("Periodic task scheduler stopped")

    async def _scheduler_loop(self):
        """Background loop that checks and runs periodic tasks."""
        logger.info("Scheduler loop running")
        while not self._shutdown:
            try:
                now = time.time()
                for name, pt in self._periodic.items():
                    if not pt.enabled:
                        continue
                    if now - pt.last_run >= pt.interval_seconds:
                        pt.last_run = now
                        try:
                            await self.submit(pt.task_type, pt.payload)
                            pt.run_count += 1
                            pt.last_error = ""
                            logger.debug(f"Periodic task '{name}' submitted (run #{pt.run_count})")
                        except Exception as e:
                            pt.last_error = str(e)
                            logger.error(f"Periodic task '{name}' submission failed: {e}")

                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(60)

    def get_periodic_status(self) -> list[dict]:
        """Return status of all periodic tasks."""
        return [
            {
                "name": name,
                "task_type": pt.task_type,
                "interval_seconds": pt.interval_seconds,
                "enabled": pt.enabled,
                "run_count": pt.run_count,
                "last_run": pt.last_run,
                "last_error": pt.last_error,
            }
            for name, pt in self._periodic.items()
        ]

    async def submit(
        self,
        task_type: str,
        payload: dict = None,
        priority: str = "normal",
        conv_id: str = "",
        user_id: str = "",
    ) -> dict:
        """Submit a new task for background processing.

        When clustering is active, publishes to Redis Streams for
        distributed execution. Otherwise runs locally via asyncio.
        """
        task_id = f"task-{uuid.uuid4().hex[:8]}"

        if task_type not in self._handlers:
            raise ValueError(f"Unknown task type: {task_type}")

        # Record in DB
        task_record = await self.db.create_task(task_id, task_type, payload)

        # Distributed path: publish to Redis Streams
        if self._task_stream:
            stream_task_id = await self._task_stream.publish(
                task_type=task_type,
                payload=payload or {},
                priority=priority,
                conv_id=conv_id,
                user_id=user_id,
            )
            logger.info(f"Submitted task {task_id} → stream (distributed, stream_id={stream_task_id})")
        else:
            # Local path: execute in-process
            asyncio_task = asyncio.create_task(self._execute(task_id, task_type, payload))
            self._running_tasks[task_id] = asyncio_task
            logger.info(f"Submitted task {task_id} ({task_type}) [local]")

        try:
            from core.work_registry import work_registry
            await work_registry.register(
                task_id, "task", task_type,
                status="pending", metadata=payload,
            )
        except Exception:
            pass
        return task_record

    async def _execute(self, task_id: str, task_type: str, payload: dict):
        """Execute a task with concurrency control."""
        async with self._semaphore:
            try:
                await self.db.update_task(task_id, "running")
                logger.info(f"Running task {task_id}")

                handler = self._handlers[task_type]
                result = await handler(payload)

                await self.db.update_task(task_id, "completed", result=str(result) if result else None)
                logger.info(f"Completed task {task_id}")
                try:
                    from core.work_registry import work_registry
                    await work_registry.update(task_id, "completed")
                except Exception:
                    pass

            except asyncio.CancelledError:
                await self.db.update_task(task_id, "cancelled")
                logger.info(f"Cancelled task {task_id}")

            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}")
                await self.db.update_task(task_id, "failed", error=str(e))
                try:
                    from core.work_registry import work_registry
                    await work_registry.update(task_id, "failed", {"error": str(e)})
                except Exception:
                    pass

            finally:
                self._running_tasks.pop(task_id, None)

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running task."""
        if task_id in self._running_tasks:
            self._running_tasks[task_id].cancel()
            return True
        return False

    async def list_tasks(self, status: str = None) -> list:
        return await self.db.list_tasks(status)

    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
