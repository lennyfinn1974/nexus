"""Channel webhook router — handles inbound webhooks for all external channels.

This module provides:
1. Twilio webhook endpoints (WhatsApp + SMS via single webhook URL)
2. Twilio delivery status callback handler
3. Channel status/health endpoint
4. Channel identity management API
5. Voice stubs (Phase C4)

The actual message processing lives in each channel adapter. This router
validates inbound requests, detects the channel type, and dispatches to
the correct adapter.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger("nexus.routers.channels")

router = APIRouter(prefix="/api/channels", tags=["channels"])


def _get_state(request: Request) -> Any:
    """Access AppState from the request."""
    return request.app.state.nexus


# ── Channel Status ─────────────────────────────────────────────────


@router.get("/status")
async def channel_status(request: Request):
    """Get status of all registered channel adapters."""
    state = _get_state(request)
    channel_mgr = getattr(state, "channel_manager", None)

    if not channel_mgr:
        return {"channels": {}, "total": 0, "status": "not_initialized"}

    status = channel_mgr.get_status()
    status["status"] = "active"
    return status


@router.get("/identities/{nexus_user_id}")
async def get_user_identities(nexus_user_id: str, request: Request):
    """Get all channel identities linked to a Nexus user."""
    state = _get_state(request)
    db = state.db

    if not db:
        raise HTTPException(status_code=503, detail="Database not available")

    identities = await db.get_user_channel_identities(nexus_user_id)
    return {"nexus_user_id": nexus_user_id, "identities": identities}


@router.post("/identities/link")
async def link_identity(request: Request):
    """Manually link a channel identity to a Nexus user.

    Body: {
        "nexus_user_id": "user-abc",
        "channel": "whatsapp",
        "channel_user_id": "+1234567890",
        "display_name": "John Doe"
    }
    """
    state = _get_state(request)
    db = state.db

    if not db:
        raise HTTPException(status_code=503, detail="Database not available")

    body = await request.json()
    nexus_user_id = body.get("nexus_user_id")
    channel = body.get("channel")
    channel_user_id = body.get("channel_user_id")
    display_name = body.get("display_name", "")

    if not all([nexus_user_id, channel, channel_user_id]):
        raise HTTPException(
            status_code=400,
            detail="Required: nexus_user_id, channel, channel_user_id",
        )

    result = await db.upsert_channel_identity(
        nexus_user_id=nexus_user_id,
        channel=channel,
        channel_user_id=channel_user_id,
        display_name=display_name,
    )
    return {"status": "linked", **result}


@router.delete("/identities/{channel}/{channel_user_id}")
async def unlink_identity(channel: str, channel_user_id: str, request: Request):
    """Remove a channel identity link."""
    state = _get_state(request)
    db = state.db

    if not db:
        raise HTTPException(status_code=503, detail="Database not available")

    removed = await db.remove_channel_identity(channel, channel_user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Identity not found")

    return {"status": "unlinked", "channel": channel, "channel_user_id": channel_user_id}


# ── TwiML Helper ──────────────────────────────────────────────────

TWIML_EMPTY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Response></Response>"
)


def _twiml_message(text: str) -> str:
    """Build a TwiML response with a <Message> body."""
    # Escape XML special characters
    safe = (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{safe}</Message></Response>"
    )


def _twiml_response(content: str) -> PlainTextResponse:
    """Wrap TwiML XML string in a proper HTTP response."""
    return PlainTextResponse(content=content, media_type="application/xml")


# ── Twilio Webhooks ───────────────────────────────────────────────


@router.post("/twilio/webhook")
async def twilio_webhook(request: Request):
    """Receive inbound messages from Twilio (WhatsApp + SMS).

    Twilio sends the same webhook format for both WhatsApp and SMS.
    The adapter distinguishes them by the 'From' field prefix:
    - whatsapp:+1234567890 → WhatsApp adapter
    - +1234567890 → SMS adapter

    Flow:
    1. Parse form data
    2. Validate Twilio signature (X-Twilio-Signature header)
    3. Detect channel type from 'From' prefix
    4. Dispatch to the correct adapter's handle_inbound()
    5. Send reply back async, return empty TwiML immediately
    """
    state = _get_state(request)
    cfg = state.cfg

    # Parse form-encoded body (Twilio sends application/x-www-form-urlencoded)
    form_data = dict(await request.form())

    from_field = form_data.get("From", "")
    body_preview = (form_data.get("Body", "") or "")[:60]
    is_whatsapp = from_field.startswith("whatsapp:")

    channel_name = "WhatsApp" if is_whatsapp else "SMS"
    logger.info(
        f"Twilio webhook: {channel_name} from {from_field} — \"{body_preview}\""
    )

    # ── Signature Validation ──
    # Twilio signs every webhook. We validate to prevent spoofing.
    twilio_signature = request.headers.get("X-Twilio-Signature", "")
    webhook_url = str(request.url)

    # Twilio validates against the original URL it was configured with,
    # which may use the configured webhook base URL rather than the
    # internal server URL. Use the configured base if available.
    webhook_base = cfg.get("TWILIO_WEBHOOK_BASE_URL", "")
    if webhook_base:
        webhook_url = f"{webhook_base.rstrip('/')}/api/channels/twilio/webhook"

    # Get the right adapter
    channel_mgr = getattr(state, "channel_manager", None)
    if not channel_mgr:
        logger.error("Twilio webhook: channel_manager not available")
        return _twiml_response(TWIML_EMPTY)

    if is_whatsapp:
        adapter = channel_mgr.get("whatsapp")
        if not adapter or not adapter.is_available:
            logger.warning("Twilio webhook: WhatsApp adapter not available")
            return _twiml_response(TWIML_EMPTY)
    else:
        adapter = channel_mgr.get("sms")
        if not adapter or not adapter.is_available:
            logger.warning("Twilio webhook: SMS adapter not available")
            return _twiml_response(TWIML_EMPTY)

    # Validate signature
    if not adapter.validate_webhook(webhook_url, form_data, twilio_signature):
        logger.warning(
            f"Twilio webhook: INVALID signature from {from_field} "
            f"(url={webhook_url})"
        )
        return _twiml_response(TWIML_EMPTY)

    # ── Process Message ──
    # Handle inbound returns a ChannelResponse. We send it back inline
    # via TwiML <Message> for simplicity. For long agent responses, the
    # adapter may also send async via the REST API.
    try:
        response = await adapter.handle_inbound(form_data)

        if response and response.text:
            # Return reply inline via TwiML
            reply_text = response.text
            # Truncate if too long for inline TwiML
            # (Twilio TwiML <Message> has a practical limit around 1600 chars for SMS)
            if not is_whatsapp and len(reply_text) > 1500:
                reply_text = reply_text[:1497] + "..."
            elif is_whatsapp and len(reply_text) > 4000:
                reply_text = reply_text[:3997] + "..."

            return _twiml_response(_twiml_message(reply_text))
        else:
            return _twiml_response(TWIML_EMPTY)

    except Exception as e:
        logger.error(
            f"Twilio webhook processing failed ({channel_name}): {e}",
            exc_info=True,
        )
        # Return a friendly error message via TwiML
        return _twiml_response(
            _twiml_message("Sorry, something went wrong. Please try again.")
        )


@router.post("/twilio/status")
async def twilio_status_callback(request: Request):
    """Receive message delivery status callbacks from Twilio.

    Reports delivery status: queued, sent, delivered, read, failed, undelivered.
    Logs the status and can be extended for retry logic.
    """
    state = _get_state(request)
    form_data = dict(await request.form())

    message_sid = form_data.get("MessageSid", "")
    status = form_data.get("MessageStatus", "")
    to = form_data.get("To", "")
    error_code = form_data.get("ErrorCode", "")

    # Detect channel from To field
    is_whatsapp = to.startswith("whatsapp:")
    channel_name = "WhatsApp" if is_whatsapp else "SMS"

    if error_code:
        error_msg = form_data.get("ErrorMessage", "")
        logger.warning(
            f"Twilio {channel_name} delivery failed: SID={message_sid}, "
            f"status={status}, error={error_code}: {error_msg}"
        )
    else:
        logger.info(
            f"Twilio {channel_name} status: SID={message_sid}, "
            f"status={status}, to={to}"
        )

    # Parse via the appropriate adapter for structured logging
    channel_mgr = getattr(state, "channel_manager", None)
    if channel_mgr:
        adapter = channel_mgr.get("whatsapp" if is_whatsapp else "sms")
        if adapter and hasattr(adapter, "parse_status_callback"):
            parsed = adapter.parse_status_callback(form_data)
            logger.debug(f"Parsed status callback: {parsed}")

    return {"status": "ok"}


# ── Voice Endpoints (Phase C4 — stub endpoints) ───────────────────


@router.post("/twilio/voice/inbound")
async def twilio_voice_inbound(request: Request):
    """Handle inbound voice calls — returns TwiML to connect to Media Streams.

    Phase C4 will implement: TwiML response generation, call routing,
    greeting message via ElevenLabs TTS.
    """
    state = _get_state(request)
    cfg = state.cfg

    # Use configured voice greeting or default
    greeting = cfg.voice_greeting if hasattr(cfg, "voice_greeting") else (
        "Thank you for calling. Voice support is coming soon."
    )

    logger.info("Twilio voice inbound (stub — Phase C4)")
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Say>{greeting}</Say>"
        "<Hangup/>"
        "</Response>"
    )
    return PlainTextResponse(content=twiml, media_type="application/xml")


@router.websocket("/voice/stream")
async def voice_media_stream():
    """Twilio Media Streams WebSocket — real-time audio bidirectional.

    Phase C4 will implement: Deepgram STT, VoicePipeline, ElevenLabs TTS,
    interruption handling, sentence-boundary streaming.
    """
    # Stub — WebSocket endpoint reserved for Phase C4
    pass
