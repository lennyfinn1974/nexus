"""User reminder / scheduled notification system.

Allows users to set reminders via chat:
  "remind me in 30 minutes to check the build"
  "remind me tomorrow at 9am to review the PR"
  "remind me every day at 10am to check metrics"

Reminders are stored in-memory with optional DB persistence.
The reminder loop runs as part of the TaskQueue scheduler.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger("nexus.reminders")


@dataclass
class Reminder:
    id: str
    message: str
    trigger_at: datetime
    conv_id: str = ""
    recurring: bool = False
    interval_seconds: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fired: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "message": self.message,
            "trigger_at": self.trigger_at.isoformat(),
            "conv_id": self.conv_id,
            "recurring": self.recurring,
            "interval_seconds": self.interval_seconds,
            "created_at": self.created_at.isoformat(),
            "fired": self.fired,
        }


class ReminderManager:
    """Manages user reminders with a background check loop."""

    def __init__(self, on_fire: Optional[Callable] = None):
        """
        Args:
            on_fire: Async callback when a reminder fires.
                     Signature: async (reminder: Reminder) -> None
        """
        self._reminders: dict[str, Reminder] = {}
        self._on_fire = on_fire
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self):
        """Start the reminder check loop."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._check_loop())
            logger.info("Reminder manager started")

    def stop(self):
        """Stop the reminder check loop."""
        self._running = False
        if self._task:
            self._task.cancel()

    async def _check_loop(self):
        """Background loop — checks every 15 seconds for due reminders."""
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                for reminder in list(self._reminders.values()):
                    if reminder.fired and not reminder.recurring:
                        continue
                    if now >= reminder.trigger_at:
                        await self._fire(reminder)
                await asyncio.sleep(15)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Reminder loop error: {e}")
                await asyncio.sleep(30)

    async def _fire(self, reminder: Reminder):
        """Fire a reminder — invoke callback and handle recurrence."""
        logger.info(f"Reminder fired: {reminder.id} - {reminder.message}")
        reminder.fired = True
        try:
            from core.work_registry import work_registry
            await work_registry.update(reminder.id, "completed")
        except Exception:
            pass

        if self._on_fire:
            try:
                await self._on_fire(reminder)
            except Exception as e:
                logger.error(f"Reminder callback failed: {e}")

        if reminder.recurring and reminder.interval_seconds > 0:
            # Reschedule for next occurrence
            reminder.trigger_at = datetime.now(timezone.utc) + timedelta(seconds=reminder.interval_seconds)
            reminder.fired = False
            logger.info(f"Recurring reminder {reminder.id} rescheduled for {reminder.trigger_at}")
        else:
            # One-shot — remove after firing
            self._reminders.pop(reminder.id, None)

    def add(
        self,
        message: str,
        trigger_at: datetime,
        conv_id: str = "",
        recurring: bool = False,
        interval_seconds: int = 0,
    ) -> Reminder:
        """Add a new reminder."""
        reminder_id = f"rem-{uuid.uuid4().hex[:8]}"
        reminder = Reminder(
            id=reminder_id,
            message=message,
            trigger_at=trigger_at,
            conv_id=conv_id,
            recurring=recurring,
            interval_seconds=interval_seconds,
        )
        self._reminders[reminder_id] = reminder
        logger.info(f"Reminder added: {reminder_id} at {trigger_at} — '{message}'")
        try:
            import asyncio as _aio
            loop = _aio.get_running_loop()
            from core.work_registry import work_registry
            loop.create_task(work_registry.register(
                reminder_id, "reminder", message,
                status="pending", conv_id=conv_id,
                metadata={"trigger_at": trigger_at.isoformat(), "recurring": recurring},
            ))
        except RuntimeError:
            pass
        return reminder

    def cancel(self, reminder_id: str) -> bool:
        """Cancel a reminder."""
        if reminder_id in self._reminders:
            del self._reminders[reminder_id]
            logger.info(f"Reminder cancelled: {reminder_id}")
            try:
                import asyncio as _aio
                loop = _aio.get_running_loop()
                from core.work_registry import work_registry
                loop.create_task(work_registry.update(reminder_id, "cancelled"))
            except RuntimeError:
                pass
            return True
        return False

    def list_active(self) -> list[dict]:
        """List all active (non-fired) reminders."""
        now = datetime.now(timezone.utc)
        return [
            r.to_dict()
            for r in sorted(self._reminders.values(), key=lambda r: r.trigger_at)
            if not r.fired or r.recurring
        ]

    def parse_and_add(self, text: str, conv_id: str = "") -> Optional[Reminder]:
        """Parse natural language reminder text and create a reminder.

        Supports:
          "in 30 minutes" / "in 2 hours" / "in 1 day"
          "tomorrow at 9am"
          "every day at 10am"
          "every 4 hours"

        Returns None if text doesn't match any pattern.
        """
        text_lower = text.lower().strip()
        now = datetime.now(timezone.utc)

        # "in X minutes/hours/days"
        match = re.search(r"in\s+(\d+)\s+(minute|hour|day|second)s?", text_lower)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            delta = {
                "second": timedelta(seconds=amount),
                "minute": timedelta(minutes=amount),
                "hour": timedelta(hours=amount),
                "day": timedelta(days=amount),
            }.get(unit, timedelta(minutes=amount))

            # Extract message (everything after the time spec)
            msg = text_lower.split(match.group(0))[-1].strip()
            msg = re.sub(r"^(to|that|about)\s+", "", msg).strip()
            if not msg:
                msg = "Reminder"

            return self.add(msg, now + delta, conv_id=conv_id)

        # "every X hours/minutes"
        match = re.search(r"every\s+(\d+)\s+(minute|hour|day)s?", text_lower)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            interval = {
                "minute": 60 * amount,
                "hour": 3600 * amount,
                "day": 86400 * amount,
            }.get(unit, 3600 * amount)

            msg = text_lower.split(match.group(0))[-1].strip()
            msg = re.sub(r"^(to|that|about)\s+", "", msg).strip()
            if not msg:
                msg = "Recurring reminder"

            return self.add(
                msg,
                now + timedelta(seconds=interval),
                conv_id=conv_id,
                recurring=True,
                interval_seconds=interval,
            )

        return None
