"""OpenClaw Bridge — Bidirectional Integration.

Connects Nexus to the OpenClaw orchestration framework for:
- Receiving tasks from OpenClaw and routing through plugins
- Sending progress updates, command results, and agent status
- Shared memory access between platforms
- Event synchronization

WebSocket-based connection with auto-reconnect.
"""

import asyncio
import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger("nexus.openclaw")


class EventType(str, Enum):
    """Events sent to/from OpenClaw."""
    # Outgoing (Nexus -> OpenClaw)
    SKILL_STARTED = "skill.started"
    SKILL_PROGRESS = "skill.progress"
    SKILL_COMPLETED = "skill.completed"
    SKILL_FAILED = "skill.failed"
    STATUS_UPDATE = "status.update"
    HEARTBEAT = "heartbeat"
    COMMAND_RESULT = "command.result"
    AGENT_STATUS = "agent.status"
    MEMORY_SYNC = "memory.sync"

    # Incoming (OpenClaw -> Nexus)
    TASK_ASSIGNED = "task.assigned"
    TASK_CANCELLED = "task.cancelled"
    CONFIG_UPDATED = "config.updated"
    COMMAND_REQUEST = "command.request"
    AGENT_REQUEST = "agent.request"
    MEMORY_REQUEST = "memory.request"


@dataclass
class BridgeConfig:
    """Configuration for OpenClaw bridge."""
    gateway_url: str = ""
    auth_token: str = ""
    reconnect_delay: float = 5.0
    max_reconnect_delay: float = 300.0
    heartbeat_interval: float = 30.0
    enabled: bool = False


@dataclass
class ConnectionState:
    """Current connection state."""
    connected: bool = False
    last_connected: Optional[float] = None
    last_message: Optional[float] = None
    reconnect_attempts: int = 0
    pending_messages: list = field(default_factory=list)
    events_received: int = 0
    events_sent: int = 0
    tasks_routed: int = 0
    commands_executed: int = 0


@dataclass
class BridgeTask:
    """A task received from OpenClaw for execution."""
    task_id: str
    source: str  # "openclaw"
    task_type: str  # "command", "query"
    payload: Dict[str, Any]
    priority: str = "normal"
    received_at: float = 0.0
    status: str = "pending"
    result: Optional[Dict[str, Any]] = None


