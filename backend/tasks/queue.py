"""Async task queue for background research and maintenance."""

import asyncio
import logging
import uuid

logger = logging.getLogger("nexus.tasks")


class TaskQueue:
    """Simple async task queue using asyncio — no Redis/Celery needed."""

    def __init__(self, db, max_concurrent: int = 3):
        self.db = db
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: dict = {}
        self._handlers: dict = {}

    def register_handler(self, task_type: str, handler: callable):
        """Register an async handler function for a task type."""
        self._handlers[task_type] = handler
        logger.info(f"Registered task handler: {task_type}")

    async def submit(self, task_type: str, payload: dict = None) -> dict:
        """Submit a new task for background processing."""
        task_id = f"task-{uuid.uuid4().hex[:8]}"

        if task_type not in self._handlers:
            raise ValueError(f"Unknown task type: {task_type}")

        # Record in DB
        task_record = await self.db.create_task(task_id, task_type, payload)

        # Launch background execution
        asyncio_task = asyncio.create_task(self._execute(task_id, task_type, payload))
        self._running_tasks[task_id] = asyncio_task

        logger.info(f"Submitted task {task_id} ({task_type})")
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

            except asyncio.CancelledError:
                await self.db.update_task(task_id, "cancelled")
                logger.info(f"Cancelled task {task_id}")

            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}")
                await self.db.update_task(task_id, "failed", error=str(e))

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
