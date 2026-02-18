"""Channel Adapter Framework — unified message handling across all communication channels.

Every channel (WebSocket, Telegram, WhatsApp, SMS, Voice) normalizes inbound messages
into a `ChannelMessage` dataclass, routes through `AgentRunner.run()` (or
`process_message()` for slash commands), and formats responses per-channel via
`ResponseFormatter`.

Architecture:
    Inbound → ChannelAdapter.receive() → ChannelMessage → AgentRunner → response
    Response → ResponseFormatter.format() → channel-specific output → ChannelAdapter.send()

The ChannelAdapter ABC defines the contract. Concrete adapters implement channel-specific
I/O (webhook parsing, WebSocket framing, bot API calls) but delegate all intelligence
to the shared Nexus agent pipeline.
"""

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, Optional

logger = logging.getLogger("nexus.channels")


# ── Enums ──────────────────────────────────────────────────────────


class ChannelType(str, Enum):
    """Supported communication channels."""
    WEBSOCKET = "websocket"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    VOICE = "voice"
    API = "api"          # REST API callers
    INSTAGRAM = "instagram"


class MediaType(str, Enum):
    """Media attachment types."""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    LOCATION = "location"
    CONTACT = "contact"
    STICKER = "sticker"


class MessageDirection(str, Enum):
    """Message direction for logging."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


# ── Dataclasses ────────────────────────────────────────────────────


@dataclass
class MediaAttachment:
    """A media file attached to a channel message."""
    media_type: MediaType
    url: str = ""                   # Remote URL (e.g. Twilio media URL)
    file_path: str = ""             # Local file path (after download)
    mime_type: str = ""             # MIME type (e.g. "image/jpeg")
    file_name: str = ""             # Original filename
    file_size: int = 0              # Size in bytes
    caption: str = ""               # Optional caption
    duration_seconds: float = 0     # For audio/video
    # Location-specific
    latitude: float = 0.0
    longitude: float = 0.0
    # Transcription (for voice messages)
    transcription: str = ""         # STT result for audio messages


@dataclass
class ChannelMessage:
    """Normalized inbound message from any channel.

    Every channel adapter converts its native message format into this
    dataclass before routing to the agent pipeline.
    """
    # Identity
    message_id: str = field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:12]}")
    channel: ChannelType = ChannelType.WEBSOCKET
    direction: MessageDirection = MessageDirection.INBOUND

    # Sender
    sender_id: str = ""             # Channel-specific user ID
    sender_name: str = ""           # Display name
    sender_username: str = ""       # @username if applicable
    nexus_user_id: str = ""         # Resolved Nexus user ID (from channel_identities)

    # Content
    text: str = ""                  # Message text content
    media: list[MediaAttachment] = field(default_factory=list)

    # Conversation
    conv_id: str = ""               # Nexus conversation ID (resolved by adapter)
    reply_to_message_id: str = ""   # If this is a reply

    # Metadata
    timestamp: float = field(default_factory=time.time)
    raw_payload: dict = field(default_factory=dict)  # Original channel payload
    metadata: dict = field(default_factory=dict)      # Channel-specific extras

    @property
    def has_media(self) -> bool:
        return len(self.media) > 0

    @property
    def has_text(self) -> bool:
        return bool(self.text and self.text.strip())

    @property
    def has_audio(self) -> bool:
        return any(m.media_type == MediaType.AUDIO for m in self.media)

    @property
    def audio_transcription(self) -> str:
        """Get transcription from the first audio attachment."""
        for m in self.media:
            if m.media_type == MediaType.AUDIO and m.transcription:
                return m.transcription
        return ""

    @property
    def effective_text(self) -> str:
        """Text content, falling back to audio transcription."""
        if self.has_text:
            return self.text
        if self.has_audio and self.audio_transcription:
            return self.audio_transcription
        return ""


@dataclass
class ChannelResponse:
    """Outbound response to send back through a channel.

    Created by ResponseFormatter from the raw agent response.
    """
    text: str = ""                          # Formatted text for the channel
    media: list[MediaAttachment] = field(default_factory=list)
    # Channel-specific rendering hints
    parse_mode: str = ""                    # "Markdown", "HTML", "plain"
    buttons: list[dict] = field(default_factory=list)  # Interactive buttons
    metadata: dict = field(default_factory=dict)


# ── Response Formatter ─────────────────────────────────────────────


class ResponseFormatter:
    """Format agent responses for specific channels.

    Each channel has different constraints:
    - WebSocket: Full Markdown, no length limit
    - Telegram: Markdown, 4096 char limit
    - WhatsApp: Limited formatting, 4096 char limit, interactive buttons
    - SMS: Plain text, 160 char segments (1600 char practical max)
    - Voice: Plain text for TTS, no formatting
    """

    # Channel-specific limits
    LIMITS = {
        ChannelType.WEBSOCKET: 0,       # No limit
        ChannelType.TELEGRAM: 4000,      # Leave buffer from 4096
        ChannelType.WHATSAPP: 4000,      # Leave buffer from 4096
        ChannelType.SMS: 1500,           # ~10 SMS segments max
        ChannelType.VOICE: 500,          # TTS should be concise
        ChannelType.API: 0,              # No limit
        ChannelType.INSTAGRAM: 1000,     # DM limit
    }

    @classmethod
    def format(cls, text: str, channel: ChannelType, **kwargs) -> ChannelResponse:
        """Format agent response text for a specific channel."""
        if channel == ChannelType.SMS:
            return cls._format_sms(text)
        elif channel == ChannelType.VOICE:
            return cls._format_voice(text)
        elif channel == ChannelType.WHATSAPP:
            return cls._format_whatsapp(text)
        elif channel == ChannelType.TELEGRAM:
            return cls._format_telegram(text)
        else:
            # WebSocket, API — pass through with Markdown
            return ChannelResponse(text=text, parse_mode="Markdown")

    @classmethod
    def _format_sms(cls, text: str) -> ChannelResponse:
        """SMS: Strip all formatting, aggressive truncation."""
        plain = cls._strip_markdown(text)
        limit = cls.LIMITS[ChannelType.SMS]
        if len(plain) > limit:
            plain = plain[:limit - 3] + "..."
        return ChannelResponse(text=plain, parse_mode="plain")

    @classmethod
    def _format_voice(cls, text: str) -> ChannelResponse:
        """Voice (TTS): Strip formatting, keep concise, natural speech."""
        plain = cls._strip_markdown(text)
        # Remove code blocks entirely (can't speak code)
        import re
        plain = re.sub(r"```[\s\S]*?```", "[code omitted]", plain)
        plain = re.sub(r"`[^`]+`", lambda m: m.group(0).strip("`"), plain)
        # Remove URLs (can't speak them usefully)
        plain = re.sub(r"https?://\S+", "", plain)
        plain = plain.strip()
        limit = cls.LIMITS[ChannelType.VOICE]
        if len(plain) > limit:
            # Truncate at sentence boundary
            truncated = plain[:limit]
            last_period = truncated.rfind(".")
            if last_period > limit // 2:
                plain = truncated[:last_period + 1]
            else:
                plain = truncated.rsplit(" ", 1)[0] + "."
        return ChannelResponse(text=plain, parse_mode="plain")

    @classmethod
    def _format_whatsapp(cls, text: str) -> ChannelResponse:
        """WhatsApp: Convert Markdown to WhatsApp formatting."""
        import re
        # WhatsApp uses *bold*, _italic_, ~strikethrough~, ```monospace```
        # Convert **bold** → *bold*
        formatted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
        # Convert # headers → *bold* on own line
        formatted = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", formatted, flags=re.MULTILINE)
        # Convert [text](url) → text (url)
        formatted = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", formatted)
        limit = cls.LIMITS[ChannelType.WHATSAPP]
        if limit and len(formatted) > limit:
            formatted = formatted[:limit - 3] + "..."
        return ChannelResponse(text=formatted, parse_mode="whatsapp")

    @classmethod
    def _format_telegram(cls, text: str) -> ChannelResponse:
        """Telegram: Markdown is native, just enforce length."""
        limit = cls.LIMITS[ChannelType.TELEGRAM]
        if limit and len(text) > limit:
            text = text[:limit - 3] + "..."
        return ChannelResponse(text=text, parse_mode="Markdown")

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove all Markdown formatting from text."""
        import re
        # Code blocks
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Inline code
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Bold/italic
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        text = re.sub(r"__(.+?)__", r"\1", text)
        text = re.sub(r"_(.+?)_", r"\1", text)
        # Headers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Links
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # Bullet points → dashes
        text = re.sub(r"^[\*\-]\s+", "- ", text, flags=re.MULTILINE)
        # Tables → remove pipes
        text = re.sub(r"\|", " ", text)
        text = re.sub(r"-{3,}", "", text)
        # Clean up multiple newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


