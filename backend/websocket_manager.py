"""WebSocket Connection Manager with Reconnection and Message Queue."""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger("nexus.websocket")


class WebSocketManager:
    """Manages WebSocket connections with reconnection and message queuing."""

    def __init__(self, max_queue_size: int = 100, heartbeat_interval: int = 30):
        self.connections: dict[str, WebSocket] = {}
        self.session_data: dict[str, dict] = {}
        self.message_queues: dict[str, deque] = defaultdict(lambda: deque(maxlen=max_queue_size))
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_tasks: dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, session_id: str = None) -> str:
        """Accept a new WebSocket connection and assign session."""
        await websocket.accept()

        if session_id and session_id in self.session_data:
            # Reconnection - restore session
            ws_id = session_id
            logger.info(f"WebSocket reconnected: {ws_id}")

            # Cancel old heartbeat if exists
            if ws_id in self.heartbeat_tasks:
                self.heartbeat_tasks[ws_id].cancel()

        else:
            # New connection
            ws_id = f"ws-{uuid.uuid4().hex[:8]}"
            logger.info(f"WebSocket connected: {ws_id}")
            self.session_data[ws_id] = {
                "created_at": time.time(),
                "conv_id": None,
                "force_model": None,
            }

        self.connections[ws_id] = websocket

        # Start heartbeat task
        self.heartbeat_tasks[ws_id] = asyncio.create_task(
            self._heartbeat_loop(ws_id)
        )

        # Send queued messages if any
        await self._send_queued_messages(ws_id)

        # Send session info
        await self._send_message(ws_id, {
            "type": "session_info",
            "session_id": ws_id,
            "reconnected": session_id is not None,
            "queue_size": len(self.message_queues[ws_id])
        })

        return ws_id

    async def disconnect(self, ws_id: str, keep_session: bool = True):
        """Handle WebSocket disconnection."""
        if ws_id in self.connections:
            del self.connections[ws_id]

        if ws_id in self.heartbeat_tasks:
            self.heartbeat_tasks[ws_id].cancel()
            del self.heartbeat_tasks[ws_id]

        if not keep_session and ws_id in self.session_data:
            del self.session_data[ws_id]
            if ws_id in self.message_queues:
                del self.message_queues[ws_id]

        logger.info(f"WebSocket disconnected: {ws_id} (session kept: {keep_session})")

    async def send_to_client(self, ws_id: str, message: dict):
        """Send message to client, queue if offline."""
        if ws_id in self.connections:
            # Client is online, send immediately
            await self._send_message(ws_id, message)
        else:
            # Client is offline, queue the message
            self.message_queues[ws_id].append({
                "timestamp": time.time(),
                "message": message
            })
            logger.debug(f"Message queued for {ws_id}: {message['type']}")

    async def broadcast(self, message: dict, exclude: Optional[list[str]] = None):
        """Broadcast message to all connected clients."""
        exclude = exclude or []
        for ws_id in list(self.connections.keys()):
            if ws_id not in exclude:
                await self.send_to_client(ws_id, message)

    def get_session_data(self, ws_id: str) -> Optional[dict]:
        """Get session data for a WebSocket connection."""
        return self.session_data.get(ws_id)

    def update_session_data(self, ws_id: str, data: dict):
        """Update session data for a WebSocket connection."""
        if ws_id in self.session_data:
            self.session_data[ws_id].update(data)

    async def _send_message(self, ws_id: str, message: dict):
        """Internal method to send message to WebSocket."""
        if ws_id not in self.connections:
            return

        try:
            websocket = self.connections[ws_id]
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send message to {ws_id}: {e}")
            # Connection is probably dead, clean it up
            await self.disconnect(ws_id, keep_session=True)

    async def _send_queued_messages(self, ws_id: str):
        """Send all queued messages to the client."""
        if ws_id not in self.message_queues:
            return

        queue = self.message_queues[ws_id]
        messages_to_send = list(queue)
        queue.clear()

        for queued_item in messages_to_send:
            message = queued_item["message"]
            message["queued"] = True
            message["queued_at"] = queued_item["timestamp"]
            await self._send_message(ws_id, message)

    async def _heartbeat_loop(self, ws_id: str):
        """Heartbeat loop to detect dead connections."""
        try:
            while ws_id in self.connections:
                await asyncio.sleep(self.heartbeat_interval)

                # Send ping
                await self._send_message(ws_id, {
                    "type": "ping",
                    "timestamp": time.time()
                })

                # Wait for pong (client should respond within 10 seconds)
                # For now, we'll just continue - a more sophisticated implementation
                # would track pong responses and disconnect unresponsive clients

        except asyncio.CancelledError:
            # Task was cancelled, normal shutdown
            pass
        except Exception as e:
            logger.error(f"Heartbeat error for {ws_id}: {e}")


# Global instance
websocket_manager = WebSocketManager()
