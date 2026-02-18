"""WhatsApp ChannelAdapter — Twilio WhatsApp Business API integration.

Handles:
- Inbound message parsing from Twilio webhooks
- Outbound message sending via Twilio REST API
- Media handling (images, audio, documents, video)
- WhatsApp voice message transcription (when Deepgram is available)
- Interactive buttons and list messages
- 24-hour session window awareness
- Webhook signature validation

The adapter is initialized at startup but only activates when
WHATSAPP_ENABLED=true and Twilio credentials are configured.
Twilio is imported lazily so the adapter can be created without
the `twilio` package installed — it will log a warning and
report as unavailable.
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

logger = logging.getLogger("nexus.channels.whatsapp")


# Media type mapping from Twilio content types
_TWILIO_MEDIA_MAP = {
    "image/jpeg": MediaType.IMAGE,
    "image/png": MediaType.IMAGE,
    "image/gif": MediaType.IMAGE,
    "image/webp": MediaType.IMAGE,
    "video/mp4": MediaType.VIDEO,
    "video/3gpp": MediaType.VIDEO,
    "audio/ogg": MediaType.AUDIO,
    "audio/mpeg": MediaType.AUDIO,
    "audio/mp4": MediaType.AUDIO,
    "audio/amr": MediaType.AUDIO,
    "application/pdf": MediaType.DOCUMENT,
    "application/vnd.ms-excel": MediaType.DOCUMENT,
    "application/msword": MediaType.DOCUMENT,
}


class WhatsAppAdapter(ChannelAdapter):
    """WhatsApp channel adapter using Twilio's WhatsApp Business API.

    Twilio sends inbound WhatsApp messages as HTTP POST webhooks with
    the same format as SMS, but the From field starts with "whatsapp:".
    Outbound messages are sent via the Twilio REST API.

    Key WhatsApp behaviors:
    - 24-hour session window: After user messages, you can reply freely
      for 24h. After that, only pre-approved template messages allowed.
    - Media: Supports images, video, audio, documents, location, contacts
    - Interactive: Up to 3 buttons or list messages
    - Rate limits: Tiered from 250 → 1K → 10K → 100K based on quality
    """

    def __init__(
        self,
        account_sid: str = "",
        auth_token: str = "",
        whatsapp_number: str = "",
        webhook_base_url: str = "",
        db: Any = None,
        message_handler: Optional[Callable[..., Awaitable[str]]] = None,
        agent_name: str = "Nexus",
        cfg: Any = None,
    ):
        super().__init__(
            channel_type=ChannelType.WHATSAPP,
            db=db,
            message_handler=message_handler,
            agent_name=agent_name,
        )
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._whatsapp_number = whatsapp_number
        self._webhook_base_url = webhook_base_url
        self._cfg = cfg
        self._client: Any = None  # Twilio Client (lazy)
        self._validator: Any = None  # RequestValidator for webhook auth
        self._available = False

    @property
    def is_available(self) -> bool:
        """Whether the adapter is configured and ready to send/receive."""
        return self._available and self._client is not None

    async def start(self, **kwargs) -> None:
        """Initialize the Twilio client for WhatsApp messaging."""
        if not self._account_sid or not self._auth_token:
            logger.info("WhatsApp adapter: no Twilio credentials — adapter inactive")
            return

        try:
            from twilio.rest import Client
            from twilio.request_validator import RequestValidator

            self._client = Client(self._account_sid, self._auth_token)
            self._validator = RequestValidator(self._auth_token)
            self._available = True
            self._started = True

            logger.info(
                f"WhatsApp adapter started — number: {self._whatsapp_number}, "
                f"webhook: {self._webhook_base_url}/api/channels/twilio/webhook"
            )
        except ImportError:
            logger.warning(
                "WhatsApp adapter: 'twilio' package not installed. "
                "Run: pip3 install twilio"
            )
            self._available = False
        except Exception as e:
            logger.error(f"WhatsApp adapter failed to start: {e}")
            self._available = False

    async def stop(self) -> None:
        """Stop the WhatsApp adapter."""
        self._client = None
        self._validator = None
        self._available = False
        self._started = False
        logger.info("WhatsApp adapter stopped")

    # ── Inbound Message Parsing ────────────────────────────────────

    def parse_webhook(self, form_data: dict) -> ChannelMessage:
        """Parse a Twilio webhook POST body into a ChannelMessage.

        Twilio sends form-encoded data with these fields:
        - MessageSid: Unique message ID
        - From: "whatsapp:+1234567890"
        - To: "whatsapp:+0987654321"
        - Body: Text content
        - NumMedia: Number of media attachments
        - MediaUrl0, MediaContentType0, etc.
        - ProfileName: Sender's WhatsApp display name
        - WaId: WhatsApp ID (phone number without +)
        """
        # Extract sender info
        from_raw = form_data.get("From", "")
        sender_id = from_raw.replace("whatsapp:", "").strip()
        sender_name = form_data.get("ProfileName", "")
        wa_id = form_data.get("WaId", sender_id.lstrip("+"))

        # Parse media attachments
        media = []
        num_media = int(form_data.get("NumMedia", "0"))
        for i in range(num_media):
            url = form_data.get(f"MediaUrl{i}", "")
            content_type = form_data.get(f"MediaContentType{i}", "")
            media_type = _TWILIO_MEDIA_MAP.get(content_type, MediaType.DOCUMENT)

            media.append(MediaAttachment(
                media_type=media_type,
                url=url,
                mime_type=content_type,
            ))

        # Build ChannelMessage
        msg = ChannelMessage(
            message_id=form_data.get("MessageSid", ""),
            channel=ChannelType.WHATSAPP,
            direction=MessageDirection.INBOUND,
            sender_id=sender_id,
            sender_name=sender_name,
            text=form_data.get("Body", ""),
            media=media,
            raw_payload=form_data,
            metadata={
                "wa_id": wa_id,
                "num_segments": form_data.get("NumSegments", "1"),
                "sms_sid": form_data.get("SmsSid", ""),
                "account_sid": form_data.get("AccountSid", ""),
            },
        )

        return msg

    def validate_webhook(self, url: str, form_data: dict, signature: str) -> bool:
        """Validate Twilio webhook signature to prevent spoofing.

        Args:
            url: The full webhook URL (including https://)
            form_data: The POST body as a dict
            signature: The X-Twilio-Signature header value

        Returns:
            True if the signature is valid
        """
        if not self._validator:
            logger.warning("No validator available — accepting webhook without validation")
            return True

        try:
            return self._validator.validate(url, form_data, signature)
        except Exception as e:
            logger.error(f"Webhook validation error: {e}")
            return False

    # ── Outbound Messaging ─────────────────────────────────────────

    async def send(self, recipient_id: str, response: ChannelResponse) -> bool:
        """Send a WhatsApp message to a recipient.

        Args:
            recipient_id: Phone number (E.164 format, e.g. "+1234567890")
            response: Formatted response from ResponseFormatter

        Returns:
            True on success, False on failure
        """
        if not self._client:
            logger.error("WhatsApp adapter not available — cannot send")
            return False

        # Ensure recipient has whatsapp: prefix
        to_number = recipient_id if recipient_id.startswith("whatsapp:") else f"whatsapp:{recipient_id}"

        try:
            # Send text message
            message = self._client.messages.create(
                body=response.text,
                from_=self._whatsapp_number,
                to=to_number,
            )
            logger.info(
                f"WhatsApp sent to {recipient_id}: SID={message.sid}, "
                f"status={message.status}"
            )
            return True

        except Exception as e:
            logger.error(f"WhatsApp send failed to {recipient_id}: {e}")
            return False

    async def send_media(
        self,
        recipient_id: str,
        media_url: str,
        caption: str = "",
    ) -> bool:
        """Send a WhatsApp message with media attachment.

        Args:
            recipient_id: Phone number (E.164)
            media_url: Public URL of the media file
            caption: Optional text caption
        """
        if not self._client:
            return False

        to_number = recipient_id if recipient_id.startswith("whatsapp:") else f"whatsapp:{recipient_id}"

        try:
            message = self._client.messages.create(
                body=caption or "",
                from_=self._whatsapp_number,
                to=to_number,
                media_url=[media_url],
            )
            logger.info(f"WhatsApp media sent to {recipient_id}: SID={message.sid}")
            return True
        except Exception as e:
            logger.error(f"WhatsApp media send failed to {recipient_id}: {e}")
            return False

    async def send_template(
        self,
        recipient_id: str,
        template_sid: str,
        variables: dict = None,
    ) -> bool:
        """Send a pre-approved WhatsApp template message.

        Template messages are required when the 24-hour session window
        has expired. Templates must be pre-approved by Meta via Twilio.

        Args:
            recipient_id: Phone number (E.164)
            template_sid: Twilio Content Template SID (e.g. HXxxxx)
            variables: Template variable substitutions
        """
        if not self._client:
            return False

        to_number = recipient_id if recipient_id.startswith("whatsapp:") else f"whatsapp:{recipient_id}"

        try:
            kwargs = {
                "from_": self._whatsapp_number,
                "to": to_number,
                "content_sid": template_sid,
            }
            if variables:
                kwargs["content_variables"] = str(variables)

            message = self._client.messages.create(**kwargs)
            logger.info(f"WhatsApp template sent to {recipient_id}: SID={message.sid}")
            return True
        except Exception as e:
            logger.error(f"WhatsApp template send failed: {e}")
            return False

    # ── Full Message Handling ──────────────────────────────────────

    async def handle_inbound(self, form_data: dict) -> ChannelResponse:
        """Full inbound message pipeline: parse → resolve identity → route → respond.

        Called by the webhook router after signature validation.
        Returns a ChannelResponse to send back.
        """
        # Parse webhook into ChannelMessage
        message = self.parse_webhook(form_data)
        logger.info(
            f"WhatsApp inbound from {message.sender_id} "
            f"({message.sender_name}): {message.text[:80]}"
        )

        # Resolve or create channel identity
        if self.db:
            try:
                existing = await self.db.get_channel_identity("whatsapp", message.sender_id)
                if not existing:
                    await self.db.upsert_channel_identity(
                        nexus_user_id=f"wa-{message.sender_id.lstrip('+')}",
                        channel="whatsapp",
                        channel_user_id=message.sender_id,
                        display_name=message.sender_name,
                    )
            except Exception as e:
                logger.debug(f"Channel identity update failed (non-blocking): {e}")

        # Get or create conversation for this user
        message.conv_id = await self.get_or_create_conversation(
            message.sender_id,
            first_message=message.effective_text,
        )

        # Handle voice messages (audio → transcription)
        if message.has_audio and not message.has_text:
            transcription = await self._transcribe_audio(message.media[0])
            if transcription:
                message.media[0].transcription = transcription
                logger.info(f"WhatsApp audio transcribed: {transcription[:80]}")

        # Route through agent pipeline
        response = await self.handle_message(message)

        return response

    async def _transcribe_audio(self, media: MediaAttachment) -> str:
        """Transcribe a WhatsApp voice message using Deepgram.

        Falls back to empty string if Deepgram is not configured.
        Phase C4 will add full Deepgram STT support.
        """
        # Stub — Phase C4 will implement Deepgram STT
        logger.info(f"Audio transcription requested for {media.url} — STT not yet implemented")
        return ""

    # ── Status Callbacks ───────────────────────────────────────────

    def parse_status_callback(self, form_data: dict) -> dict:
        """Parse a Twilio delivery status callback.

        Returns a dict with:
        - message_sid: str
        - status: str (queued, sent, delivered, read, failed, undelivered)
        - error_code: str (if failed)
        - error_message: str (if failed)
        """
        return {
            "message_sid": form_data.get("MessageSid", ""),
            "status": form_data.get("MessageStatus", ""),
            "to": form_data.get("To", "").replace("whatsapp:", ""),
            "error_code": form_data.get("ErrorCode", ""),
            "error_message": form_data.get("ErrorMessage", ""),
            "channel_prefix": form_data.get("ChannelPrefix", ""),
        }
