# Nexus Communications Architecture — WhatsApp + Twilio Voice/SMS + ElevenLabs

**Version:** 1.0
**Date:** 18 February 2026
**Status:** Deep Research Complete — Ready for Implementation Planning

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [WhatsApp Business API Integration](#2-whatsapp-business-api-integration)
3. [Twilio Voice + SMS Integration](#3-twilio-voice--sms-integration)
4. [ElevenLabs Voice Synthesis](#4-elevenlabs-voice-synthesis)
5. [Real-Time Voice Conversation Architecture](#5-real-time-voice-conversation-architecture)
6. [Open-Source Voice Agent Frameworks](#6-open-source-voice-agent-frameworks)
7. [Unified Communications Layer](#7-unified-communications-layer)
8. [Implementation Architecture](#8-implementation-architecture)
9. [Pricing Analysis](#9-pricing-analysis)
10. [Recommended Implementation Plan](#10-recommended-implementation-plan)

---

## 1. Executive Summary

This document covers the integration of three communication platforms into Nexus:

- **WhatsApp Business API** — via Twilio (recommended) or Meta's direct Cloud API
- **Twilio** — Voice calls (with Media Streams for real-time AI), SMS, and WhatsApp messaging
- **ElevenLabs** — Natural-sounding text-to-speech for voice responses

The core architectural challenge is building a **Unified Communications Layer** that normalizes messages from all channels (WebSocket, Telegram, WhatsApp, SMS, Voice) into a common format, routes them through the existing `process_message()` pipeline, and formats responses appropriately per channel.

**Key Decision: Twilio as WhatsApp Provider.** Using Twilio for WhatsApp messaging (rather than Meta's direct API) is strongly recommended because:
1. Nexus already needs Twilio for voice/SMS — single vendor, single SDK, single webhook system
2. Twilio abstracts away Meta's Business API complexity (verification, hosting, certificate management)
3. Same Python SDK (`twilio`) handles WhatsApp + SMS + Voice
4. Unified phone number management and billing

---

## 2. WhatsApp Business API Integration

### 2.1 Meta Cloud API vs Twilio WhatsApp

| Factor | Meta Cloud API (Direct) | Twilio WhatsApp API |
|--------|------------------------|---------------------|
| **Setup complexity** | High — Meta Business Manager, Business Verification, API setup, webhook hosting | Medium — Twilio account + WhatsApp sender registration |
| **Phone number** | Must provide your own number, goes through Meta verification | Can use Twilio-provided numbers or your own |
| **Template approval** | Direct Meta review (24-48h) | Submit through Twilio (routes to Meta, same timeline) |
| **Webhook handling** | Must implement Meta's verification challenge (hub.verify_token) | Standard Twilio webhook format (same as SMS/Voice) |
| **SDK** | No official Python SDK — raw HTTP via Graph API | `twilio` Python SDK with full WhatsApp support |
| **Pricing** | Meta conversation-based pricing only | Twilio markup on top of Meta's pricing |
| **Rich media** | Full support | Full support |
| **Interactive messages** | Buttons, lists, location, contacts | Buttons, lists (via ContentSid templates) |
| **Rate limits** | Tiered: 250 → 1K → 10K → 100K → unlimited (based on quality rating) | Same Meta limits apply, Twilio adds its own queuing |
| **Annual cost (1K msgs/day)** | ~$30-50/mo (conversation-based) | ~$50-80/mo (Twilio markup ~$0.005-0.01/msg) |

**Recommendation:** Twilio WhatsApp. The SDK unification with Voice/SMS and simplified webhook handling outweighs the small price premium.

### 2.2 WhatsApp Messaging Model

WhatsApp has a distinctive conversation-based pricing and messaging model:

**24-Hour Session Window:**
- When a user messages your business, a 24-hour "customer service window" opens
- Within this window, you can send any message (text, media, interactive)
- After the window closes, you can ONLY send pre-approved **template messages**
- Template messages re-open the 24-hour window when the user responds

**Conversation Categories (pricing tiers):**
- **Utility** — Order confirmations, shipping updates, account alerts. Cheapest.
- **Authentication** — OTP codes, login verifications
- **Marketing** — Promotions, offers, announcements. Most expensive.
- **Service** — User-initiated conversations (user messages first). Free tier exists.

**Message Types Supported:**
- Text messages (up to 4096 characters)
- Images (JPEG, PNG — up to 5MB)
- Documents (PDF, DOC, etc. — up to 100MB)
- Audio (AAC, MP3, OGG, AMR — up to 16MB)
- Video (MP4, 3GPP — up to 16MB)
- Location (latitude/longitude)
- Contacts (vCard format)
- Interactive: Buttons (up to 3), Lists (up to 10 sections/rows), Reply buttons
- Reactions (emoji reactions to messages)
- Stickers (WebP, 512x512px)

### 2.3 Twilio WhatsApp Setup

**Registration Process:**
1. Create Twilio account, get Account SID + Auth Token
2. Navigate to Messaging > Senders > WhatsApp Senders
3. Register a WhatsApp Business Profile (business name, description, logo)
4. Either use Twilio's sandbox for testing or register a production sender
5. Submit WhatsApp sender for approval (1-2 business days)
6. Configure webhook URL for incoming messages

**Twilio Sandbox (Development):**
- Instant setup, no approval needed
- Users must opt-in by sending "join <sandbox-keyword>" to Twilio's sandbox number
- Limited to 1 test number per account
- Good for development, not production

**Webhook Configuration:**
- Incoming messages: `POST /api/channels/whatsapp/webhook`
- Status callbacks: `POST /api/channels/whatsapp/status`
- Twilio sends standard HTTP POST with form-encoded or JSON body
- Must return 200 OK within 15 seconds or Twilio retries

### 2.4 Python SDK Usage

```python
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

# Send a WhatsApp message
client = Client(account_sid, auth_token)
message = client.messages.create(
    from_='whatsapp:+14155238886',
    body='Hello from Nexus!',
    to='whatsapp:+15551234567'
)

# Send media
message = client.messages.create(
    from_='whatsapp:+14155238886',
    body='Here is your document',
    media_url=['https://example.com/doc.pdf'],
    to='whatsapp:+15551234567'
)

# Send template message (for out-of-window messaging)
message = client.messages.create(
    from_='whatsapp:+14155238886',
    content_sid='HXxxxxx',  # Pre-approved template ContentSid
    content_variables='{"1":"John","2":"Order #12345"}',
    to='whatsapp:+15551234567'
)

# Webhook handler (FastAPI)
@router.post("/api/channels/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    from_number = form.get("From", "")       # "whatsapp:+15551234567"
    body = form.get("Body", "")               # Message text
    num_media = int(form.get("NumMedia", 0))  # Number of media attachments
    media_url = form.get("MediaUrl0", "")     # First media URL
    media_type = form.get("MediaContentType0", "")

    # Process through Nexus agent
    response = await process_message(user_id=from_number, text=body, ...)

    # Reply via TwiML
    twiml = MessagingResponse()
    twiml.message(response)
    return Response(content=str(twiml), media_type="text/xml")
```

### 2.5 Nexus-Specific Considerations

**Existing WhatsApp Skill:** Nexus already has a `whatsapp-automation` skill (via Rube MCP/Composio) for outbound messaging. This new integration is for **inbound** — receiving WhatsApp messages as a communication channel, same as Telegram.

**User Identity Mapping:**
- WhatsApp users identified by phone number: `whatsapp:+15551234567`
- Need a pairing mechanism similar to Telegram's `/pair CODE` system
- Can use phone number as persistent user ID (more stable than Telegram user IDs)

**Message Size Limits:**
- WhatsApp: 4096 chars (vs Telegram: 4096 chars, SMS: 160 chars)
- For long Nexus responses, chunk at paragraph boundaries
- Consider sending long responses as documents (PDF/TXT) for readability

**Media Handling:**
- Incoming voice messages: Twilio provides a URL to the OGG/AMR audio file
- Need speech-to-text transcription before passing to agent
- Incoming images: Could use vision model or describe to user
- Outgoing audio: ElevenLabs TTS → upload as audio message

---

## 3. Twilio Voice + SMS Integration

### 3.1 Twilio Voice Architecture

Twilio voice calls work through a webhook-driven model:

```
User calls Twilio number
         |
         v
Twilio sends HTTP request to your webhook URL
         |
         v
Your server returns TwiML (XML instructions)
         |
         v
Twilio executes TwiML (play audio, gather input, record, etc.)
         |
         v
Repeat for each interaction
```

**TwiML Verbs (key ones for AI agent):**
- `<Say>` — Text-to-speech (Twilio's built-in voices or SSML)
- `<Play>` — Play an audio file URL
- `<Gather>` — Collect DTMF digits or speech input
- `<Record>` — Record caller's speech
- `<Stream>` — Bidirectional audio streaming via WebSocket (for real-time AI)
- `<Dial>` — Connect to another number (conferencing, bridging)
- `<Pause>` — Wait N seconds
- `<Redirect>` — Send call to another TwiML URL

### 3.2 Twilio Media Streams (Bidirectional Audio)

This is the critical feature for real-time AI voice agents. Media Streams provides **raw audio streaming over WebSocket** — enabling real-time speech-to-text and text-to-speech without the latency of HTTP round-trips.

**How it works:**

```
Caller ←→ Twilio ←→ WebSocket ←→ Your Server (Nexus)
                                       |
                                  STT Engine
                                       |
                                  LLM (Agent)
                                       |
                                  TTS Engine
                                       |
                                  Audio back to WebSocket
                                       ↓
                              Twilio plays to caller
```

**TwiML to start a bidirectional stream:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://your-server.com/api/voice/stream" />
    </Connect>
</Response>
```

**WebSocket Protocol:**

Messages from Twilio (incoming audio):
```json
{
    "event": "media",
    "sequenceNumber": "1",
    "media": {
        "track": "inbound",
        "chunk": "1",
        "timestamp": "5",
        "payload": "<base64-encoded-audio>"
    },
    "streamSid": "MZxxxx"
}
```

Messages to Twilio (outgoing audio):
```json
{
    "event": "media",
    "streamSid": "MZxxxx",
    "media": {
        "payload": "<base64-encoded-audio>"
    }
}
```

**Audio Format:**
- **Inbound (from caller):** mulaw (u-law), 8kHz, mono, base64 encoded
- **Outbound (to caller):** mulaw (u-law), 8kHz, mono, base64 encoded
- 20ms audio chunks (160 bytes raw = 214 bytes base64)
- ~50 WebSocket messages per second

**Key events:**
- `connected` — WebSocket connection established
- `start` — Stream started, contains `streamSid`, `callSid`, `accountSid`
- `media` — Audio chunk (both directions)
- `stop` — Stream ended
- `dtmf` — DTMF tone detected
- `mark` — Playback marker reached (for synchronization)

**Bidirectional streaming capabilities:**
- Send audio to the caller while simultaneously receiving their audio
- Clear the outbound audio buffer (for interruption handling)
- Send marks to track playback position
- Pause/resume the stream

**Clear message (for interruption handling):**
```json
{
    "event": "clear",
    "streamSid": "MZxxxx"
}
```
This clears all queued outbound audio — essential for when the user interrupts the AI.

### 3.3 Twilio SMS

SMS is simpler than voice — standard webhook-based messaging:

```python
# Send SMS
message = client.messages.create(
    body="Hello from Nexus!",
    from_='+15551234567',
    to='+15559876543'
)

# Receive SMS (webhook)
@router.post("/api/channels/sms/webhook")
async def sms_webhook(request: Request):
    form = await request.form()
    from_number = form.get("From")
    body = form.get("Body")
    response = await process_message(user_id=from_number, text=body, ...)
    twiml = MessagingResponse()
    twiml.message(response[:1600])  # SMS limit ~1600 chars with concatenation
    return Response(content=str(twiml), media_type="text/xml")
```

**SMS Considerations:**
- 160 character limit per segment (concatenated SMS up to 1600 chars)
- No rich media (MMS available in US/Canada only)
- Twilio automatically handles message segmentation
- Responses should be concise — consider a "brief mode" for SMS channel

### 3.4 Twilio Speech Recognition (Built-in STT)

Twilio has built-in speech recognition via the `<Gather>` verb:

```xml
<Gather input="speech" speechTimeout="auto"
        speechModel="experimental_conversations"
        language="en-US"
        action="/api/voice/process">
    <Say>How can I help you?</Say>
</Gather>
```

**Speech Models:**
- `default` — General purpose
- `numbers_and_commands` — Optimized for digits and short commands
- `phone_call` — Optimized for phone conversations
- `experimental_conversations` — Latest conversational model (best for AI agents)
- `experimental_utterances` — Short utterance recognition

**Limitations:**
- Not real-time — waits for speech to complete, then sends transcript via HTTP callback
- Adds 1-3 seconds latency per utterance
- For real-time AI conversation, Media Streams + external STT is better

**For real-time use cases, prefer Media Streams + Deepgram/Whisper/AssemblyAI for STT.**

### 3.5 Twilio Python SDK

```python
# pip install twilio
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
from twilio.request_validator import RequestValidator

# Initialize
client = Client(account_sid, auth_token)

# Make an outbound call
call = client.calls.create(
    url='https://your-server.com/api/voice/twiml',
    to='+15559876543',
    from_='+15551234567',
    status_callback='https://your-server.com/api/voice/status',
    status_callback_event=['initiated', 'ringing', 'answered', 'completed'],
)

# Generate TwiML for Media Streams
response = VoiceResponse()
response.say("Connecting you to Nexus AI agent.", voice='Polly.Amy')
connect = Connect()
stream = Stream(url='wss://your-server.com/api/voice/stream')
stream.parameter(name='userId', value='user123')
connect.append(stream)
response.append(connect)

# Webhook validation (IMPORTANT for security)
validator = RequestValidator(auth_token)
is_valid = validator.validate(url, params, signature)
```

### 3.6 IVR (Interactive Voice Response)

Simple IVR menu using TwiML:

```xml
<Response>
    <Gather numDigits="1" action="/api/voice/menu">
        <Say>
            Press 1 to talk to the AI agent.
            Press 2 for account status.
            Press 3 to leave a message.
        </Say>
    </Gather>
    <Say>We didn't receive any input. Goodbye!</Say>
</Response>
```

For Nexus, the IVR would be minimal — primarily a greeting before connecting to the AI agent via Media Streams.

---

## 4. ElevenLabs Voice Synthesis

### 4.1 API Overview

ElevenLabs provides high-quality, low-latency text-to-speech with multiple delivery methods:

**API Endpoints:**
1. **Standard TTS** — `POST /v1/text-to-speech/{voice_id}` — Full text in, audio out
2. **Streaming TTS** — `POST /v1/text-to-speech/{voice_id}/stream` — Text in, chunked audio stream out
3. **WebSocket TTS** — `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input` — Real-time bidirectional streaming
4. **Conversational AI** — Their own agent platform (separate product, not just TTS)

### 4.2 Streaming TTS (HTTP)

```python
import httpx

async def stream_tts(text: str, voice_id: str) -> AsyncIterator[bytes]:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
            json={
                "text": text,
                "model_id": "eleven_turbo_v2_5",  # Lowest latency
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.8,
                    "style": 0.0,
                    "use_speaker_boost": True,
                },
                "output_format": "ulaw_8000",  # Twilio-compatible!
            },
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
            },
        )
        async for chunk in response.aiter_bytes():
            yield chunk
```

### 4.3 WebSocket TTS (Real-Time)

The WebSocket API is designed for real-time conversational use — you can send text incrementally as the LLM generates it:

```python
import websockets
import json

async def realtime_tts(voice_id: str):
    uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
    params = f"?model_id=eleven_turbo_v2_5&output_format=ulaw_8000"

    async with websockets.connect(uri + params) as ws:
        # Send BOS (beginning of stream)
        await ws.send(json.dumps({
            "text": " ",  # Space signals BOS
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
            },
            "xi_api_key": api_key,
        }))

        # Stream text chunks as LLM generates them
        for chunk in llm_stream():
            await ws.send(json.dumps({"text": chunk}))

        # Send EOS (end of stream)
        await ws.send(json.dumps({"text": ""}))

        # Receive audio chunks
        while True:
            response = json.loads(await ws.recv())
            if response.get("audio"):
                audio_bytes = base64.b64decode(response["audio"])
                yield audio_bytes
            if response.get("isFinal"):
                break
```

### 4.4 Voice Models

| Model | Latency | Quality | Languages | Best For |
|-------|---------|---------|-----------|----------|
| `eleven_turbo_v2_5` | ~300ms TTFB | Very Good | 32 languages | **Real-time conversation** |
| `eleven_multilingual_v2` | ~500ms TTFB | Excellent | 29 languages | High-quality narration |
| `eleven_flash_v2_5` | ~150ms TTFB | Good | English-focused | Ultra-low latency |
| `eleven_monolingual_v1` | ~400ms TTFB | Good | English only | Simple TTS |

**For Nexus voice calls: Use `eleven_turbo_v2_5`** — best balance of latency and quality.
**For WhatsApp voice messages: Use `eleven_multilingual_v2`** — latency less critical, quality matters more.

### 4.5 Output Formats

| Format | Sample Rate | Use Case |
|--------|-------------|----------|
| `mp3_44100_128` | 44.1kHz, 128kbps | Default, high quality |
| `mp3_22050_32` | 22kHz, 32kbps | Smaller files |
| `pcm_16000` | 16kHz, 16-bit | Raw PCM for processing |
| `pcm_24000` | 24kHz, 16-bit | Higher quality PCM |
| `ulaw_8000` | 8kHz, u-law | **Twilio-compatible** |
| `ogg_opus` | Variable | WhatsApp voice messages |

**Critical: ElevenLabs supports `ulaw_8000` natively** — this means zero audio conversion needed for Twilio Media Streams. This is a major latency win.

### 4.6 Voice Cloning

ElevenLabs offers two cloning approaches:

1. **Instant Voice Cloning (IVC):**
   - Upload 1-5 minutes of clean audio samples
   - Clone created in seconds
   - Good quality, works with all models
   - Available on all paid plans

2. **Professional Voice Cloning (PVC):**
   - Requires 30+ minutes of studio-quality audio
   - Takes hours to train
   - Near-indistinguishable from original
   - Enterprise plan only

For Nexus, **IVC is sufficient** — users can give the agent a custom voice with just a few audio samples.

```python
# Create a cloned voice
voice = client.clone(
    name="nexus-agent",
    description="Nexus AI agent voice",
    files=["sample1.mp3", "sample2.mp3"],
)
voice_id = voice.voice_id
```

### 4.7 ElevenLabs Python SDK

```python
# pip install elevenlabs
from elevenlabs import ElevenLabs
from elevenlabs import stream as play_stream

client = ElevenLabs(api_key="your-api-key")

# Simple TTS
audio = client.text_to_speech.convert(
    text="Hello, I'm your Nexus AI agent.",
    voice_id="pNInz6obpgDQGcFmaJgB",  # Adam voice
    model_id="eleven_turbo_v2_5",
    output_format="ulaw_8000",
)

# Streaming TTS
audio_stream = client.text_to_speech.convert_as_stream(
    text="Hello, I'm your Nexus AI agent.",
    voice_id="pNInz6obpgDQGcFmaJgB",
    model_id="eleven_turbo_v2_5",
    output_format="ulaw_8000",
)

for chunk in audio_stream:
    # Send to Twilio WebSocket
    pass

# List available voices
voices = client.voices.get_all()
for voice in voices.voices:
    print(f"{voice.name}: {voice.voice_id}")
```

### 4.8 ElevenLabs Conversational AI

ElevenLabs launched their own **Conversational AI** platform — a full voice agent system with:
- Built-in STT (speech-to-text)
- LLM integration (OpenAI, Anthropic, custom)
- TTS (their own)
- Tool calling support
- WebSocket-based real-time conversation

**Relevance to Nexus:** This is a competing product, not something to integrate. Nexus's approach (Twilio + custom STT + Nexus LLM + ElevenLabs TTS) is more flexible and allows using local LLMs. However, ElevenLabs' Conversational AI architecture validates the general approach: WebSocket bidirectional audio with streaming STT and TTS.

---

## 5. Real-Time Voice Conversation Architecture

### 5.1 The Full Pipeline

```
User speaks into phone
         |
    Twilio captures audio (mulaw 8kHz)
         |
    Twilio Media Streams WebSocket → Nexus backend
         |
    Speech-to-Text (Deepgram/Whisper)
         |  ← ~200-400ms for streaming STT
    Text transcript
         |
    Nexus Agent (LLM) — process_message()
         |  ← ~500-3000ms for LLM generation
    Response text (streaming)
         |
    ElevenLabs TTS (WebSocket streaming, ulaw_8000)
         |  ← ~200-400ms TTFB, then continuous
    Audio chunks (mulaw)
         |
    Twilio Media Streams WebSocket ← Nexus backend
         |
    Twilio plays audio to caller
         |
    User hears AI response
```

### 5.2 Latency Budget

Target: **< 1500ms** from end of user speech to first audio of AI response.

| Stage | Target | Notes |
|-------|--------|-------|
| Twilio → Nexus WebSocket | 20-50ms | Network latency |
| STT processing | 200-500ms | Deepgram streaming: ~200ms; Whisper: ~500ms |
| LLM inference (TTFB) | 300-1500ms | Ollama warm: ~500ms; Claude API: ~300ms |
| TTS generation (TTFB) | 200-400ms | ElevenLabs turbo: ~300ms |
| Nexus → Twilio WebSocket | 20-50ms | Network latency |
| **Total (best case)** | **~750ms** | Deepgram + warm Ollama + ElevenLabs turbo |
| **Total (typical)** | **~1200ms** | Streaming STT + Claude API + ElevenLabs |
| **Total (worst case)** | **~2500ms** | Cold Ollama + slow STT + ElevenLabs multilingual |

**Key optimization: Pipeline the stages.** Don't wait for the full LLM response before starting TTS. Stream LLM text directly into ElevenLabs WebSocket TTS, which streams audio directly into Twilio. The user hears the first word of the response before the LLM finishes generating.

### 5.3 Speech-to-Text Options

| Engine | Type | Latency | Accuracy | Cost | Self-Hosted |
|--------|------|---------|----------|------|-------------|
| **Deepgram** | Cloud API | ~200ms streaming | Excellent | $0.0043/min | No (cloud only) |
| **Whisper (OpenAI)** | Cloud API | ~500ms batch | Very Good | $0.006/min | No |
| **Whisper.cpp** | Local | ~300ms (M4 Max) | Very Good | Free | Yes |
| **Faster-Whisper** | Local | ~250ms (GPU) | Very Good | Free | Yes |
| **AssemblyAI** | Cloud API | ~300ms streaming | Excellent | $0.01/min (Universal-2) |  No |
| **Google Cloud STT** | Cloud API | ~300ms streaming | Good | $0.006/min (v2) | No |
| **Vosk** | Local | ~100ms streaming | Good | Free | Yes |

**Recommendation for Nexus:**
- **Primary: Deepgram** — Lowest latency streaming STT, excellent accuracy, WebSocket API
- **Fallback: Whisper.cpp / Faster-Whisper** — Local, free, runs well on M4 Max

Deepgram streaming STT is ideal because it provides **interim results** (partial transcripts as the user speaks) and **final results** (corrected transcript after speech ends), enabling the AI to start processing before the user finishes speaking.

```python
# Deepgram streaming STT via WebSocket
import websockets
import json

async def transcribe_stream(audio_stream):
    uri = "wss://api.deepgram.com/v1/listen"
    params = "?encoding=mulaw&sample_rate=8000&channels=1&model=nova-2&smart_format=true"

    async with websockets.connect(
        uri + params,
        extra_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
    ) as ws:
        async def send_audio():
            async for chunk in audio_stream:
                await ws.send(chunk)
            await ws.send(json.dumps({"type": "CloseStream"}))

        async def receive_transcript():
            async for msg in ws:
                data = json.loads(msg)
                transcript = data.get("channel", {}).get("alternatives", [{}])[0].get("transcript", "")
                is_final = data.get("is_final", False)
                if transcript:
                    yield transcript, is_final

        # Run both concurrently
        ...
```

### 5.4 Interruption Handling

When the user speaks while the AI is responding (barge-in), the system must:

1. **Detect speech** — Voice Activity Detection (VAD) on the inbound audio stream
2. **Stop TTS playback** — Send `clear` event to Twilio to flush outbound audio buffer
3. **Cancel LLM generation** — Set abort flag on the current AgentRunner
4. **Start new STT** — Begin transcribing the user's new utterance
5. **Process new input** — Route new transcript through agent pipeline

```python
# Interruption handling in the voice WebSocket handler
async def handle_voice_stream(websocket, path):
    vad = VoiceActivityDetector()
    is_speaking = False
    current_generation = None

    async for message in websocket:
        data = json.loads(message)

        if data["event"] == "media":
            audio_chunk = base64.b64decode(data["media"]["payload"])

            # Check for voice activity (user speaking)
            if vad.is_speech(audio_chunk):
                if not is_speaking and current_generation:
                    # User interrupted — stop AI response
                    is_speaking = True
                    current_generation.cancel()
                    await websocket.send(json.dumps({
                        "event": "clear",
                        "streamSid": stream_sid
                    }))
                # Feed audio to STT
                await stt.feed(audio_chunk)
            else:
                if is_speaking:
                    # User stopped speaking — process transcript
                    is_speaking = False
                    transcript = await stt.finalize()
                    current_generation = asyncio.create_task(
                        generate_and_stream_response(transcript, websocket, stream_sid)
                    )
```

### 5.5 Voice Activity Detection (VAD)

Options for VAD:
- **WebRTC VAD** (`webrtcvad` Python package) — Fast, CPU-only, works on mulaw
- **Silero VAD** (`torch` + `silero-vad`) — More accurate but heavier, needs PyTorch
- **Energy-based** — Simple RMS threshold on audio frames (least accurate)

**Recommendation: WebRTC VAD** — lightweight, runs on any platform, well-tested, handles phone-quality audio well.

```python
import webrtcvad

vad = webrtcvad.Vad(2)  # Aggressiveness: 0-3 (higher = more aggressive)

def is_speech(audio_frame: bytes, sample_rate: int = 8000) -> bool:
    """Check if a 20ms audio frame contains speech."""
    return vad.is_speech(audio_frame, sample_rate)
```

### 5.6 Audio Format Conversion

**Good news: Minimal conversion needed.**

- Twilio Media Streams: mulaw 8kHz (both directions)
- ElevenLabs: supports `ulaw_8000` output format natively
- Deepgram: accepts mulaw 8kHz input natively

The only conversion needed is if using local Whisper STT (which expects 16kHz PCM):

```python
import audioop

def mulaw_to_pcm16k(mulaw_8k: bytes) -> bytes:
    """Convert mulaw 8kHz to PCM 16kHz for Whisper."""
    # Decode mulaw to PCM
    pcm_8k = audioop.ulaw2lin(mulaw_8k, 2)
    # Upsample 8kHz to 16kHz
    pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
    return pcm_16k
```

### 5.7 Buffering Strategy

For smooth conversation, implement a three-buffer system:

1. **STT Input Buffer** — Accumulates 20ms audio frames, feeds to STT in batches of 100-200ms
2. **LLM Output Buffer** — Accumulates LLM tokens, sends to TTS in sentence-boundary chunks
3. **TTS Output Buffer** — Accumulates audio chunks, sends to Twilio at constant rate

The LLM-to-TTS buffering is the most critical. Strategy:

```python
async def stream_llm_to_tts(llm_stream, tts_client, twilio_ws, stream_sid):
    """Stream LLM text output through TTS to Twilio."""
    text_buffer = ""
    sentence_endings = {'.', '!', '?', ':', ';', '\n'}

    async for token in llm_stream:
        text_buffer += token

        # Flush at sentence boundaries (natural pause points)
        if text_buffer and text_buffer[-1] in sentence_endings and len(text_buffer) > 10:
            # Send accumulated text to TTS
            async for audio_chunk in tts_client.stream(text_buffer):
                # Send audio to Twilio
                await twilio_ws.send(json.dumps({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {
                        "payload": base64.b64encode(audio_chunk).decode()
                    }
                }))
            text_buffer = ""

    # Flush remaining text
    if text_buffer.strip():
        async for audio_chunk in tts_client.stream(text_buffer):
            await twilio_ws.send(json.dumps({
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": base64.b64encode(audio_chunk).decode()}
            }))
```

---

## 6. Open-Source Voice Agent Frameworks

### 6.1 Pipecat (by Daily.co)

**Repository:** github.com/pipecat-ai/pipecat
**License:** BSD-2-Clause
**Stars:** ~8K+ (as of early 2025)
**Language:** Python

**Architecture:**
- Frame-based pipeline processing (audio frames flow through processing stages)
- Each stage is a "processor" (STT, LLM, TTS, VAD, etc.)
- Processors connected via async queues
- Built-in support for: Twilio, Daily, WebSocket, Local audio

**Key components:**
- `Pipeline` — DAG of processors
- `InputTransport` — Audio input (Twilio, Daily, WebSocket)
- `OutputTransport` — Audio output
- `STTService` — Deepgram, Whisper, Google, Azure
- `LLMService` — OpenAI, Anthropic, Ollama, local models
- `TTSService` — ElevenLabs, Azure, Google, Play.ht, Cartesia
- `VADAnalyzer` — Silero VAD for interruption detection
- `UserIdleProcessor` — Detect when user hasn't spoken
- `FunctionCallProcessor` — LLM tool/function calling

**Why it matters for Nexus:**
- Pipecat's pipeline architecture maps well to Nexus's needs
- Already has Twilio transport + ElevenLabs TTS integration
- Handles VAD, interruption, buffering out of the box
- BUT: it's designed as the primary framework (wants to own the LLM interaction)
- Nexus would need to either: (a) use Pipecat for voice only, routing to its own agent, or (b) adapt Pipecat's transport/TTS code into Nexus's own pipeline

**Integration approach:** Use Pipecat's `TwilioTransport` and audio processing pipeline, but replace the LLM processor with a custom one that calls Nexus's `process_message()`.

### 6.2 Vocode

**Repository:** github.com/vocodedev/vocode-core
**License:** MIT
**Stars:** ~3K+ (as of early 2025)
**Language:** Python

**Architecture:**
- Conversation class orchestrates STT → Agent → TTS pipeline
- Pluggable synthesizers (ElevenLabs, Azure, Google, Play.ht, Bark)
- Pluggable transcribers (Deepgram, AssemblyAI, Google, Whisper)
- Pluggable agents (custom, OpenAI function calling)
- Twilio integration via TwiML + Media Streams

**Vocode's Twilio integration:**
```python
from vocode.streaming.telephony.conversation.twilio_conversation import TwilioConversation

conversation = TwilioConversation(
    transcriber=DeepgramTranscriber(api_key=...),
    agent=CustomAgent(config=...),
    synthesizer=ElevenLabsSynthesizer(api_key=..., voice_id=...),
)
```

**Status:** Development has slowed. Vocode shifted focus to their hosted platform. Open-source version is usable but may have stale dependencies.

### 6.3 LiveKit Agents

**Repository:** github.com/livekit/agents
**License:** Apache-2.0
**Stars:** ~4K+ (as of early 2025)
**Language:** Python

**Architecture:**
- Built on LiveKit (open-source WebRTC infrastructure)
- Agent framework for voice/video AI applications
- Plugin system: STT, TTS, LLM, VAD
- Handles WebRTC, not Twilio (different transport layer)

**Strengths:**
- Best WebRTC integration (browser-to-agent voice)
- Low latency (WebRTC is ~100ms vs Twilio's ~200ms)
- Open-source infrastructure (can self-host LiveKit server)
- Active development, well-funded

**Weakness for Nexus:**
- Phone calls require LiveKit SIP Bridge (extra infrastructure)
- Different architecture than Twilio (WebRTC vs PSTN)
- More complex to self-host

**When to consider:** If Nexus wants browser-based voice chat (in the React chat-ui), LiveKit is superior to Twilio for web-to-agent voice. Could be a Phase 2 addition after Twilio phone integration.

### 6.4 Commercial Platforms (Architecture Reference)

**Retell AI:**
- Fully managed voice agent platform
- Custom LLM integration via WebSocket or REST API
- Handles Twilio integration, STT, TTS, VAD internally
- Pricing: $0.07-0.15/min
- **Architecture insight:** Uses a "response orchestrator" that manages turn-taking, interruptions, and filler audio (e.g., "um", "let me think") to feel natural

**Vapi:**
- Similar to Retell — managed voice AI platform
- Stronger on Twilio integration and phone number management
- Custom tool/function calling support
- Pricing: $0.05-0.10/min
- **Architecture insight:** Implements "latency optimization mode" that starts TTS on first sentence while LLM still generates rest

**Bland.ai:**
- Enterprise voice AI (Twilio-based)
- Emphasizes "pathway" system for call flows (like a visual IVR builder)
- **Architecture insight:** Pre-generates common responses for sub-100ms latency on known conversation patterns

### 6.5 Framework Comparison for Nexus

| Framework | Twilio Support | ElevenLabs | Custom LLM | Self-Hosted | Complexity | Recommendation |
|-----------|---------------|------------|------------|-------------|------------|----------------|
| **Pipecat** | Yes (transport) | Yes (TTS) | Yes (custom processor) | Yes | Medium | **Best fit** |
| Vocode | Yes | Yes | Yes | Yes | Medium | Stale, not recommended |
| LiveKit | Via SIP bridge | Via plugin | Yes | Yes (WebRTC) | High | Phase 2 for web voice |
| Custom | Yes | Yes | Yes | Yes | High | Most flexible |

**Recommendation:**

1. **Phase 1: Custom implementation** — Build Nexus's own voice pipeline using Twilio SDK + ElevenLabs SDK + Deepgram SDK directly. This gives maximum control and integrates cleanly with the existing `process_message()` architecture. The components are well-documented and the glue code is ~500-800 lines.

2. **Phase 2 (optional): Evaluate Pipecat** — If the custom implementation's audio handling becomes complex (buffering, timing, interruptions), consider adopting Pipecat's audio pipeline for the transport layer while keeping Nexus's LLM/agent logic.

---

## 7. Unified Communications Layer

### 7.1 Architecture Design

The key insight: All channels eventually need to do the same thing — receive a message, process it through the Nexus agent, and send a response. The differences are in transport, media handling, and response formatting.

```
┌─────────────────────────────────────────────────────────────┐
│                    Channel Adapters                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ WebSocket│ │ Telegram │ │ WhatsApp │ │  Twilio  │       │
│  │ Adapter  │ │ Adapter  │ │ Adapter  │ │Voice/SMS │       │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │
│       │            │            │            │              │
│       ▼            ▼            ▼            ▼              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            Unified Message Bus                       │   │
│  │                                                      │   │
│  │  ChannelMessage {                                    │   │
│  │    channel: "whatsapp" | "telegram" | "sms" | ...    │   │
│  │    user_id: str                                      │   │
│  │    conv_id: str                                      │   │
│  │    text: str                                         │   │
│  │    media: list[MediaAttachment]                      │   │
│  │    metadata: dict  (channel-specific data)           │   │
│  │    reply_callback: async (response) -> None          │   │
│  │  }                                                   │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            Message Processor                         │   │
│  │  (existing process_message() + channel awareness)    │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            Response Formatter                        │   │
│  │                                                      │   │
│  │  WebSocket → Markdown (full formatting)              │   │
│  │  Telegram → Markdown (subset, 4096 chars)            │   │
│  │  WhatsApp → Plain text + media (4096 chars)          │   │
│  │  SMS → Plain text (160 chars, concise mode)          │   │
│  │  Voice → Short sentences (for TTS naturalness)       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Normalized Message Format

```python
@dataclass
class ChannelMessage:
    """Normalized message from any communication channel."""
    channel: str          # "websocket", "telegram", "whatsapp", "sms", "voice"
    user_id: str          # Channel-specific user identifier
    conv_id: str | None   # Nexus conversation ID (or None for new)
    text: str             # Message text (transcribed for voice)
    media: list[MediaAttachment] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # Channel-specific extras
    timestamp: float = field(default_factory=time.time)

@dataclass
class MediaAttachment:
    """Media attached to a message."""
    type: str             # "image", "audio", "video", "document", "location"
    url: str | None       # URL to fetch the media
    data: bytes | None    # Raw bytes (for inline media)
    mime_type: str = ""
    filename: str = ""
    caption: str = ""

@dataclass
class ChannelResponse:
    """Response to send back through a channel."""
    text: str
    media: list[MediaAttachment] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # Channel-specific extras
    # e.g., metadata={"buttons": [...]} for WhatsApp interactive
```

### 7.3 Channel Adapter Interface

```python
class ChannelAdapter(abc.ABC):
    """Base class for all communication channel adapters."""

    name: str = "base"

    @abc.abstractmethod
    async def start(self) -> None:
        """Initialize the channel (connect, start polling, etc.)."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Gracefully shutdown the channel."""

    @abc.abstractmethod
    async def send(self, user_id: str, response: ChannelResponse) -> bool:
        """Send a response to a specific user. Returns True on success."""

    @property
    @abc.abstractmethod
    def max_message_length(self) -> int:
        """Maximum text length for this channel."""

    @abc.abstractmethod
    def format_response(self, text: str) -> str:
        """Format AI response for this channel (strip markdown, truncate, etc.)."""

    async def health_check(self) -> dict:
        """Return channel health status."""
        return {"status": "ok", "channel": self.name}
```

### 7.4 Conversation Continuity Across Channels

Users should be able to start a conversation on WhatsApp and continue on web (or vice versa):

**Identity Resolution:**
- Phone number → Nexus user mapping (via pairing, same as Telegram)
- Multiple channels can map to the same Nexus user
- `channel_identities` table: `nexus_user_id, channel, channel_user_id, paired_at, active`

**Conversation Routing:**
- Each channel gets its own default conversation (like Telegram currently)
- User can explicitly link a channel conversation to a web conversation
- System prompt includes channel context: "The user is currently on WhatsApp"

### 7.5 Response Formatting Per Channel

| Channel | Max Length | Format | Media | Special |
|---------|-----------|--------|-------|---------|
| WebSocket | Unlimited | Full Markdown | Images, files | Streaming, typing indicator |
| Telegram | 4096 chars | Telegram Markdown | Images, docs, audio | Chunking, parse_mode |
| WhatsApp | 4096 chars | Plain text | Images, docs, audio, buttons | Template msgs, reactions |
| SMS | 1600 chars | Plain text only | None (MMS in US) | Must be concise |
| Voice | ~30 seconds | Spoken text | None | Short sentences, no lists |

**Voice-specific formatting:**
- Strip all Markdown formatting (no `**bold**`, `# headers`, `- bullets`)
- Replace code blocks with verbal descriptions ("The code to do this is...")
- Convert lists to natural language ("First, ... Second, ... Third, ...")
- Break into short sentences (< 20 words each) for natural TTS
- Remove URLs (say "I'll send you the link" instead)
- Numbers: write out as words for natural speech ("forty-two" not "42")

---

## 8. Implementation Architecture

### 8.1 New Files

```
backend/
├── channels/
│   ├── __init__.py          # existing
│   ├── base.py              # NEW: ChannelAdapter ABC + ChannelMessage dataclasses
│   ├── telegram.py          # MODIFY: refactor to use ChannelAdapter interface
│   ├── whatsapp.py          # NEW: WhatsApp via Twilio adapter
│   ├── sms.py               # NEW: SMS via Twilio adapter
│   └── voice.py             # NEW: Voice via Twilio Media Streams
│
├── voice/
│   ├── __init__.py          # NEW
│   ├── stt.py               # NEW: Speech-to-text (Deepgram + Whisper fallback)
│   ├── tts.py               # NEW: Text-to-speech (ElevenLabs wrapper)
│   ├── vad.py               # NEW: Voice activity detection (WebRTC VAD)
│   ├── audio.py             # NEW: Audio format conversion utilities
│   └── pipeline.py          # NEW: Voice conversation pipeline orchestrator
│
├── routers/
│   ├── webhooks.py          # NEW: Twilio webhook endpoints (voice, SMS, WhatsApp)
│   └── ws.py                # MODIFY: minimal — add voice WebSocket endpoint
│
├── core/
│   ├── message_processor.py # MODIFY: accept ChannelMessage, add channel awareness
│   └── response_formatter.py # NEW: per-channel response formatting
```

### 8.2 Database Schema Additions

```sql
-- Channel identity mapping (link phone numbers / accounts to Nexus users)
CREATE TABLE channel_identities (
    id SERIAL PRIMARY KEY,
    nexus_user_id TEXT NOT NULL,       -- Internal user ID
    channel TEXT NOT NULL,             -- "whatsapp", "sms", "voice", "telegram"
    channel_user_id TEXT NOT NULL,     -- e.g., "whatsapp:+15551234567"
    display_name TEXT,
    paired_at TIMESTAMPTZ DEFAULT NOW(),
    active BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    UNIQUE(channel, channel_user_id)
);

-- Voice call records
CREATE TABLE voice_calls (
    id SERIAL PRIMARY KEY,
    call_sid TEXT UNIQUE NOT NULL,     -- Twilio Call SID
    stream_sid TEXT,                   -- Twilio Stream SID
    user_id TEXT NOT NULL,
    conv_id TEXT NOT NULL,
    direction TEXT NOT NULL,           -- "inbound" or "outbound"
    status TEXT DEFAULT 'initiated',   -- initiated, ringing, in-progress, completed, failed
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    duration_seconds INTEGER,
    transcript TEXT,                   -- Full call transcript
    model_used TEXT,
    tts_chars INTEGER DEFAULT 0,       -- ElevenLabs characters used
    cost_estimate DECIMAL(10, 4),
    metadata JSONB DEFAULT '{}'
);

-- Channel message log (audit trail)
CREATE TABLE channel_messages (
    id SERIAL PRIMARY KEY,
    channel TEXT NOT NULL,
    direction TEXT NOT NULL,           -- "inbound" or "outbound"
    user_id TEXT NOT NULL,
    conv_id TEXT,
    content TEXT,
    media_urls TEXT[],
    status TEXT DEFAULT 'delivered',
    external_id TEXT,                  -- Twilio Message SID, etc.
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);
```

### 8.3 Config Settings (DB-backed via ConfigManager)

```python
# Twilio Settings (category: "communications")
TWILIO_ACCOUNT_SID = ""
TWILIO_AUTH_TOKEN = ""          # encrypted
TWILIO_PHONE_NUMBER = ""        # e.g., "+15551234567"
TWILIO_WHATSAPP_NUMBER = ""     # e.g., "whatsapp:+15551234567"

# ElevenLabs Settings (category: "voice")
ELEVENLABS_API_KEY = ""         # encrypted
ELEVENLABS_VOICE_ID = ""        # Default voice for TTS
ELEVENLABS_MODEL = "eleven_turbo_v2_5"

# Speech-to-Text Settings (category: "voice")
STT_PROVIDER = "deepgram"       # "deepgram", "whisper_local", "whisper_api"
DEEPGRAM_API_KEY = ""           # encrypted

# Channel Toggles (category: "channels")
WHATSAPP_ENABLED = False
SMS_ENABLED = False
VOICE_ENABLED = False
VOICE_GREETING = "Hello! You're connected to Nexus AI. How can I help you?"
VOICE_MAX_DURATION = 600        # Max call duration in seconds (10 min)

# Webhook URLs (auto-configured, but overridable)
TWILIO_WEBHOOK_BASE_URL = ""    # e.g., "https://your-domain.com" or ngrok URL
```

### 8.4 Voice Pipeline Detail

```python
class VoicePipeline:
    """Orchestrates real-time voice conversation over Twilio Media Streams.

    Lifecycle:
    1. Twilio calls webhook → returns TwiML with <Stream> pointing to our WebSocket
    2. WebSocket connection established → pipeline starts
    3. Audio flows: Twilio → STT → Agent → TTS → Twilio
    4. Interruption handling via VAD on inbound audio
    5. Call ends → cleanup, save transcript
    """

    def __init__(
        self,
        stream_sid: str,
        call_sid: str,
        user_id: str,
        conv_id: str,
        twilio_ws: WebSocket,
        stt: STTEngine,
        tts: TTSEngine,
        vad: VADDetector,
        message_handler: Callable,
    ):
        self.stream_sid = stream_sid
        self.call_sid = call_sid
        self.twilio_ws = twilio_ws
        self.stt = stt
        self.tts = tts
        self.vad = vad
        self.message_handler = message_handler
        self._is_speaking = False        # AI is currently outputting audio
        self._user_speaking = False      # User is currently speaking
        self._abort = asyncio.Event()
        self._transcript: list[dict] = []

    async def run(self):
        """Main pipeline loop — runs until call ends."""
        # Play greeting
        await self._say(self.greeting)

        # Process inbound audio
        async for message in self.twilio_ws:
            data = json.loads(message)

            if data["event"] == "media":
                await self._handle_audio(data)
            elif data["event"] == "stop":
                break

    async def _handle_audio(self, data: dict):
        """Process an inbound audio chunk."""
        audio = base64.b64decode(data["media"]["payload"])

        # VAD: detect if user is speaking
        has_speech = self.vad.is_speech(audio)

        if has_speech:
            if not self._user_speaking:
                self._user_speaking = True
                if self._is_speaking:
                    # INTERRUPTION: user started talking while AI was responding
                    await self._interrupt()
            # Feed audio to STT
            await self.stt.feed(audio)
        else:
            if self._user_speaking:
                # User stopped speaking — get final transcript and process
                self._user_speaking = False
                transcript = await self.stt.finalize()
                if transcript.strip():
                    self._transcript.append({"role": "user", "text": transcript})
                    await self._process_and_respond(transcript)

    async def _process_and_respond(self, text: str):
        """Process user text through agent and stream TTS response."""
        self._is_speaking = True
        self._abort.clear()

        # Get AI response (streaming)
        response = await self.message_handler(self.user_id, text, conv_id=self.conv_id)

        if not self._abort.is_set():
            # Stream response through TTS to Twilio
            await self._say(response)
            self._transcript.append({"role": "assistant", "text": response})

        self._is_speaking = False

    async def _say(self, text: str):
        """Convert text to speech and stream to Twilio."""
        async for audio_chunk in self.tts.stream(text):
            if self._abort.is_set():
                break
            await self._send_audio(audio_chunk)

    async def _send_audio(self, audio: bytes):
        """Send audio chunk to Twilio."""
        await self.twilio_ws.send_json({
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {"payload": base64.b64encode(audio).decode()}
        })

    async def _interrupt(self):
        """Handle user interruption — stop AI output."""
        self._abort.set()
        # Clear Twilio's outbound audio buffer
        await self.twilio_ws.send_json({
            "event": "clear",
            "streamSid": self.stream_sid
        })
        # Reset STT for new utterance
        await self.stt.reset()
```

### 8.5 Webhook Router

```python
# backend/routers/webhooks.py

from fastapi import APIRouter, Request, Response
from twilio.request_validator import RequestValidator

router = APIRouter(prefix="/api/channels", tags=["channels"])

@router.post("/voice/incoming")
async def voice_incoming(request: Request):
    """Handle incoming Twilio voice call — return TwiML to start Media Stream."""
    form = await request.form()
    from_number = form.get("From", "")
    call_sid = form.get("CallSid", "")

    # Validate Twilio signature (IMPORTANT for security)
    # ...

    response = VoiceResponse()
    response.say(state.cfg.get("VOICE_GREETING", "Hello! Connecting you to Nexus."),
                 voice="Polly.Amy")

    connect = Connect()
    stream = Stream(url=f"wss://{state.cfg.get('TWILIO_WEBHOOK_BASE_URL')}/api/voice/stream")
    stream.parameter(name="callSid", value=call_sid)
    stream.parameter(name="from", value=from_number)
    connect.append(stream)
    response.append(connect)

    return Response(content=str(response), media_type="text/xml")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """Handle incoming WhatsApp message via Twilio."""
    form = await request.form()
    from_number = form.get("From", "")      # "whatsapp:+15551234567"
    body = form.get("Body", "")
    num_media = int(form.get("NumMedia", 0))

    # Process media if present
    media = []
    for i in range(num_media):
        media.append(MediaAttachment(
            type=_classify_media(form.get(f"MediaContentType{i}", "")),
            url=form.get(f"MediaUrl{i}", ""),
            mime_type=form.get(f"MediaContentType{i}", ""),
        ))

    # Voice message → transcribe
    if media and media[0].type == "audio":
        body = await transcribe_audio(media[0].url)

    # Route through message processor
    response_text = await process_message(
        user_id=from_number, text=body, channel="whatsapp", ...
    )

    # Format response for WhatsApp
    formatted = format_for_whatsapp(response_text)

    twiml = MessagingResponse()
    twiml.message(formatted)
    return Response(content=str(twiml), media_type="text/xml")


@router.post("/sms/webhook")
async def sms_webhook(request: Request):
    """Handle incoming SMS via Twilio."""
    form = await request.form()
    from_number = form.get("From", "")
    body = form.get("Body", "")

    response_text = await process_message(
        user_id=from_number, text=body, channel="sms", ...
    )

    # SMS must be concise
    formatted = format_for_sms(response_text)

    twiml = MessagingResponse()
    twiml.message(formatted)
    return Response(content=str(twiml), media_type="text/xml")
```

### 8.6 Twilio Webhook Security

Every webhook request from Twilio includes an `X-Twilio-Signature` header. Validating this is critical to prevent spoofed requests:

```python
from twilio.request_validator import RequestValidator

async def validate_twilio_request(request: Request) -> bool:
    """Validate that a request actually came from Twilio."""
    validator = RequestValidator(auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    form = await request.form()
    params = dict(form)
    return validator.validate(url, params, signature)
```

### 8.7 Ngrok / Tunnel for Development

Twilio webhooks need a publicly accessible URL. For local development:

```bash
# Install ngrok
brew install ngrok

# Start tunnel to Nexus backend
ngrok http 8080

# Use the ngrok URL as TWILIO_WEBHOOK_BASE_URL
# e.g., https://abc123.ngrok-free.app
```

For production, Nexus needs either:
- A public server with proper domain + TLS
- Cloudflare Tunnel (free, stable)
- Tailscale Funnel (if already using Tailscale)

---

## 9. Pricing Analysis

### 9.1 Twilio Pricing (as of early 2025)

| Service | Price | Unit |
|---------|-------|------|
| Phone number (US local) | $1.15/mo | Per number |
| Phone number (toll-free) | $2.15/mo | Per number |
| Inbound voice call | $0.0085/min | Per minute |
| Outbound voice call (US) | $0.014/min | Per minute |
| Media Streams | Included | With voice calls |
| SMS inbound | $0.0079/msg | Per message |
| SMS outbound (US) | $0.0079/msg | Per message |
| WhatsApp (service conv) | ~$0.005/conv | Per 24h window |
| WhatsApp (utility conv) | ~$0.005/conv | Per 24h window |
| WhatsApp (marketing conv) | ~$0.025/conv | Per 24h window |
| WhatsApp per-message | +$0.005/msg | Twilio surcharge |

**Estimated monthly cost for moderate use:**
- 500 WhatsApp conversations: ~$5-15
- 100 voice minutes: ~$1.50-3.00
- 200 SMS messages: ~$3.00
- Phone number: ~$1.15
- **Total Twilio: ~$10-22/mo**

### 9.2 ElevenLabs Pricing (as of early 2025)

| Plan | Price | Characters/mo | Notes |
|------|-------|---------------|-------|
| Free | $0 | 10,000 chars | 3 custom voices, no API |
| Starter | $5/mo | 30,000 chars | API access, 10 voices |
| Creator | $22/mo | 100,000 chars | Instant voice cloning |
| Pro | $99/mo | 500,000 chars | 96kbps, priority queue |
| Scale | $330/mo | 2,000,000 chars | Low latency, highest quality |
| Business | $1,320/mo | 11,000,000 chars | Enterprise features |

**Character estimation:**
- Average AI response: ~200 characters
- Average voice call: ~10 exchanges = ~2,000 chars
- 100 voice calls/month: ~200,000 chars → Pro plan ($99/mo)
- WhatsApp voice messages (sporadic): ~10,000 chars/mo

**Estimated monthly cost: $22-99/mo** depending on voice call volume.

### 9.3 Speech-to-Text Pricing

| Provider | Price | Model | Notes |
|----------|-------|-------|-------|
| Deepgram | $0.0043/min | Nova-2 | Best streaming latency |
| Deepgram | $0.0059/min | Whisper Cloud | Hosted Whisper |
| OpenAI Whisper | $0.006/min | whisper-1 | Batch only, no streaming |
| AssemblyAI | $0.01/min | Universal-2 | Best accuracy |
| Google Cloud STT | $0.006/min | chirp_2 | Good multilingual |
| Whisper.cpp (local) | $0 | Any Whisper model | Runs on M4 Max |

**Recommendation: Deepgram Nova-2 for production, Whisper.cpp for development/fallback.**

100 voice minutes/month on Deepgram: ~$0.43/mo (negligible).

### 9.4 Total Estimated Monthly Cost

| Component | Low Use (50 calls, 200 WA msgs) | Medium Use (200 calls, 1K WA msgs) | High Use (1K calls, 5K WA msgs) |
|-----------|----------------------------------|-------------------------------------|----------------------------------|
| Twilio (all channels) | ~$8 | ~$25 | ~$120 |
| ElevenLabs TTS | ~$22 (Creator) | ~$99 (Pro) | ~$330 (Scale) |
| Deepgram STT | ~$0.25 | ~$1 | ~$4 |
| **Total** | **~$30/mo** | **~$125/mo** | **~$454/mo** |

---

## 10. Recommended Implementation Plan

### Phase 1: WhatsApp + SMS (1-2 sessions)

**Why first:** Builds on existing Telegram architecture. Text-based channels are simpler than voice. Validates the unified communications layer.

1. Create `channels/base.py` — ChannelAdapter ABC, ChannelMessage/ChannelResponse dataclasses
2. Create `channels/whatsapp.py` — Twilio WhatsApp adapter
3. Create `channels/sms.py` — Twilio SMS adapter
4. Create `routers/webhooks.py` — Twilio webhook endpoints
5. Create `core/response_formatter.py` — Per-channel formatting
6. Refactor `channels/telegram.py` to implement ChannelAdapter interface
7. Add Twilio config settings to ConfigManager
8. Add channel_identities + channel_messages DB tables
9. Wire into app.py lifespan (similar to Telegram channel startup)
10. Admin UI: Twilio settings page, WhatsApp/SMS toggles

**Dependencies:** `twilio` Python package

### Phase 2: ElevenLabs TTS (1 session)

**Why second:** Needed for voice, but also useful standalone for WhatsApp voice message responses.

1. Create `voice/tts.py` — ElevenLabs wrapper (streaming HTTP + WebSocket)
2. Add ElevenLabs config settings to ConfigManager
3. Add TTS tool to plugin system (generate voice message on demand)
4. Test: WhatsApp voice message response (text→TTS→audio→WhatsApp)
5. Admin UI: ElevenLabs settings, voice selection, test button

**Dependencies:** `elevenlabs` Python package

### Phase 3: Voice Calls (2-3 sessions)

**Why third:** Most complex. Requires STT + TTS + real-time pipeline.

**Session 1: STT + Audio Utilities**
1. Create `voice/stt.py` — Deepgram streaming + Whisper.cpp fallback
2. Create `voice/vad.py` — WebRTC VAD wrapper
3. Create `voice/audio.py` — mulaw/PCM conversion utilities
4. Test: audio → transcript pipeline

**Session 2: Voice Pipeline**
1. Create `voice/pipeline.py` — VoicePipeline orchestrator
2. Create `channels/voice.py` — Twilio voice adapter
3. Add voice WebSocket endpoint to ws.py or webhooks.py
4. Implement greeting → STT → Agent → TTS → playback flow
5. Implement interruption handling (VAD + abort + clear)

**Session 3: Polish + Production**
1. Voice call records DB table + transcript saving
2. Outbound calling support (Nexus initiates calls)
3. Call duration limits + cost tracking
4. Admin UI: Voice settings, call history, transcript viewer
5. Webhook URL configuration (ngrok for dev, domain for prod)

**Dependencies:** `deepgram-sdk`, `webrtcvad`, `audioop-lts` (or built-in audioop)

### Phase 4: Unified Layer + Cross-Channel (1 session)

1. Implement conversation continuity across channels
2. Add channel context to system prompt ("User is on WhatsApp")
3. Channel-specific response length and format hints to LLM
4. Cross-channel notifications ("I sent you the file on WhatsApp")
5. Unified channel status dashboard in admin UI

### New Python Dependencies

```
# Communications
twilio>=9.0.0
elevenlabs>=1.0.0
deepgram-sdk>=3.0.0
webrtcvad>=2.0.10

# Audio processing (for Whisper.cpp fallback)
# faster-whisper>=1.0.0   # Optional: local STT fallback
# audioop-lts>=0.2.0      # If Python 3.13+ (audioop removed in 3.13)
```

### Admin UI Additions

**Settings > Communications page:**
- Twilio section: Account SID, Auth Token (encrypted), Phone Number, WhatsApp Number
- ElevenLabs section: API Key (encrypted), Voice ID (dropdown), Model selector
- STT section: Provider selector, Deepgram API Key (encrypted)
- Channel toggles: WhatsApp enabled, SMS enabled, Voice enabled
- Webhook URL (auto-detect or manual override)
- Test buttons: Send test WhatsApp, Make test call, Test TTS

**Communications Dashboard:**
- Active channels with status indicators
- Recent messages across all channels (unified view)
- Voice call history with transcripts
- Message volume chart (per channel, per day)
- Cost tracking (Twilio + ElevenLabs usage)

---

## Appendix A: Key API Endpoints Summary

| Provider | Endpoint | Purpose |
|----------|----------|---------|
| Twilio | `POST /2010-04-01/Accounts/{sid}/Messages.json` | Send SMS/WhatsApp |
| Twilio | `POST /2010-04-01/Accounts/{sid}/Calls.json` | Initiate outbound call |
| Twilio | Webhook: `POST /api/channels/voice/incoming` | Handle inbound call |
| Twilio | Webhook: `POST /api/channels/whatsapp/webhook` | Handle inbound WhatsApp |
| Twilio | Webhook: `POST /api/channels/sms/webhook` | Handle inbound SMS |
| Twilio | WebSocket: `wss://your-server/api/voice/stream` | Media Streams audio |
| ElevenLabs | `POST /v1/text-to-speech/{voice_id}/stream` | Streaming TTS (HTTP) |
| ElevenLabs | `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input` | Real-time TTS (WS) |
| Deepgram | `wss://api.deepgram.com/v1/listen` | Streaming STT |
| Deepgram | `POST /v1/listen` | Batch STT |

## Appendix B: Audio Format Quick Reference

| Context | Format | Sample Rate | Encoding | Notes |
|---------|--------|-------------|----------|-------|
| Twilio Media Streams (in) | mulaw | 8kHz | base64 | Raw telephone audio |
| Twilio Media Streams (out) | mulaw | 8kHz | base64 | Must match inbound |
| ElevenLabs TTS output | ulaw_8000 | 8kHz | raw bytes | Native format, zero conversion |
| Deepgram STT input | mulaw | 8kHz | raw bytes | Native format, zero conversion |
| Whisper STT input | PCM | 16kHz | 16-bit signed | Requires mulaw→PCM upsampling |
| WhatsApp voice message | OGG Opus | Variable | Opus codec | Need to transcode for STT |
| WhatsApp audio response | OGG Opus | Variable | Opus codec | ElevenLabs can output this |

## Appendix C: Twilio Webhook Security Checklist

1. Validate `X-Twilio-Signature` on every webhook request
2. Use HTTPS for all webhook URLs (Twilio rejects HTTP in production)
3. Return HTTP 200 within 15 seconds (or Twilio retries)
4. Implement idempotency (Twilio may retry on timeout — check message SID)
5. Rate limit webhook endpoints (prevent abuse if URL leaked)
6. Log all webhook requests for audit trail
7. Never expose auth token in client-side code or logs

## Appendix D: Important Caveats and Notes

**Knowledge cutoff:** This research is based on API documentation and pricing available through early 2025. Verify current pricing, API versions, and SDK versions before implementation:
- Twilio pricing page: twilio.com/pricing
- ElevenLabs pricing: elevenlabs.io/pricing
- Deepgram pricing: deepgram.com/pricing
- Check `pip install twilio elevenlabs deepgram-sdk` for latest SDK versions

**Twilio WhatsApp approval:** Getting a production WhatsApp sender approved takes 1-5 business days. Start the application process early. Use Twilio's sandbox for development.

**ElevenLabs quota management:** TTS characters are consumed even for failed/interrupted calls. Implement client-side tracking and budget alerts.

**Ngrok for development:** Twilio webhooks require a public URL. `ngrok http 8080` provides one for development. For production, use a proper domain with TLS.

**mulaw audio:** The `audioop` module was removed from Python 3.13+. If Nexus upgrades past 3.12, install `audioop-lts` package or use a pure-Python implementation.

**Voice latency on Ollama:** Cold Ollama inference (model loading from disk) can take 5-10 seconds — unacceptable for voice. Solutions: (a) keep model loaded with `OLLAMA_KEEP_ALIVE`, (b) use Claude API for voice channel, (c) pre-warm model with periodic dummy requests.

**WhatsApp template approval:** Template messages must be pre-approved by Meta. Plan template content early. Utility templates (order updates, etc.) approve faster than marketing templates.

**Concurrent voice calls:** Each active call requires a dedicated VoicePipeline instance with its own STT/TTS streams. On M4 Max with Ollama, limit concurrent voice calls to 1-2 (LLM is the bottleneck). Claude API can handle more concurrent calls.
