"""Nexus Channel Adapters — unified multi-channel communication framework.

Key types:
    ChannelAdapter   — ABC for all channel implementations
    ChannelMessage   — Normalized inbound message
    ChannelResponse  — Formatted outbound response
    ChannelManager   — Registry and lifecycle for all adapters
    ChannelType      — Enum of supported channels
    ResponseFormatter — Per-channel response formatting

Channel implementations:
    telegram.py          — Original TelegramChannel (low-level bot)
    telegram_adapter.py  — ChannelAdapter wrapper for Telegram
    (whatsapp.py)        — Phase C2
    (sms.py)             — Phase C2
    (voice.py)           — Phase C4
"""

from channels.base import (
    ChannelAdapter,
    ChannelManager,
    ChannelMessage,
    ChannelResponse,
    ChannelType,
    MediaAttachment,
    MediaType,
    MessageDirection,
    ResponseFormatter,
    channel_manager,
)

__all__ = [
    "ChannelAdapter",
    "ChannelManager",
    "ChannelMessage",
    "ChannelResponse",
    "ChannelType",
    "MediaAttachment",
    "MediaType",
    "MessageDirection",
    "ResponseFormatter",
    "channel_manager",
]