# ── Channel Adapter ABC ───────────────────────────────────────────


class ChannelAdapter(ABC):
    """Abstract base class for all communication channel adapters.

    Concrete adapters implement channel-specific I/O:
    - Telegram: python-telegram-bot polling
    - WhatsApp/SMS: Twilio webhook → FastAPI route
    - Voice: Twilio Media Streams WebSocket
    - WebSocket: Existing ws.py handler (wraps for channel identity)

    The adapter's job:
    1. receive() — Parse inbound into ChannelMessage
    2. Route ChannelMessage.effective_text through the agent pipeline
    3. Format response via ResponseFormatter
    4. send() — Deliver formatted response through channel API
    """

    channel_type: ChannelType = ChannelType.WEBSOCKET

    def __init__(
        self,
        channel_type: ChannelType,
        db: Any = None,
        message_handler: Optional[Callable[..., Awaitable[str]]] = None,
        agent_name: str = "Nexus",
    ):
        self.channel_type = channel_type
        self.db = db
        self.message_handler = message_handler
        self.agent_name = agent_name
        self._started = False

    @abstractmethod
    async def start(self, **kwargs) -> None:
        """Start the channel adapter (connect, begin polling/listening)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel adapter gracefully."""
        ...

    @abstractmethod
    async def send(self, recipient_id: str, response: ChannelResponse) -> bool:
        """Send a formatted response to a recipient.

        Returns True on success, False on failure.
        """
        ...

    async def handle_message(self, message: ChannelMessage) -> ChannelResponse:
        """Process an inbound message through the agent pipeline.

        This is the core routing method — shared across all adapters.
        Subclasses call this from their channel-specific receive handlers.
        """
        if not self.message_handler:
            logger.error(f"[{self.channel_type.value}] No message handler configured")
            return ChannelResponse(text="Service unavailable")

        text = message.effective_text
        if not text:
            logger.debug(f"[{self.channel_type.value}] Empty message from {message.sender_id}")
            return ChannelResponse(text="")

        try:
            # Route through the shared agent pipeline
            response_text = await self.message_handler(
                message.sender_id,
                text,
                conv_id=message.conv_id,
            )

            # Format for this channel
            return ResponseFormatter.format(response_text, self.channel_type)

        except Exception as e:
            logger.error(
                f"[{self.channel_type.value}] Error handling message from "
                f"{message.sender_id}: {e}",
                exc_info=True,
            )
            return ResponseFormatter.format(
                f"Sorry, I encountered an error: {str(e)[:200]}",
                self.channel_type,
            )

    # ── Channel Identity ───────────────────────────────────────────

    async def resolve_nexus_user(self, channel_user_id: str) -> Optional[str]:
        """Look up the Nexus user ID for a channel-specific user ID.

        Returns the nexus_user_id if a channel_identity record exists,
        or None if the user hasn't been linked yet.
        """
        if not self.db:
            return None
        try:
            identity = await self.db.get_channel_identity(
                self.channel_type.value, channel_user_id
            )
            if identity:
                return identity.get("nexus_user_id")
        except Exception as e:
            logger.warning(f"Channel identity lookup failed: {e}")
        return None

    async def link_channel_identity(
        self,
        channel_user_id: str,
        nexus_user_id: str,
        display_name: str = "",
    ) -> bool:
        """Create or update a channel identity link."""
        if not self.db:
            return False
        try:
            await self.db.upsert_channel_identity(
                nexus_user_id=nexus_user_id,
                channel=self.channel_type.value,
                channel_user_id=channel_user_id,
                display_name=display_name,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to link channel identity: {e}")
            return False

    async def get_or_create_conversation(
        self,
        channel_user_id: str,
        first_message: str = "",
    ) -> str:
        """Get the active conversation for a channel user, or create one.

        This provides conversation continuity per channel user. Each
        channel user gets a persistent conversation that carries across
        messages.
        """
        if not self.db:
            return f"{self.channel_type.value}-{uuid.uuid4().hex[:8]}"

        # Try to find existing conversation for this channel user
        try:
            conv_id = await self.db.get_channel_conversation(
                self.channel_type.value, channel_user_id
            )
            if conv_id:
                # Verify the conversation still exists
                conv = await self.db.get_conversation(conv_id)
                if conv:
                    return conv_id
        except Exception as e:
            logger.warning(f"Conversation lookup failed: {e}")

        # Create new conversation
        conv_id = f"{self.channel_type.value[:3]}-{uuid.uuid4().hex[:8]}"
        title = first_message[:40] if first_message else f"{self.channel_type.value.title()} conversation"
        try:
            await self.db.create_conversation(conv_id, title=title)
            await self.db.set_channel_conversation(
                self.channel_type.value, channel_user_id, conv_id
            )
        except Exception as e:
            logger.warning(f"Conversation creation failed: {e}")

        return conv_id

    # ── Context Hints ──────────────────────────────────────────────

    def get_system_prompt_context(self) -> str:
        """Return channel-specific context to inject into the system prompt.

        This helps the agent adapt its behavior based on the communication
        channel (e.g., be more concise on SMS, use buttons on WhatsApp).
        """
        hints = {
            ChannelType.WEBSOCKET: "",  # Default — no special hints
            ChannelType.TELEGRAM: (
                "The user is chatting via Telegram. "
                "Use Markdown formatting. Keep responses under 4000 characters. "
                "The user can send voice messages and media."
            ),
            ChannelType.WHATSAPP: (
                "The user is messaging via WhatsApp. "
                "Be concise and conversational. Use *bold* for emphasis. "
                "Keep responses under 4000 characters. "
                "You can suggest interactive buttons (up to 3 options) by including them as numbered choices."
            ),
            ChannelType.SMS: (
                "The user is texting via SMS. "
                "Be extremely concise — each message costs money and has character limits. "
                "No formatting, no links unless essential. Keep responses under 300 characters ideally. "
                "Skip pleasantries and get straight to the point."
            ),
            ChannelType.VOICE: (
                "The user is on a live voice call. "
                "Speak naturally and conversationally. Keep responses short (1-3 sentences). "
                "No code, no URLs, no formatting — this will be spoken aloud via TTS. "
                "Ask clarifying questions if needed. Be warm and helpful."
            ),
            ChannelType.INSTAGRAM: (
                "The user is messaging via Instagram DM. "
                "Be casual and friendly. Keep responses concise."
            ),
        }
        return hints.get(self.channel_type, "")


# ── Channel Manager ────────────────────────────────────────────────


class ChannelManager:
    """Registry and lifecycle manager for all channel adapters.

    Initialized in app.py lifespan. Provides:
    - Adapter registration and lookup
    - Unified start/stop lifecycle
    - Cross-channel user identity resolution
    - Channel-aware system prompt context
    """

    def __init__(self) -> None:
        self._adapters: dict[ChannelType, ChannelAdapter] = {}
        self._started = False

    def register(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter."""
        self._adapters[adapter.channel_type] = adapter
        logger.info(f"Channel adapter registered: {adapter.channel_type.value}")

    def get(self, channel_type) -> Optional[ChannelAdapter]:
        """Get a registered adapter by channel type.

        Accepts either a ChannelType enum or a string (e.g. "whatsapp", "sms").
        """
        if isinstance(channel_type, str):
            try:
                channel_type = ChannelType(channel_type)
            except ValueError:
                return None
        return self._adapters.get(channel_type)

    @property
    def active_channels(self) -> list[ChannelType]:
        """List of registered channel types."""
        return list(self._adapters.keys())

    @property
    def active_channel_names(self) -> list[str]:
        """List of registered channel type names (for display)."""
        return [ct.value for ct in self._adapters]

    async def start_all(self, **kwargs) -> None:
        """Start all registered adapters."""
        for channel_type, adapter in self._adapters.items():
            try:
                await adapter.start(**kwargs)
                logger.info(f"Channel started: {channel_type.value}")
            except Exception as e:
                logger.warning(f"Channel failed to start ({channel_type.value}): {e}")
        self._started = True

    async def stop_all(self) -> None:
        """Stop all registered adapters."""
        for channel_type, adapter in self._adapters.items():
            try:
                await adapter.stop()
                logger.info(f"Channel stopped: {channel_type.value}")
            except Exception as e:
                logger.warning(f"Channel failed to stop ({channel_type.value}): {e}")
        self._started = False

    async def send_to_channel(
        self,
        channel_type: ChannelType,
        recipient_id: str,
        response: ChannelResponse,
    ) -> bool:
        """Send a message through a specific channel."""
        adapter = self._adapters.get(channel_type)
        if not adapter:
            logger.warning(f"No adapter for channel: {channel_type.value}")
            return False
        return await adapter.send(recipient_id, response)

    async def broadcast(
        self,
        nexus_user_id: str,
        text: str,
        db: Any = None,
        preferred_channel: Optional[ChannelType] = None,
    ) -> dict[str, bool]:
        """Send a message to a user across their preferred or all linked channels.

        Returns a dict of {channel_name: success_bool}.
        """
        results: dict[str, bool] = {}

        if not db:
            return results

        # Find all channel identities for this user
        try:
            identities = await db.get_user_channel_identities(nexus_user_id)
        except Exception as e:
            logger.warning(f"Failed to lookup channel identities: {e}")
            return results

        for identity in identities:
            channel_name = identity.get("channel", "")
            channel_user_id = identity.get("channel_user_id", "")

            try:
                channel_type = ChannelType(channel_name)
            except ValueError:
                continue

            # If preferred channel specified, skip others
            if preferred_channel and channel_type != preferred_channel:
                continue

            adapter = self._adapters.get(channel_type)
            if not adapter:
                continue

            response = ResponseFormatter.format(text, channel_type)
            success = await adapter.send(channel_user_id, response)
            results[channel_name] = success

        return results

    def get_system_prompt_context(self, channel_type: ChannelType) -> str:
        """Get system prompt context for a specific channel."""
        adapter = self._adapters.get(channel_type)
        if adapter:
            return adapter.get_system_prompt_context()
        return ""

    def get_status(self) -> dict:
        """Get status of all channels."""
        return {
            "channels": {
                ct.value: {
                    "started": adapter._started,
                    "type": ct.value,
                }
                for ct, adapter in self._adapters.items()
            },
            "total": len(self._adapters),
        }


# ── Global singleton ───────────────────────────────────────────────

channel_manager = ChannelManager()
