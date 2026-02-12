"""Unified Work Registry — single source of truth for all active work items.

Aggregates: agent runs, sub-agent orchestrations, plans, tasks, and reminders
into a unified KanBan-compatible data model with real-time event emission
via SSE (admin UI) and WebSocket broadcast (chat UI).

Usage:
    from core.work_registry import work_registry

    # In app.py lifespan:
    work_registry.init(db, websocket_manager)

    # In any subsystem:
    await work_registry.register("agent-abc", "agent", "Process user query", "running", conv_id="...")
    await work_registry.update("agent-abc", "completed")
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("nexus.work_registry")


class WorkRegistry:
    """Maintains unified registry of all work items with real-time events.

    Acts as the single source of truth, aggregating agent runs, sub-agent
    orchestrations, plans, tasks, and reminders into one data model.

    In-memory cache holds active (non-terminal) items for fast reads.
    DB persistence ensures items survive restarts.
    SSE + WebSocket emission enables real-time UI updates.
    """

    def __init__(self):
        # In-memory cache of active items (mirrors DB for speed)
        self._items: dict[str, dict] = {}
        # SSE subscribers (asyncio.Queue per subscriber)
        self._sse_subscribers: list[asyncio.Queue] = []
        # Database reference (injected at startup)
        self._db: Any = None
        # WebSocket manager reference (injected at startup)
        self._ws_manager: Any = None
        self._initialized = False

    def init(self, db: Any, ws_manager: Any) -> None:
        """Called from app.py lifespan after DB is ready."""
        self._db = db
        self._ws_manager = ws_manager
        self._initialized = True
        logger.info("Work registry initialized")

    # ── Core Operations ──────────────────────────────────────────

    async def register(
        self,
        item_id: str,
        kind: str,
        title: str,
        status: str = "pending",
        parent_id: str = None,
        conv_id: str = None,
        model: str = None,
        metadata: dict = None,
    ) -> dict:
        """Register a new work item (or update if exists)."""
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "id": item_id,
            "kind": kind,
            "title": title,
            "status": status,
            "parent_id": parent_id,
            "conv_id": conv_id,
            "model": model,
            "metadata": metadata or {},
            "created_at": now,
            "started_at": now if status == "running" else None,
            "completed_at": None,
        }

        self._items[item_id] = item

        # Persist to DB (don't block caller on failure)
        if self._db:
            try:
                await self._db.upsert_work_item(
                    item_id, kind, title, status,
                    parent_id=parent_id, conv_id=conv_id,
                    model=model, metadata=metadata,
                )
            except Exception as e:
                logger.warning(f"WorkRegistry DB persist failed for {item_id}: {e}")

        # Emit event to SSE + WebSocket
        await self._emit(item, "registered")
        return item

    async def update(
        self,
        item_id: str,
        status: str,
        metadata_patch: dict = None,
    ) -> Optional[dict]:
        """Update a work item's status."""
        item = self._items.get(item_id)

        if not item:
            # Item not in cache — update DB directly (may have been evicted)
            if self._db:
                try:
                    await self._db.update_work_item_status(item_id, status, metadata_patch)
                except Exception as e:
                    logger.debug(f"WorkRegistry DB update for non-cached {item_id}: {e}")
            # Emit a minimal event so SSE/WS clients can react
            minimal = {"id": item_id, "status": status}
            await self._emit(minimal, "updated")
            return None

        # Update in-memory cache
        item["status"] = status
        now = datetime.now(timezone.utc).isoformat()
        if status == "running" and not item.get("started_at"):
            item["started_at"] = now
        if status in ("completed", "failed", "cancelled"):
            item["completed_at"] = now
        if metadata_patch:
            item["metadata"].update(metadata_patch)

        # Persist to DB
        if self._db:
            try:
                await self._db.update_work_item_status(item_id, status, metadata_patch)
            except Exception as e:
                logger.warning(f"WorkRegistry DB update failed for {item_id}: {e}")

        # Emit event
        await self._emit(item, "updated")

        # Remove from cache if terminal
        if status in ("completed", "failed", "cancelled"):
            self._items.pop(item_id, None)

        return item

    # ── Query Operations ─────────────────────────────────────────

    def get(self, item_id: str) -> Optional[dict]:
        """Get a work item from cache."""
        return self._items.get(item_id)

    def get_all_active(self) -> list[dict]:
        """Get all active (non-terminal) items from cache."""
        return list(self._items.values())

    def get_by_kind(self, kind: str) -> list[dict]:
        """Get items by kind from cache."""
        return [i for i in self._items.values() if i.get("kind") == kind]

    def get_children(self, parent_id: str) -> list[dict]:
        """Get child items of a parent."""
        return [i for i in self._items.values() if i.get("parent_id") == parent_id]

    def get_counts(self) -> dict:
        """Get count summary by status."""
        counts = {
            "pending": 0, "running": 0, "completed": 0,
            "failed": 0, "cancelled": 0, "total": 0,
        }
        for item in self._items.values():
            s = item.get("status", "pending")
            if s in counts:
                counts[s] += 1
            counts["total"] += 1
        return counts

    # ── SSE Subscription ─────────────────────────────────────────

    def subscribe_sse(self) -> asyncio.Queue:
        """Subscribe to SSE events. Returns a queue to read from."""
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._sse_subscribers.append(q)
        return q

    def unsubscribe_sse(self, q: asyncio.Queue) -> None:
        """Remove an SSE subscriber."""
        if q in self._sse_subscribers:
            self._sse_subscribers.remove(q)

    # ── Event Emission ───────────────────────────────────────────

    async def _emit(self, item: dict, event_type: str) -> None:
        """Emit a work item event to SSE subscribers and WebSocket clients."""
        if not self._initialized:
            return

        event = {
            "type": "work_item_update",
            "event": event_type,
            "item": item,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Push to SSE subscribers
        for q in list(self._sse_subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer — drop oldest events
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

        # Broadcast to all WebSocket clients
        if self._ws_manager:
            try:
                await self._ws_manager.broadcast(event)
            except Exception as e:
                logger.debug(f"WorkRegistry WS broadcast failed: {e}")


# ── Global singleton ─────────────────────────────────────────────
work_registry = WorkRegistry()
