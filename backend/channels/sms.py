"""SMS ChannelAdapter — Twilio SMS integration.

Handles:
- Inbound SMS parsing from Twilio webhooks (same format as WhatsApp)
- Outbound SMS via Twilio REST API
- Aggressive brevity mode (160-char segment awareness)
- MMS media attachments (inbound images)
- Delivery status tracking

SMS messages from Twilio use the same webhook format as WhatsApp,
but the From field is a plain phone number (no "whatsapp:" prefix).
The webhook router distinguishes them by checking the prefix.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from channels.base import (
    ChannelAdapter,
    ChannelMessage,
    ChannelResponse,
    ChannelType,
    MediaAttachment,
    MediaType,
    MessageDirection,
    ResponseFormatter,
)

logger = logging.getLogger("nexus.channels.sms")


class SMSAdapter(ChannelAdapter):
    """SMS channel adapter using Twilio's Programmable Messaging API.

    Key SMS constraints:
    - 160 chars per segment (SMS), 1600 chars practical max (~10 segments)
    - No formatting — plain text only
    - MMS supports images but adds cost
    - Each segment costs money — brevity is critical
    - No read receipts (delivery receipts available)
    """

    def __init__(
        self,
        account_sid: str = "",
        auth_token: str = "",
        phone_number: str = "",
        webhook_base_url: str = "",
        db: Any = None,
        message_handler: Optional[Callable[..., Awaitable[str]]] = None,
        agent_name: str = "Nexus",
        cfg: Any = None,
    ):
        super().__init__(
            channel_type=ChannelType.SMS,
            db=db,
            message_handler=message_handler,
            agent_name=agent_name,
        )
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._phone_number = phone_number
        self._webhook_base_url = webhook_base_url
        self._cfg = cfg
        self._client: Any = None
        self._validator: Any = None
        self._available = False

    @property
    def is_available(self) -> bool:
        return self._available and self._client is not None

    async def start(self, **kwargs) -> None:
        """Initialize the Twilio client for SMS."""
        if not self._account_sid or not self._auth_token:
            logger.info("SMS adapter: no Twilio credentials — adapter inactive")
            return

        try:
            from twilio.rest import Client
            from twilio.request_validator import RequestValidator

            self._client = Client(self._account_sid, self._auth_token)
            self._validator = RequestValidator(self._auth_token)
            self._available = True
            self._started = True

            logger.info(
                f"SMS adapter started — number: {self._phone_number}, "
                f"webhook: {self._webhook_base_url}/api/channels/twilio/webhook"
            )
        except ImportError:
            logger.warning(
                "SMS adapter: 'twilio' package not installed. "
                "Run: pip3 install twilio"
            )
        except Exception as e:
            logger.error(f"SMS adapter failed to start: {e}")

    async def stop(self) -> None:
        self._client = None
        self._validator = None
        self._available = False
        self._started = False
        logger.info("SMS adapter stopped")

    # ── Inbound ────────────────────────────────────────────────────

    def parse_webhook(self, form_data: dict) -> ChannelMessage:
        """Parse a Twilio SMS webhook into a ChannelMessage.

        Same format as WhatsApp but From is plain phone number.
        """
        sender_id = form_data.get("From", "").strip()
        from_city = form_data.get("FromCity", "")
        from_state = form_data.get("FromState", "")

        # Parse MMS media (SMS can include images via MMS)
        media = []
        num_media = int(form_data.get("NumMedia", "0"))
        for i in range(num_media):
            url = form_data.get(f"MediaUrl{i}", "")
            content_type = form_data.get(f"MediaContentType{i}", "")
            media_type = MediaType.IMAGE if "image" in content_type else MediaType.DOCUMENT

            media.append(MediaAttachment(
                media_type=media_type,
                url=url,
                mime_type=content_type,
            ))

        return ChannelMessage(
            message_id=form_data.get("MessageSid", ""),
            channel=ChannelType.SMS,
            direction=MessageDirection.INBOUND,
            sender_id=sender_id,
            text=form_data.get("Body", ""),
            media=media,
            raw_payload=form_data,
            metadata={
                "from_city": from_city,
                "from_state": from_state,
                "from_country": form_data.get("FromCountry", ""),
                "from_zip": form_data.get("FromZip", ""),
                "num_segments": form_data.get("NumSegments", "1"),
            },
        )

    def validate_webhook(self, url: str, form_data: dict, signature: str) -> bool:
        """Validate Twilio webhook signature."""
        if not self._validator:
            return True
        try:
            return self._validator.validate(url, form_data, signature)
        except Exception as e:
            logger.error(f"SMS webhook validation error: {e}")
            return False

    # ── Outbound ───────────────────────────────────────────────────

    async def send(self, recipient_id: str, response: ChannelResponse) -> bool:
        """Send an SMS to a recipient.

        Args:
            recipient_id: Phone number (E.164 format)
            response: Formatted response (should already be brevity-optimized)
        """
        if not self._client:
            logger.error("SMS adapter not available — cannot send")
            return False

        try:
            message = self._client.messages.create(
                body=response.text,
                from_=self._phone_number,
                to=recipient_id,
            )
            segments = len(response.text) // 160 + 1
            logger.info(
                f"SMS sent to {recipient_id}: SID={message.sid}, "
                f"status={message.status}, ~{segments} segment(s)"
            )
            return True
        except Exception as e:
            logger.error(f"SMS send failed to {recipient_id}: {e}")
            return False

    # ── Full Pipeline ──────────────────────────────────────────────

    async def handle_inbound(self, form_data: dict) -> ChannelResponse:
        """Full inbound SMS pipeline: parse → identity → route → respond."""
        message = self.parse_webhook(form_data)
        logger.info(f"SMS inbound from {message.sender_id}: {message.text[:80]}")

        # Resolve or create channel identity
        if self.db:
            try:
                existing = await self.db.get_channel_identity("sms", message.sender_id)
                if not existing:
                    await self.db.upsert_channel_identity(
                        nexus_user_id=f"sms-{message.sender_id.lstrip('+')}",
                        channel="sms",
                        channel_user_id=message.sender_id,
                    )
            except Exception as e:
                logger.debug(f"Channel identity update failed: {e}")

        # Get or create conversation
        message.conv_id = await self.get_or_create_conversation(
            message.sender_id,
            first_message=message.effective_text,
        )

        # Route through agent pipeline
        response = await self.handle_message(message)

        return response

    def parse_status_callback(self, form_data: dict) -> dict:
        """Parse SMS delivery status callback."""
        return {
            "message_sid": form_data.get("MessageSid", ""),
            "status": form_data.get("MessageStatus", ""),
            "to": form_data.get("To", ""),
            "error_code": form_data.get("ErrorCode", ""),
            "error_message": form_data.get("ErrorMessage", ""),
        }
