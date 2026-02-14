"""Event Bus — Redis Pub/Sub broadcast for real-time agent coordination.

Channels:
    nexus:events:agent   — Agent lifecycle (joined, leaving, role_changed)
    nexus:events:model   — Model status changes (switch, failover)
    nexus:events:abort   — Abort signals (user_cancelled, timeout)
    nexus:events:config  — Config propagation (setting updates, epoch bumps)
    nexus:events:health  — Health alerts (agent_sdown, agent_odown)

Events are fire-and-forget — if no subscriber is listening, the message is
lost. For durable delivery, use Task Streams (Phase 6B) instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("nexus.cluster.event_bus")

# Type alias for event handlers
EventHandler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    """Redis Pub/Sub event bus for inter-agent communication.

    Usage:
        bus = EventBus(redis, prefix="nexus:", agent_id="nexus-01")
        await bus.start()

        # Subscribe to events
        await bus.subscribe("agent", my_handler)
        await bus.subscribe("config", my_config_handler)

        # Publish events
        await bus.publish("agent", {"type": "agent_joined", "id": "nexus-01"})

        await bus.stop()
    """

    # Standard event channels
    CHANNELS = ("agent", "model", "abort", "config", "health")

    def __init__(
        self,
        redis,
        prefix: str,
        agent_id: str,
    ):
        self._redis = redis
        self._prefix = prefix
        self.agent_id = agent_id

        # Handlers: channel_name -> [handler_fn, ...]
        self._handlers: dict[str, list[EventHandler]] = {}

        # Pub/Sub connection (separate from main connection)
        self._pubsub = None
        self._listener_task: Optional[asyncio.Task] = None
        self._stopped = False

        # Stats
        self._published_count = 0
        self._received_count = 0
        self._errors_count = 0

    def _channel_key(self, channel: str) -> str:
        """Full Redis channel key for a logical channel name."""
        return f"{self._prefix}events:{channel}"

    async def start(self) -> None:
        """Initialize Pub/Sub connection and start listener."""
        self._pubsub = self._redis.pubsub()

        # Subscribe to all standard channels
        channels = {self._channel_key(ch): self._dispatch for ch in self.CHANNELS}
        await self._pubsub.subscribe(**channels)

        # Start background listener
        self._listener_task = asyncio.create_task(self._listener_loop())

        logger.info(
            f"Event bus started: agent={self.agent_id} "
            f"channels={list(self.CHANNELS)}"
        )

    async def stop(self) -> None:
        """Unsubscribe from all channels and stop listener."""
        self._stopped = True

        # Cancel listener
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        # Unsubscribe and close pubsub
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.aclose()
            except Exception as e:
                logger.warning(f"Error closing pubsub: {e}")

        logger.info(
            f"Event bus stopped: published={self._published_count} "
            f"received={self._received_count} errors={self._errors_count}"
        )

    async def publish(self, channel: str, event: dict[str, Any]) -> int:
        """Publish an event to a channel.

        Args:
            channel: Logical channel name (e.g., "agent", "config")
            event: Event payload dict. Will be JSON-serialized with
                   sender_id and timestamp injected automatically.

        Returns:
            Number of subscribers that received the message.
        """
        # Inject metadata
        event["_sender"] = self.agent_id
        event["_timestamp"] = int(time.time() * 1000)  # ms precision

        key = self._channel_key(channel)
        payload = json.dumps(event)

        try:
            receivers = await self._redis.publish(key, payload)
            self._published_count += 1

            logger.debug(
                f"Published to {channel}: type={event.get('type', '?')} "
                f"receivers={receivers}"
            )
            return receivers

        except Exception as e:
            self._errors_count += 1
            logger.warning(f"Publish failed on {channel}: {e}")
            return 0

    async def subscribe(self, channel: str, handler: EventHandler) -> None:
        """Register a handler for events on a channel.

        The handler is an async callable: async def handler(channel, event_dict)

        Multiple handlers can be registered per channel. They run
        concurrently via asyncio.gather when an event arrives.
        """
        if channel not in self._handlers:
            self._handlers[channel] = []

        self._handlers[channel].append(handler)
        logger.debug(
            f"Handler registered: channel={channel} "
            f"total_handlers={len(self._handlers[channel])}"
        )

    async def unsubscribe(self, channel: str, handler: EventHandler = None) -> None:
        """Remove a handler (or all handlers) from a channel.

        Args:
            channel: The channel to unsubscribe from.
            handler: Specific handler to remove. If None, removes all.
        """
        if channel not in self._handlers:
            return

        if handler is None:
            del self._handlers[channel]
        else:
            self._handlers[channel] = [
                h for h in self._handlers[channel] if h is not handler
            ]
            if not self._handlers[channel]:
                del self._handlers[channel]

    async def publish_abort(self, conv_id: str, reason: str = "user_cancelled") -> int:
        """Convenience: publish an abort signal for a conversation."""
        return await self.publish("abort", {
            "type": "abort",
            "conv_id": conv_id,
            "reason": reason,
        })

    async def publish_model_switch(
        self, conv_id: str, from_model: str, to_model: str, reason: str = ""
    ) -> int:
        """Convenience: publish a model switch event."""
        return await self.publish("model", {
            "type": "model_switch",
            "conv_id": conv_id,
            "from": from_model,
            "to": to_model,
            "reason": reason,
        })

    async def publish_config_update(self, key: str, epoch: int) -> int:
        """Convenience: publish a config update notification."""
        return await self.publish("config", {
            "type": "config_update",
            "key": key,
            "epoch": epoch,
        })

    async def publish_health_alert(
        self, alert_type: str, target_id: str, **details
    ) -> int:
        """Convenience: publish a health alert."""
        return await self.publish("health", {
            "type": alert_type,
            "target_id": target_id,
            **details,
        })

    async def _dispatch(self, message: dict) -> None:
        """Internal dispatcher called by Redis pubsub for each message.

        Parses the JSON payload, extracts the logical channel name,
        and fans out to all registered handlers.
        """
        if message["type"] != "message":
            return  # skip subscribe/unsubscribe confirmations

        try:
            # Parse channel and payload
            raw_channel = message["channel"]
            if isinstance(raw_channel, bytes):
                raw_channel = raw_channel.decode("utf-8")

            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8")

            event = json.loads(data)

            # Extract logical channel name from full key
            # e.g., "nexus:events:agent" -> "agent"
            logical_channel = raw_channel.split(":")[-1]

            # Skip own messages (prevent echo)
            if event.get("_sender") == self.agent_id:
                return

            self._received_count += 1

            logger.debug(
                f"Received on {logical_channel}: type={event.get('type', '?')} "
                f"from={event.get('_sender', '?')}"
            )

            # Dispatch to handlers
            handlers = self._handlers.get(logical_channel, [])
            if handlers:
                tasks = [h(logical_channel, event) for h in handlers]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Log any handler errors
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        self._errors_count += 1
                        logger.warning(
                            f"Handler error on {logical_channel}: {result}"
                        )

        except json.JSONDecodeError as e:
            self._errors_count += 1
            logger.warning(f"Invalid JSON in event: {e}")
        except Exception as e:
            self._errors_count += 1
            logger.warning(f"Event dispatch error: {e}")

    async def _listener_loop(self) -> None:
        """Background loop reading from Pub/Sub.

        Uses get_message() with a short timeout to stay responsive
        to cancellation while not busy-waiting.
        """
        while not self._stopped:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message:
                    await self._dispatch(message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._errors_count += 1
                logger.warning(f"Listener error: {e}")
                # Brief backoff on error
                try:
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    break

    def get_stats(self) -> dict[str, Any]:
        """Return event bus statistics."""
        return {
            "published": self._published_count,
            "received": self._received_count,
            "errors": self._errors_count,
            "handler_count": sum(
                len(handlers) for handlers in self._handlers.values()
            ),
            "channels_with_handlers": list(self._handlers.keys()),
        }
