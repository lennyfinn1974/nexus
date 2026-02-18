"""Telegram ChannelAdapter — wraps existing TelegramChannel for unified channel system.

The existing TelegramChannel (channels/telegram.py) is battle-tested and handles
its own polling, pairing, and message routing. This adapter wraps it to conform
to the ChannelAdapter interface, enabling:
- Cross-channel identity linking (channel_identities table)
- Unified channel management via ChannelManager
- Channel-aware system prompt context
- ResponseFormatter integration

The underlying TelegramChannel continues to handle all Telegram-specific logic
(polling, commands, pairing codes, message chunking). This adapter delegates
to it rather than replacing it.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from channels.base import (
    ChannelAdapter,
    ChannelMessage,
    ChannelResponse,
    ChannelType,
    MessageDirection,
    ResponseFormatter,
)

logger = logging.getLogger("nexus.channels.telegram")


class TelegramAdapter(ChannelAdapter):
    """ChannelAdapter wrapper for the existing TelegramChannel.

    Lifecycle:
        1. Created in app.py with the same args as TelegramChannel
        2. start() creates and starts the inner TelegramChannel
        3. Messages flow through TelegramChannel's existing handlers
        4. Channel identity links are created on successful pairing
        5. stop() delegates to TelegramChannel.stop()

    The inner TelegramChannel is imported lazily to avoid import errors
    when python-telegram-bot is not installed.
    """

    def __init__(
        self,
        token: str,
        db: Any = None,
        message_handler: Optional[Callable[..., Awaitable[str]]] = None,
        agent_name: str = "Nexus",
    ):
        super().__init__(
            channel_type=ChannelType.TELEGRAM,
            db=db,
            message_handler=message_handler,
            agent_name=agent_name,
        )
        self._token = token
        self._inner: Any = None  # TelegramChannel instance (lazy)

    async def start(self, **kwargs) -> None:
        """Start the Telegram bot via the existing TelegramChannel."""
        from channels.telegram import TelegramChannel

        # Wrap the message handler to create channel identity links
        original_handler = self.message_handler

        async def _wrapped_handler(user_id: str, text: str, conv_id: str = None) -> str:
            """Route through original handler and link channel identity."""
            # Ensure channel identity exists for this Telegram user
            if self.db:
                try:
                    existing = await self.db.get_channel_identity("telegram", user_id)
                    if not existing:
                        # Auto-link: use Telegram user ID as the nexus_user_id
                        # (will be updated to real nexus_user_id when user pairs via web)
                        await self.db.upsert_channel_identity(
                            nexus_user_id=f"tg-{user_id}",
                            channel="telegram",
                            channel_user_id=user_id,
                        )
                    # Update conversation mapping in channel_identities
                    if conv_id:
                        await self.db.set_channel_conversation("telegram", user_id, conv_id)
                except Exception as e:
                    logger.debug(f"Channel identity update failed (non-blocking): {e}")

            return await original_handler(user_id, text, conv_id=conv_id)

        self._inner = TelegramChannel(
            token=self._token,
            db=self.db,
            message_handler=_wrapped_handler,
            agent_name=self.agent_name,
        )

        status_fn = kwargs.get("status_fn")
        await self._inner.start(status_fn=status_fn)
        self._started = True
        logger.info("TelegramAdapter started (wrapping TelegramChannel)")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._inner:
            await self._inner.stop()
        self._started = False
        logger.info("TelegramAdapter stopped")

    async def send(self, recipient_id: str, response: ChannelResponse) -> bool:
        """Send a message to a Telegram user."""
        if not self._inner:
            logger.error("TelegramAdapter not started — cannot send")
            return False

        text = response.text
        parse_mode = response.parse_mode if response.parse_mode != "plain" else None

        return await self._inner.send_message(
            chat_id=recipient_id,
            text=text,
            parse_mode=parse_mode or "Markdown",
        )

    # ── Passthrough to inner TelegramChannel ───────────────────────

    @property
    def inner(self) -> Any:
        """Access the underlying TelegramChannel for Telegram-specific operations."""
        return self._inner

    async def get_bot_info(self) -> Optional[dict]:
        """Get bot info from the underlying TelegramChannel."""
        if self._inner:
            return await self._inner.get_bot_info()
        return None