class OpenClawBridge:
    """Manages bidirectional communication with OpenClaw.

    Features:
    - WebSocket connection with auto-reconnect
    - Exponential backoff on connection failures
    - Message queuing when disconnected
    - Event-based handler registration
    - Bidirectional task routing
    """

    def __init__(self, config: Optional[BridgeConfig] = None):
        self.config = config or BridgeConfig()
        self.state = ConnectionState()
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._handlers: Dict[EventType, list] = {}
        self._running = False
        self._tasks: list = []
        self._active_bridge_tasks: Dict[str, BridgeTask] = {}
        self._plugin_manager = None

    def set_plugin_manager(self, pm):
        """Set reference to plugin manager for command routing."""
        self._plugin_manager = pm

    async def start(self):
        """Start the bridge connection."""
        if not self.config.enabled or not self.config.gateway_url:
            logger.info("OpenClaw bridge disabled or not configured")
            return

        self._running = True
        self._session = aiohttp.ClientSession()

        self._register_default_handlers()
        self._tasks.append(asyncio.create_task(self._connection_loop()))
        logger.info(f"OpenClaw bridge starting: {self.config.gateway_url}")

    async def stop(self):
        """Stop the bridge connection."""
        self._running = False

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()
            self._session = None

        self.state.connected = False
        logger.info("OpenClaw bridge stopped")

    def _register_default_handlers(self):
        self.register_handler(EventType.TASK_ASSIGNED, self._handle_task_assigned)
        self.register_handler(EventType.TASK_CANCELLED, self._handle_task_cancelled)
        self.register_handler(EventType.CONFIG_UPDATED, self._handle_config_updated)
        self.register_handler(EventType.COMMAND_REQUEST, self._handle_command_request)

    def register_handler(self, event_type: EventType, handler: Callable):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    async def send_event(self, event_type: EventType, data: Dict[str, Any]):
        """Send an event to OpenClaw. Queues if disconnected."""
        message = {
            "type": event_type.value,
            "timestamp": time.time(),
            "source": "nexus",
            "data": data,
        }
        self.state.events_sent += 1

        if self.state.connected and self._ws:
            try:
                await self._ws.send_json(message)
                return True
            except Exception as e:
                logger.warning(f"Failed to send event: {e}")
                self.state.pending_messages.append(message)
                return False
        else:
            self.state.pending_messages.append(message)
            return False

    # ── Outgoing Notifications ──

    async def notify_skill_started(self, skill_id: str, skill_name: str, action: str, params: dict):
        await self.send_event(EventType.SKILL_STARTED, {
            "skill_id": skill_id, "skill_name": skill_name,
            "action": action, "params": params,
        })

    async def notify_skill_completed(self, skill_id: str, result: str, duration_ms: float):
        await self.send_event(EventType.SKILL_COMPLETED, {
            "skill_id": skill_id, "result": result, "duration_ms": duration_ms,
        })

    async def notify_skill_failed(self, skill_id: str, error: str, duration_ms: float):
        await self.send_event(EventType.SKILL_FAILED, {
            "skill_id": skill_id, "error": error, "duration_ms": duration_ms,
        })

    async def notify_command_result(self, task_id: str, command: str, result: dict):
        await self.send_event(EventType.COMMAND_RESULT, {
            "task_id": task_id, "command": command,
            "success": "error" not in result,
            "content": result.get("content", ""),
            "error": result.get("error", ""),
        })

    # ── Incoming Event Handlers ──

    async def _handle_task_assigned(self, data: dict):
        task_id = data.get("task_id", f"oc-{uuid.uuid4().hex[:8]}")
        task_type = data.get("type", "command")
        payload = data.get("payload", {})

        bridge_task = BridgeTask(
            task_id=task_id, source="openclaw", task_type=task_type,
            payload=payload, received_at=time.time(),
        )
        self._active_bridge_tasks[task_id] = bridge_task
        self.state.tasks_routed += 1
        logger.info(f"Task assigned from OpenClaw: {task_id} ({task_type})")

        if task_type == "command" and self._plugin_manager:
            command = payload.get("command", "")
            if command.startswith("/"):
                parts = command[1:].split(None, 1)
                cmd_name = parts[0] if parts else ""
                cmd_args = parts[1] if len(parts) > 1 else ""
                result = await self._plugin_manager.handle_command(cmd_name, cmd_args)
                bridge_task.status = "completed"
                bridge_task.result = {"content": result or "No response"}
                await self.notify_command_result(task_id, command, bridge_task.result)

    async def _handle_task_cancelled(self, data: dict):
        task_id = data.get("task_id", "")
        if task_id in self._active_bridge_tasks:
            self._active_bridge_tasks[task_id].status = "cancelled"
            logger.info(f"Task cancelled: {task_id}")

    async def _handle_config_updated(self, data: dict):
        updates = data.get("settings", {})
        logger.info(f"Config update from OpenClaw: {list(updates.keys())}")

    async def _handle_command_request(self, data: dict):
        task_id = data.get("task_id", f"oc-cmd-{uuid.uuid4().hex[:8]}")
        command = data.get("command", "")
        if not command:
            await self.notify_command_result(task_id, "", {"error": "No command specified"})
            return

        bridge_task = BridgeTask(
            task_id=task_id, source="openclaw", task_type="command",
            payload={"command": command}, received_at=time.time(),
        )
        self._active_bridge_tasks[task_id] = bridge_task
        self.state.commands_executed += 1

    # ── Connection Management ──

    async def _connection_loop(self):
        while self._running:
            try:
                await self._connect()
                await self._message_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Connection error: {e}")
                self.state.connected = False

            if not self._running:
                break

            self.state.reconnect_attempts += 1
            delay = min(
                self.config.reconnect_delay * (2 ** self.state.reconnect_attempts),
                self.config.max_reconnect_delay,
            )
            logger.info(f"Reconnecting in {delay:.1f}s (attempt {self.state.reconnect_attempts})")
            await asyncio.sleep(delay)

    async def _connect(self):
        if not self._session:
            self._session = aiohttp.ClientSession()

        headers = {}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        ws_url = self.config.gateway_url.replace("http://", "ws://").replace("https://", "wss://")
        if not ws_url.endswith("/ws"):
            ws_url = f"{ws_url}/ws"

        self._ws = await self._session.ws_connect(ws_url, headers=headers)
        self.state.connected = True
        self.state.last_connected = time.time()
        self.state.reconnect_attempts = 0
        logger.info("Connected to OpenClaw gateway")

        await self._flush_pending()
        await self.send_event(EventType.STATUS_UPDATE, {
            "status": "connected", "capabilities": ["commands", "skills", "plugins"],
            "version": "2.0",
        })
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))

    async def _message_loop(self):
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self.state.last_message = time.time()
                self.state.events_received += 1
                await self._handle_message(json.loads(msg.data))
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                break

    async def _handle_message(self, message: dict):
        msg_type = message.get("type", "")
        data = message.get("data", {})
        try:
            event_type = EventType(msg_type)
        except ValueError:
            logger.warning(f"Unknown event type: {msg_type}")
            return

        for handler in self._handlers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"Handler error for {event_type}: {e}")

    async def _flush_pending(self):
        while self.state.pending_messages and self._ws:
            message = self.state.pending_messages.pop(0)
            try:
                await self._ws.send_json(message)
            except Exception:
                self.state.pending_messages.insert(0, message)
                break

    async def _heartbeat_loop(self):
        while self._running and self.state.connected:
            await asyncio.sleep(self.config.heartbeat_interval)
            if self.state.connected:
                await self.send_event(EventType.HEARTBEAT, {
                    "status": "alive",
                    "uptime": time.time() - (self.state.last_connected or time.time()),
                    "events_received": self.state.events_received,
                    "events_sent": self.state.events_sent,
                    "tasks_routed": self.state.tasks_routed,
                })

    @property
    def is_connected(self) -> bool:
        return self.state.connected

    def get_active_tasks(self) -> List[dict]:
        return [
            {"task_id": t.task_id, "type": t.task_type, "status": t.status}
            for t in self._active_bridge_tasks.values()
            if t.status in ("pending", "running")
        ]

    def get_status(self) -> dict:
        active = len([t for t in self._active_bridge_tasks.values() if t.status in ("pending", "running")])
        return {
            "enabled": self.config.enabled,
            "connected": self.state.connected,
            "gateway_url": self.config.gateway_url,
            "last_connected": self.state.last_connected,
            "last_message": self.state.last_message,
            "reconnect_attempts": self.state.reconnect_attempts,
            "pending_messages": len(self.state.pending_messages),
            "events_received": self.state.events_received,
            "events_sent": self.state.events_sent,
            "tasks_routed": self.state.tasks_routed,
            "commands_executed": self.state.commands_executed,
            "active_tasks": active,
        }
