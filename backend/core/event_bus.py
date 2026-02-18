"""Local Typed Event Bus — in-process event coordination for Nexus.

Unlike the Redis cluster event bus (core/cluster/event_bus.py) which handles
cross-instance pub/sub, this module provides in-process typed events for
coordinating components within a single Nexus instance: conductor phases,
terminal output, agent decisions, git operations.

Architecture:
    - Typed event dataclasses with validation
    - asyncio.Queue-based bus with subscriber pattern
    - Subscribers: WorkRegistry, WebSocket broadcaster, log writer, metrics
    - Thread-safe event emission (for subprocess callbacks)

Usage:
    from core.event_bus import event_bus, PhaseChangeEvent, TerminalOutputEvent

    # Subscribe:
    event_bus.subscribe("phase_change", my_handler)

    # Publish:
    await event_bus.publish(PhaseChangeEvent(
        conductor_id="cond-abc",
        from_phase="BUILDING",
        to_phase="REVIEWING",
    ))
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("nexus.event_bus")


# ── Event Types ─────────────────────────────────────────────────


class EventType(str, Enum):
    """All typed events the local bus can carry."""
    PHASE_CHANGE = "phase_change"
    AGENT_DECISION = "agent_decision"
    AGENT_SPAWNED = "agent_spawned"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    TERMINAL_COMMAND = "terminal_command"
    TERMINAL_OUTPUT = "terminal_output"
    GIT_EVENT = "git_event"
    CONDUCTOR_START = "conductor_start"
    CONDUCTOR_COMPLETE = "conductor_complete"
    BUILD_CYCLE = "build_cycle"
    METRICS = "metrics"


# ── Event Dataclasses ───────────────────────────────────────────


@dataclass
class BaseEvent:
    """Base for all typed events."""
    id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:8]}")
    event_type: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    conductor_id: str = ""  # Which conductor run this belongs to (empty = global)
    metadata: dict = field(default_factory=dict)


@dataclass
class PhaseChangeEvent(BaseEvent):
    """Conductor transitioned between phases."""
    event_type: str = field(default=EventType.PHASE_CHANGE, init=False)
    from_phase: str = ""
    to_phase: str = ""
    reason: str = ""  # Why the transition happened


@dataclass
class AgentDecisionEvent(BaseEvent):
    """Conductor made a decision about agent dispatch."""
    event_type: str = field(default=EventType.AGENT_DECISION, init=False)
    decision: str = ""  # e.g., "spawn_builder", "retry_build", "escalate"
    agent_id: str = ""
    context: str = ""  # What informed the decision


@dataclass
class AgentSpawnedEvent(BaseEvent):
    """A sub-agent was spawned."""
    event_type: str = field(default=EventType.AGENT_SPAWNED, init=False)
    agent_id: str = ""
    role: str = ""
    model: str = ""
    prompt_preview: str = ""  # First 200 chars of prompt


@dataclass
class AgentCompletedEvent(BaseEvent):
    """A sub-agent completed its work."""
    event_type: str = field(default=EventType.AGENT_COMPLETED, init=False)
    agent_id: str = ""
    role: str = ""
    model: str = ""
    duration_ms: int = 0
    output_preview: str = ""  # First 200 chars of output


@dataclass
class AgentFailedEvent(BaseEvent):
    """A sub-agent failed."""
    event_type: str = field(default=EventType.AGENT_FAILED, init=False)
    agent_id: str = ""
    role: str = ""
    error: str = ""


@dataclass
class TerminalCommandEvent(BaseEvent):
    """A command was sent to a terminal session."""
    event_type: str = field(default=EventType.TERMINAL_COMMAND, init=False)
    session_name: str = ""
    command: str = ""
    agent_id: str = ""  # Which agent issued the command


@dataclass
class TerminalOutputEvent(BaseEvent):
    """Output was captured from a terminal session."""
    event_type: str = field(default=EventType.TERMINAL_OUTPUT, init=False)
    session_name: str = ""
    output: str = ""
    exit_code: Optional[int] = None


@dataclass
class GitEvent(BaseEvent):
    """A git operation occurred."""
    event_type: str = field(default=EventType.GIT_EVENT, init=False)
    operation: str = ""  # "commit", "branch", "merge", "push", "diff"
    branch: str = ""
    message: str = ""
    files_changed: int = 0
    agent_id: str = ""


@dataclass
class ConductorStartEvent(BaseEvent):
    """A conductor orchestration started."""
    event_type: str = field(default=EventType.CONDUCTOR_START, init=False)
    task: str = ""
    strategy: str = ""
    agent_count: int = 0


@dataclass
class ConductorCompleteEvent(BaseEvent):
    """A conductor orchestration completed."""
    event_type: str = field(default=EventType.CONDUCTOR_COMPLETE, init=False)
    status: str = ""  # "success", "failed", "escalated"
    duration_ms: int = 0
    build_cycles: int = 0
    agents_used: int = 0
    total_cost_usd: float = 0.0


@dataclass
class BuildCycleEvent(BaseEvent):
    """A build-review cycle completed."""
    event_type: str = field(default=EventType.BUILD_CYCLE, init=False)
    cycle_number: int = 0
    builder_model: str = ""
    reviewer_model: str = ""
    reviewer_score: float = 0.0
    passed: bool = False
    feedback_preview: str = ""


# ── Subscriber Type ─────────────────────────────────────────────

EventHandler = Callable[[BaseEvent], Coroutine[Any, Any, None]]


# ── Event Bus ───────────────────────────────────────────────────


class LocalEventBus:
    """In-process async event bus with typed events.

    Supports:
    - Subscribing to specific event types or "*" for all events
    - Async handlers (non-blocking dispatch)
    - Event history ring buffer for recent event queries
    - Statistics (events published, handlers called, errors)
    """

    def __init__(self, history_size: int = 500):
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._history: list[BaseEvent] = []
        self._history_size = history_size
        self._stats = {
            "published": 0,
            "dispatched": 0,
            "errors": 0,
        }
        self._initialized = False

    def init(self) -> None:
        """Mark as initialized. Call from app.py lifespan."""
        self._initialized = True
        logger.info("Local event bus initialized")

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe a handler to an event type.

        Args:
            event_type: EventType value or "*" for all events.
            handler: Async callable accepting a BaseEvent subclass.
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug("Subscribed handler to '%s' events", event_type)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a handler from an event type."""
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event to all matching subscribers.

        Handlers are called concurrently. Errors in one handler
        don't prevent others from running.
        """
        if not self._initialized:
            return

        self._stats["published"] += 1

        # Add to history ring buffer
        self._history.append(event)
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size:]

        # Collect matching handlers
        handlers = list(self._subscribers.get(event.event_type, []))
        handlers.extend(self._subscribers.get("*", []))

        if not handlers:
            return

        # Dispatch concurrently (fire-and-forget style but awaited for ordering)
        for handler in handlers:
            try:
                await handler(event)
                self._stats["dispatched"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                logger.warning(
                    "Event handler error for %s: %s",
                    event.event_type, e,
                )

    def publish_sync(self, event: BaseEvent) -> None:
        """Schedule event publication from a sync context (e.g., subprocess callback).

        Creates an asyncio task to publish the event without blocking.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            # No running loop — just log and drop
            logger.debug("No event loop for sync publish of %s", event.event_type)

    # ── Query ────────────────────────────────────────────────────

    def get_recent_events(
        self,
        event_type: Optional[str] = None,
        conductor_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[BaseEvent]:
        """Query recent events from the ring buffer.

        Args:
            event_type: Filter by event type (None = all).
            conductor_id: Filter by conductor run (None = all).
            limit: Maximum events to return.
        """
        events = self._history
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if conductor_id:
            events = [e for e in events if e.conductor_id == conductor_id]
        return events[-limit:]

    def get_stats(self) -> dict:
        """Return event bus statistics."""
        return {
            **self._stats,
            "subscribers": {
                k: len(v) for k, v in self._subscribers.items()
            },
            "history_size": len(self._history),
        }

    def clear_history(self) -> None:
        """Clear the event history ring buffer."""
        self._history.clear()


# ── Global singleton ────────────────────────────────────────────
event_bus = LocalEventBus()
