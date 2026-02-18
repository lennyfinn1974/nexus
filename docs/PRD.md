# Nexus Platform — Product Requirements Document

**Document Version:** 2.0
**Date:** 18 February 2026
**Status:** Approved for Implementation
**Owner:** Nexus Core Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Vision](#2-product-vision)
3. [Target Users](#3-target-users)
4. [Architecture Overview](#4-architecture-overview)
5. [Core Services PRD](#5-core-services-prd)
   - 5.1 [Workflow and Multi-Agent Orchestration](#51-workflow-and-multi-agent-orchestration-stream-1)
   - 5.2 [Communications Platform](#52-communications-platform-stream-2)
   - 5.3 [Marketing Agency](#53-marketing-agency-stream-3)
6. [Vertical Framework PRD](#6-vertical-framework-prd)
7. [Vertical: Gym/Fitness](#7-vertical-gymfitness)
8. [Vertical: Cafe/Restaurant](#8-vertical-caferestaurant)
9. [Database Schema](#9-database-schema)
10. [API Endpoints](#10-api-endpoints)
11. [Licensing and Monetization](#11-licensing-and-monetization)
12. [Dependencies and Costs](#12-dependencies-and-costs)
13. [Implementation Roadmap](#13-implementation-roadmap)
14. [Success Metrics](#14-success-metrics)
15. [Risks and Mitigations](#15-risks-and-mitigations)
16. [Non-Functional Requirements](#16-non-functional-requirements)

---

## 1. Executive Summary

Nexus is an AI-native business operations platform where a single intelligent agent serves as the central point of contact for every business function: customer communications, marketing, workflow orchestration, and industry-specific operations. Unlike traditional SaaS products that bolt AI onto existing software, Nexus inverts the model entirely. The AI agent IS the product. It manages supplier orders, answers customer calls, runs marketing campaigns, orchestrates development workflows, and operates domain-specific business logic, all through one personality with one unified memory.

The platform targets small-to-medium businesses (SMBs) across multiple verticals: cafes and restaurants, gyms and fitness studios, healthcare clinics, legal practices, and accounting firms. A single Nexus subscription replaces five to ten separate SaaS tools (social media schedulers, email marketing platforms, POS integrations, review management tools, CRM systems) by consolidating all capabilities behind one conversational AI agent accessible via web chat, WhatsApp, SMS, voice calls, and dedicated dashboard panels.

The platform consists of two layers:

- **Core Services** (industry-agnostic): Chat UI, Admin UI, Workflow Orchestration, Communications Platform, Marketing Agency
- **Industry Verticals** (domain-specific modules): Cafe/Restaurant, Gym/Fitness, Healthcare, Legal, Accounting, with a plugin architecture enabling rapid addition of new verticals

The existing Nexus codebase provides: a FastAPI backend with async PostgreSQL, three-tier model routing (Ollama local, Claude API cloud, Claude Code CLI agentic), a plugin system with 59 tools, sub-agent orchestration, a React chat UI, a React admin UI, a knowledge graph with RAG retrieval, passive memory learning, a work registry with KanBan board, and headless browser rendering. This PRD specifies the features required to transform this foundation into a complete commercial platform.

**Estimated total implementation effort:** 32-42 Claude Code sessions across three parallel feature streams plus a vertical framework and two reference vertical implementations.

---

## 2. Product Vision

### 2.1 Core Philosophy: AI-Native, Not AI-Bolted-On

Traditional platforms add AI as a feature layer on top of existing software: "We added a chatbot to our POS system." Nexus inverts this model. The AI agent does not integrate into an existing system; it builds and operates the entire business platform from the ground up.

Every feature, workflow, and customer interaction starts with the agent. The user interface panels (`/marketing`, `/workflow`, `/cafe`, `/gym`) are visual dashboards into what the agent already knows and does, not the other way around. Business owners do not configure a platform and then add an AI assistant. They deploy an AI agent and it creates the operational platform around itself.

### 2.2 One Agent, One Memory, All Channels, All Tools

The Nexus agent maintains a single personality, a single knowledge graph, and a single memory system across every interaction channel. A conversation started on WhatsApp continues seamlessly on voice or web. If the agent learns a customer's preferences on a phone call, it remembers them in WhatsApp. If marketing performance data is ingested via the ads API, a business owner can ask about it from any channel and receive a coherent answer.

### 2.3 The Agent as Employee

For SMB owners, Nexus is not a software tool; it is a virtual employee. The agent proactively manages operations: it notices inventory running low and drafts supplier orders, it detects declining member attendance and triggers retention outreach, it spots a trending local event and suggests a flash promotion, it monitors review platforms and drafts brand-voice responses. It handles routine tasks automatically (with configurable approval gates) and escalates decisions that require human judgment.

### 2.4 Cross-Domain Intelligence

Because the agent has visibility into marketing, communications, operations, and customer data simultaneously, it can draw connections that siloed tools never could. "Your Instagram post about oat milk drove 12 orders today" is a statement that requires linking social media analytics to POS transaction data. No combination of separate SaaS tools produces this insight without manual correlation. Nexus does it natively because the same agent touches both systems.

---

## 3. Target Users

### 3.1 Primary Personas

| Persona | Role | Interaction Mode | Primary Needs |
|---------|------|-----------------|---------------|
| **Business Owner/Operator** | Decision-maker, daily operations | WhatsApp, Voice, Chat UI, Dashboard panels | Operational summaries, approval workflows, strategic insights, cost control |
| **Marketing Manager** | Campaign management, content creation | Marketing UI, Chat UI | Campaign planning, content calendars, analytics, social media management, ad optimization |
| **Front Desk / Staff** | Day-to-day execution | WhatsApp, SMS, Vertical UI | Order management, appointment booking, member check-ins, inventory alerts |
| **Developer / Technical Admin** | System configuration, workflow automation | Chat UI, Admin UI, Workflow UI, CLI | Model configuration, plugin management, terminal orchestration, API access |
| **End Customer** | Customer of the business using Nexus | WhatsApp, Voice, SMS, Web chat | Place orders, book appointments, ask questions, provide feedback |

### 3.2 Target Verticals

| Vertical | Example Business | Key Pain Points Addressed |
|----------|-----------------|--------------------------|
| **Cafe/Restaurant** | Specialty coffee shop, bakery, bistro | Supplier ordering complexity, review management, social media consistency, customer ordering |
| **Gym/Fitness** | CrossFit box, boutique studio, PT studio | Member retention, lead conversion, automated messaging sequences, class scheduling |
| **Healthcare** | GP clinic, physiotherapy practice, dental office | Appointment booking, patient intake, treatment plan tracking, HIPAA-aware records |
| **Legal** | Small law firm, sole practitioner, barrister | Matter management, time tracking, court date management, document assembly |
| **Accounting** | Tax advisory firm, bookkeeping practice | Client management, tax deadline tracking, document collection, lodgement workflows |

### 3.3 Market Sizing

The primary addressable market is SMBs with 1-50 employees across the target verticals in English-speaking markets (Australia, UK, US, Canada, New Zealand). These businesses typically spend $200-800/month across 5-10 separate SaaS subscriptions. Nexus consolidates this into a single $49-149/month subscription.

---

## 4. Architecture Overview

### 4.1 Platform Layers

```
+------------------------------------------------------------------+
|                        THE NEXUS AGENT                            |
|   One AI   One Memory   All Tools   All Channels   All Context   |
+-------------------------------+----------------------------------+
                                |
             +------------------+------------------+
             v                  v                  v
      +-----------+      +-----------+      +-----------+
      | CORE      |      | CORE      |      | CORE      |
      | Marketing |      | Comms     |      | Workflow   |
      | (all biz) |      | (all biz) |      | (all biz) |
      +-----+-----+      +-----+-----+      +-----+-----+
            |                   |                   |
      +-----+-------------------+-------------------+-----+
      |                VERTICAL MODULES                    |
      |  +------+ +-----+ +----------+ +-------+ +------+ |
      |  | Cafe | | Gym | |Healthcare| | Legal | | Acct | |
      |  +------+ +-----+ +----------+ +-------+ +------+ |
      +----------------------------------------------------+
```

### 4.2 Core Service Routes

| Core Service | Route | Purpose | Status |
|-------------|-------|---------|--------|
| Chat UI | `/` | Conversational interface | Existing |
| Admin UI | `/admin` | System config, models, API keys, licensing | Existing |
| Workflow | `/workflow` | Terminal orchestration, BLD:APP, agent task management | New |
| Marketing | `/marketing` | Campaign management, social, email, ads, SEO | New |
| Comms | `/comms` | Voice calls, WhatsApp, SMS, channel management | New |

### 4.3 Vertical Module Routes

| Vertical | Route | Status |
|----------|-------|--------|
| Cafe/Restaurant | `/cafe` | New (reference implementation) |
| Gym/Fitness | `/gym` | New (reference implementation) |
| Healthcare | `/healthcare` | Future |
| Legal | `/legal` | Future |
| Accounting | `/accounting` | Future |

### 4.4 Existing Infrastructure

The following components are already implemented and form the foundation for all new features:

- **Backend**: FastAPI with async SQLAlchemy on PostgreSQL (port 8080)
- **Model Routing**: Three-tier local-first — Ollama (kimi-k2.5) primary, Claude API fallback, Claude Code CLI tertiary
- **Agent Pipeline**: `AgentRunner` orchestrator, `AgentAttempt` LLM+tool loop, stream buffering, abort support
- **Plugin System**: 8 plugins (mem0, qmd, macos, brave, terminal, sovereign, github, catalog), 59 tools, rate limiting, file access control, audit trail
- **Sub-Agent Orchestration**: `SubAgentOrchestrator` with 5 roles (Builder/Reviewer/Researcher/Verifier/Synthesizer), topological dependency layers, parallel execution
- **Memory**: PostgreSQL-backed `PersonalMemorySystem`, knowledge graph, RAG retrieval (25ms p50), passive context learning
- **Work Registry**: Unified tracking for agents, sub-agents, plans, tasks, reminders with SSE streaming and KanBan board
- **Frontend**: React 19 chat-ui (Vite 7 + Radix UI + Tailwind 4), React admin-ui
- **Communications**: Telegram adapter with pairing, WebSocket streaming
- **Web Understanding**: HTML extraction (BS4 + html2text), headless Chromium (Playwright), auto-fallback chain

### 4.5 Data Flow: Single AgentRunner Pipeline

Every channel adapter normalizes incoming messages to a `ChannelMessage` dataclass and routes through `AgentRunner.run()`. The agent sees all tools (marketing, terminal, comms, social, vertical-specific) regardless of channel origin. A WhatsApp customer can ask "what's the status of my campaign?" and receive an answer because the agent has access to `ads_performance` and `social_analytics` tools. The system prompt includes channel context so the agent adapts its response format (concise for SMS, conversational for voice, rich Markdown for web, interactive buttons for WhatsApp) while making the same decisions.

---

## 5. Core Services PRD

### 5.1 Workflow and Multi-Agent Orchestration (Stream 1)

#### 5.1.1 Overview

A conductor-driven multi-agent development system with full observability. The `OrchestratorConductor` manages a state machine that plans, researches, builds, reviews, fixes, and tests code changes by dispatching specialized sub-agents to persistent terminal sessions, coordinating Git branches, and publishing all events through a typed event bus.

#### 5.1.2 Feature: Persistent Terminal Sessions

**Description:** Replace the current osascript-based terminal control with proper PTY-based persistent shell sessions. Each agent gets a named session with its own working directory, environment variables, and command history. Sessions survive across tool calls and provide non-blocking I/O via asyncio.

**New File:** `backend/core/terminal_session.py` (~300 LOC)

**Acceptance Criteria:**
- Given a request to create a terminal session, when `PersistentShell.create(name)` is called, then a new PTY is allocated via `pty.openpty()` with an asyncio event-loop reader attached
- Given a running session, when a command is executed, then output is captured with ANSI codes stripped for agent context and raw codes preserved for UI rendering
- Given a session with prior commands, when the working directory is queried, then the current directory is accurately reported
- Given a session, when `destroy()` is called, then the PTY is closed and all asyncio readers are removed
- Given an active session, when `libtmux` integration is used, then the session is visible in a tmux layout alongside programmatic control

**Priority:** P0
**Dependencies:** None (standalone module)
**Estimated Effort:** 1 session

#### 5.1.3 Feature: Typed Event Bus

**Description:** An asyncio.Queue-based event bus that transports typed event dataclasses between system components. All terminal commands, agent decisions, Git events, and phase changes are published as events. Subscribers (WorkRegistry, WebSocket broadcaster, log writer, metrics collector) consume events independently.

**New File:** `backend/core/event_bus.py` (~200 LOC)

**Event Types (dataclasses):**
- `TerminalCommand` — command text, session name, timestamp
- `TerminalOutput` — output text, session name, exit code, duration_ms
- `AgentDecision` — agent role, decision description, reasoning, confidence
- `GitEvent` — event type (branch, commit, merge, conflict), branch name, details
- `PhaseChange` — from_phase, to_phase, reason, conductor_id

**Acceptance Criteria:**
- Given a new event bus, when a subscriber is registered for `TerminalCommand`, then it receives only `TerminalCommand` events (not other types)
- Given multiple subscribers, when an event is published, then all matching subscribers receive the event within 100ms
- Given the WorkRegistry subscriber, when events are received, then they are persisted to the `work_items` table for audit trail
- Given the WebSocket subscriber, when events are received, then they are broadcast to connected Chat UI clients
- Given the event bus, when `shutdown()` is called, then all pending events are drained and subscribers are notified

**Priority:** P0
**Dependencies:** None (standalone module)
**Estimated Effort:** 1 session

#### 5.1.4 Feature: OrchestratorConductor State Machine

**Description:** A state machine that manages the full lifecycle of a multi-agent development task. The conductor progresses through phases (PLANNING, RESEARCHING, BUILDING, REVIEWING, FIXING, TESTING, COMPLETE) with reactive transitions. If the reviewer scores a build below threshold, the conductor re-enters the BUILDING phase with reviewer feedback. A maximum of 3 build-review cycles is enforced before escalating to the user.

**New File:** `backend/core/conductor.py` (~500 LOC)

**State Machine:**
```
PLANNING --> RESEARCHING --> BUILDING --> REVIEWING --+--> TESTING --> COMPLETE
                                ^                    |
                                |     (score < 7)    |
                                +----  FIXING  <-----+
                                       (max 3 cycles)
```

**Acceptance Criteria:**
- Given a user request "build feature X", when the conductor starts, then it enters PLANNING phase and dispatches a planning agent to break the request into tasks
- Given a PLANNING phase completion, when tasks are defined, then the conductor transitions to RESEARCHING and dispatches research agents for each task
- Given a BUILDING phase, when the builder agent completes, then the conductor transitions to REVIEWING and dispatches a reviewer agent with the diff
- Given a reviewer score below 7 out of 10, when the review completes, then the conductor transitions to FIXING and re-enters BUILDING with the reviewer's feedback attached
- Given 3 failed build-review cycles, when the third review still scores below 7, then the conductor escalates to the user via WebSocket/WhatsApp with a summary of issues
- Given a reviewer score of 7 or above, when the review completes, then the conductor transitions to TESTING and runs the test suite
- Given all tests pass, when the test phase completes, then the conductor transitions to COMPLETE and publishes a final summary
- Given any phase transition, when it occurs, then a `PhaseChange` event is published to the event bus
- Given a Git branch strategy, when a builder agent starts, then it works on `feature/builder-{task_id}` branch; when a reviewer approves, then changes are merged to the main working branch

**Priority:** P0
**Dependencies:** Persistent Terminal Sessions (5.1.2), Event Bus (5.1.3), existing `SubAgentOrchestrator`
**Estimated Effort:** 2 sessions

**Modified Files:**
- `backend/core/sub_agent.py` — Add conductor loop, reactive phases, retry on review failure
- `backend/plugins/sovereign_plugin.py` — BLD:APP delegates to conductor instead of raw tmux
- `backend/plugins/terminal_plugin.py` — Add persistent session management via `PersistentShell`
- `backend/core/work_registry.py` — New event types for terminal, agent decisions, phase changes
- `backend/app.py` — Initialize event bus, conductor; serve workflow-ui static files

#### 5.1.5 Feature: Git Coordinator

**Description:** Manages branch-per-agent strategy for multi-agent development. Each builder agent works on its own feature branch. Merge is triggered by reviewer approval. Conflict resolution is escalated to the conductor.

**New File:** `backend/core/git_coordinator.py` (~200 LOC)

**Acceptance Criteria:**
- Given a new builder task, when the builder agent starts, then a branch `feature/builder-{task_id}` is created from the current working branch
- Given a reviewer approval, when the review completes with score >= 7, then the builder's branch is merged into the working branch
- Given a merge conflict, when the merge fails, then the conductor is notified and the conflict details are included in the next FIXING phase prompt
- Given multiple concurrent builders, when branches are created, then each operates independently without cross-contamination

**Priority:** P1
**Dependencies:** OrchestratorConductor (5.1.4)
**Estimated Effort:** Included in conductor sessions

#### 5.1.6 Feature: Workflow UI Panel

**Description:** A React application served at `/workflow` providing full observability into multi-agent orchestration. Includes live terminal viewers per agent (xterm.js), orchestration timeline with phase transitions, agent status cards, Git diff viewer, and one-click approve/reject/retry controls.

**New Directory:** `workflow-ui/` (~2000 LOC)

**Pages:**
- **Orchestration Dashboard** — Active conductor sessions, phase timeline, agent status cards with token usage and duration
- **Terminal Viewer** — Live terminal output per agent session via xterm.js, with scrollback and search
- **Git Diff Viewer** — Side-by-side diff for reviewing agent changes before merge
- **Controls** — Approve, reject, retry buttons for human-in-the-loop intervention

**Acceptance Criteria:**
- Given an active conductor session, when the Workflow UI is opened, then the current phase is highlighted in the timeline and all active agent cards show real-time status
- Given a terminal session, when commands are executed, then output appears in the xterm.js viewer within 200ms
- Given a review phase, when the reviewer completes, then the Git diff is displayed and approve/reject buttons are enabled
- Given the user clicks "Approve", when the action is confirmed, then the conductor proceeds to the TESTING phase
- Given the user clicks "Reject", when feedback is provided, then the conductor re-enters BUILDING with the user's feedback
- Given no active sessions, when the Workflow UI is opened, then a history of past orchestration runs is displayed with outcomes and durations

**Priority:** P1
**Dependencies:** OrchestratorConductor (5.1.4), Event Bus (5.1.3)
**Estimated Effort:** 1-2 sessions

#### 5.1.7 Feature: BLD:APP v2 Integration

**Description:** Upgrade the existing BLD:APP sovereign procedure to use the new OrchestratorConductor instead of raw tmux session management. The `/workflow` slash command opens the Workflow UI. Metrics are collected for orchestration duration, agents per run, review cycles, and success rate.

**Acceptance Criteria:**
- Given a BLD:APP command, when executed, then the conductor is initialized and the orchestration begins through the state machine (not raw tmux)
- Given an active conductor, when `/workflow` is typed in chat, then the Workflow UI opens in a new browser tab
- Given a completed orchestration, when metrics are collected, then `orchestration.duration`, `agents_per_run`, `review_cycles`, and `success_rate` are recorded
- Given the Chat UI, when a conductor is active, then the orchestration panel shows the current conductor state and phase

**Priority:** P1
**Dependencies:** OrchestratorConductor (5.1.4), Workflow UI (5.1.6)
**Estimated Effort:** 1 session

---

### 5.2 Communications Platform (Stream 2)

#### 5.2.1 Overview

A unified multi-channel communications system enabling the Nexus agent to interact with users via WhatsApp, SMS, and voice calls in addition to the existing WebSocket chat and Telegram channels. All channels normalize to a common message format and route through the single AgentRunner pipeline. Voice calls use Deepgram for speech-to-text and ElevenLabs for text-to-speech with real-time streaming through Twilio Media Streams.

**Core Design Decision:** Twilio serves as the single provider for WhatsApp, SMS, and Voice. One SDK (`twilio`), one billing account, one webhook format. This reduces integration complexity and operational overhead compared to using separate providers for each channel.

#### 5.2.2 Feature: Channel Adapter Framework

**Description:** An abstract base class (`ChannelAdapter`) and normalized message dataclass (`ChannelMessage`) that all communication channels implement. This framework decouples channel-specific logic from the core agent pipeline. A `ResponseFormatter` shapes agent output per channel (concise for SMS, interactive buttons for WhatsApp, rich Markdown for web, conversational for voice).

**New Files:**
- `backend/channels/base.py` (~200 LOC) — `ChannelAdapter` ABC, `ChannelMessage` dataclass, `MediaAttachment` dataclass, `ResponseFormatter`
- `backend/channels/telegram_adapter.py` (~250 LOC) — Refactor existing `TelegramChannel` to implement `ChannelAdapter`
- `backend/core/response_formatter.py` (~200 LOC) — Per-channel output formatting

**ChannelMessage Dataclass:**
```
ChannelMessage:
    channel: str              # 'telegram', 'whatsapp', 'sms', 'voice', 'websocket'
    user_id: str              # Channel-specific user identifier
    nexus_user_id: UUID       # Resolved cross-channel identity (nullable)
    text: str                 # Message text content
    media: list[MediaAttachment]  # Images, documents, audio files
    metadata: dict            # Channel-specific extras (e.g., WhatsApp button responses)
    timestamp: datetime
    reply_callback: Callable  # Async function to send response back to channel
```

**Acceptance Criteria:**
- Given any channel adapter, when a message is received, then it is normalized to a `ChannelMessage` and routed through `AgentRunner.run()` identically to WebSocket messages
- Given the existing Telegram channel, when it is refactored to `ChannelAdapter`, then all existing functionality (pairing, commands, message routing) continues to work without regression
- Given a `ResponseFormatter`, when an agent response is generated for SMS, then it is truncated to 160 characters at sentence boundaries with a "..." continuation indicator
- Given a `ResponseFormatter`, when an agent response is generated for WhatsApp, then interactive buttons are used for choices and text is kept concise
- Given a `ResponseFormatter`, when an agent response is generated for voice, then SSML tags are added for natural speech cadence
- Given a new channel, when the system prompt is constructed, then it includes channel context: "User is contacting via {channel}. Adapt your response format accordingly."
- Given the `channel_identities` table, when a phone number is received, then it is resolved to an existing `nexus_user_id` if a prior mapping exists

**Priority:** P0
**Dependencies:** None (standalone framework)
**Estimated Effort:** 1 session

#### 5.2.3 Feature: WhatsApp and SMS via Twilio

**Description:** Twilio webhook endpoints for receiving WhatsApp and SMS messages. The WhatsApp adapter handles text messages, media (images, documents, audio), interactive buttons, and voice message transcription. The SMS adapter handles text-only messages with aggressive brevity mode. Both adapters validate Twilio webhook signatures for security.

**New Files:**
- `backend/channels/whatsapp.py` (~300 LOC) — Twilio WhatsApp adapter
- `backend/channels/sms.py` (~150 LOC) — Twilio SMS adapter
- `backend/routers/channels.py` (~300 LOC) — Webhook endpoints

**Acceptance Criteria:**
- Given a Twilio webhook POST to `/api/channels/twilio/webhook`, when the request is received, then the Twilio signature is validated using `twilio.request_validator` before processing
- Given an invalid Twilio signature, when the webhook is received, then a 403 Forbidden response is returned
- Given a WhatsApp text message, when processed, then a `ChannelMessage` is created with `channel='whatsapp'` and routed to AgentRunner
- Given a WhatsApp media message (image, document), when processed, then the media URL is downloaded and included as a `MediaAttachment`
- Given a WhatsApp voice message, when processed, then the audio is transcribed via Deepgram before routing to the agent
- Given an SMS message, when processed, then a `ChannelMessage` is created with `channel='sms'` and the response is formatted for 160-character limit
- Given the Admin UI, when Twilio configuration is accessed, then fields for Account SID, Auth Token, and Phone Number are available and encrypted in the database
- Given a WhatsApp message outside the 24-hour session window, when the agent needs to respond, then a pre-approved template message is used
- Given the agent needs to send a WhatsApp response with choices, when formatting, then interactive buttons (up to 3) or list messages (up to 10 items) are used

**Priority:** P0
**Dependencies:** Channel Adapter Framework (5.2.2)
**Estimated Effort:** 1-2 sessions

#### 5.2.4 Feature: ElevenLabs Text-to-Speech

**Description:** A TTS wrapper supporting both HTTP streaming (for pre-recorded audio like WhatsApp voice replies) and WebSocket streaming (for real-time voice calls). Voice selection and cloning configuration managed through Admin UI. A new `tts_speak` tool allows any channel to trigger TTS output.

**New File:** `backend/voice/tts.py` (~300 LOC)

**Acceptance Criteria:**
- Given a text string, when `tts.speak(text, voice_id)` is called with HTTP mode, then an audio buffer is returned in PCM 16-bit format suitable for Twilio playback
- Given a text string, when `tts.speak_stream(text, voice_id)` is called with WebSocket mode, then audio chunks are yielded as they are generated for real-time playback
- Given sentence-boundary streaming, when the agent produces a multi-sentence response, then TTS begins streaming audio for the first sentence while the agent is still generating subsequent sentences
- Given the `tts_speak` tool, when invoked from any channel, then the agent generates audio and sends it as a media attachment (e.g., WhatsApp audio message)
- Given the Admin UI, when ElevenLabs configuration is accessed, then fields for API key, voice ID, and model selection (`eleven_turbo_v2_5` for real-time, `eleven_multilingual_v2` for quality) are available
- Given a voice call context, when TTS is invoked, then the `eleven_turbo_v2_5` model is used for lowest latency
- Given a WhatsApp audio response context, when TTS is invoked, then the `eleven_multilingual_v2` model is used for highest quality

**Priority:** P1
**Dependencies:** Channel Adapter Framework (5.2.2)
**Estimated Effort:** 1 session

#### 5.2.5 Feature: Voice Calls (Deepgram STT + VoicePipeline)

**Description:** Full voice call capability via Twilio Media Streams. Inbound calls are answered by the Nexus agent using Deepgram for real-time speech-to-text and ElevenLabs for text-to-speech. The VoicePipeline manages the STT-to-Agent-to-TTS flow with interruption handling: when the user starts speaking mid-response, the agent's audio output is immediately halted and a new STT session begins.

**New Files:**
- `backend/voice/stt.py` (~250 LOC) — Deepgram streaming STT with mulaw 8kHz native input
- `backend/voice/vad.py` (~100 LOC) — WebRTC VAD wrapper for speech activity detection
- `backend/voice/pipeline.py` (~400 LOC) — VoicePipeline orchestrator
- `backend/channels/voice.py` (~400 LOC) — Twilio voice adapter (TwiML generation, Media Streams WebSocket)

**Voice Pipeline Flow:**
```
Caller --> Twilio Media Streams --> WebSocket --> VAD --> Deepgram STT
                                                              |
                                                         AgentRunner
                                                              |
                                                    ElevenLabs TTS (streaming)
                                                              |
                                                 WebSocket --> Twilio --> Caller
```

**Acceptance Criteria:**
- Given an inbound call to the Twilio number, when the call is answered, then TwiML is returned that connects to the Nexus Media Streams WebSocket at `/api/voice/stream`
- Given audio from the caller, when received via Media Streams, then the mulaw 8kHz audio is streamed directly to Deepgram STT (no audio format conversion needed)
- Given Deepgram STT output, when a final transcript is produced, then it is routed to `AgentRunner.run()` as a `ChannelMessage` with `channel='voice'`
- Given the agent's text response, when TTS is invoked, then ElevenLabs audio is streamed back through the Twilio Media Streams WebSocket as base64-encoded mulaw chunks
- Given the caller starts speaking while TTS is playing, when VAD detects speech activity, then the TTS audio buffer is cleared, the current agent response is aborted, and a new STT session begins for the interruption
- Given a voice call context, when the model router selects a model, then Claude API is preferred by default (300ms TTFT vs 5-10s Ollama cold start) to maintain conversational latency
- Given the Comms UI at `/comms`, when a voice call is active, then a live call dashboard shows call duration, transcript, and agent responses in real-time
- Given a completed call, when the call ends, then a `voice_calls` record is created with call SID, duration, STT/TTS costs, and the full transcript is stored

**Priority:** P1
**Dependencies:** Channel Adapter Framework (5.2.2), ElevenLabs TTS (5.2.4)
**Estimated Effort:** 2-3 sessions

#### 5.2.6 Feature: Cross-Channel Unification

**Description:** Conversation continuity across channels. When the same user communicates via WhatsApp, Telegram, web chat, and voice, the Nexus agent maintains a single conversation thread. A unified message log in Admin UI shows all channel interactions. Per-channel cost tracking and analytics are provided. Passive memory learns channel preferences (e.g., "user prefers WhatsApp for quick questions, email for detailed reports").

**Acceptance Criteria:**
- Given a user who has paired on Telegram and also messaged via WhatsApp, when the `channel_identities` table is queried, then both channels resolve to the same `nexus_user_id`
- Given a conversation started on WhatsApp, when the same user continues on web chat, then the agent has full context of the prior WhatsApp messages
- Given the Admin UI unified message log, when a user is selected, then all messages across all channels are displayed in chronological order with channel indicators
- Given the passive memory system, when a user consistently uses WhatsApp for quick questions, then the agent stores this as a preference and adapts notification channel accordingly
- Given per-channel analytics, when the comms dashboard is viewed, then cost per channel (Twilio SMS, WhatsApp, voice minutes, TTS characters) is displayed for the current billing period

**Priority:** P2
**Dependencies:** WhatsApp/SMS (5.2.3), Voice Calls (5.2.5)
**Estimated Effort:** 1 session

#### 5.2.7 Feature: Comms UI Panel

**Description:** A React application served at `/comms` for managing communication channels and monitoring voice calls.

**New Directory:** `comms-ui/` (~1500 LOC)

**Pages:**
- **Channel Dashboard** — Active channels, message volumes, cost per channel
- **Live Calls** — Active voice calls with real-time transcript, duration, controls (mute, transfer, end)
- **Call History** — Past calls with transcripts, duration, cost, agent performance
- **Channel Config** — Twilio, ElevenLabs, Deepgram configuration (links to Admin UI settings)
- **User Directory** — Cross-channel user identities with channel preferences

**Priority:** P1
**Dependencies:** Voice Calls (5.2.5)
**Estimated Effort:** Included in Voice Calls sessions

---

### 5.3 Marketing Agency (Stream 3)

#### 5.3.1 Overview

A full-service AI marketing agency capability: strategy, content creation, distribution, and analytics. The Nexus agent does not merely have marketing tools; it proactively manages campaigns, responds to social media engagement with the brand voice, drafts email sequences, monitors ad performance, and surfaces recommendations. The Marketing UI is a visual dashboard into the agent's marketing activity.

**Core Design Decisions:**
1. **Ayrshare** ($99/mo) for social media — one API for Twitter/X, LinkedIn, Instagram, Facebook, TikTok, Pinterest; handles OAuth internally
2. **Mailchimp** (free to $20/mo) for email marketing — full campaign API, automations, A/B testing
3. **Google Ads + Meta Marketing APIs** for advertising — direct integration (too critical for middleware)
4. **Built-in SEO content optimizer** — analyze top-10 SERPs via existing `web_fetch` + LLM scoring
5. **Content approval workflow** — AI generates, human approves; never auto-publish without explicit permission
6. **Brand voice profiles** — stored in PostgreSQL, enforced on all content generation

#### 5.3.2 Feature: Core Marketing Framework

**Description:** The foundation for all marketing capabilities: brand voice profiles, content workflow state machine, campaign model, and marketing REST API. Brand voice profiles define tone, vocabulary rules, platform-specific guidelines, and example content. The content workflow state machine manages content from draft through review, approval, scheduling, to publication.

**New Files:**
- `backend/core/marketing/brand.py` (~200 LOC) — Brand voice profiles, tone enforcement, vocabulary rules
- `backend/core/marketing/content.py` (~300 LOC) — Content workflow state machine
- `backend/core/marketing/campaign.py` (~300 LOC) — Campaign planner, budget allocation, calendar management
- `backend/core/marketing/attribution.py` (~250 LOC) — Multi-touch attribution (5 models), UTM builder
- `backend/routers/marketing.py` (~300 LOC) — Marketing REST API endpoints

**Content Workflow State Machine:**
```
DRAFT --> REVIEW --> APPROVED --> SCHEDULED --> PUBLISHED
  ^         |                                     |
  |    (rejected)                             (failed)
  +-------- +                                     |
                                                  v
                                               FAILED
```

**Acceptance Criteria:**
- Given a brand profile, when content is generated by the LLM, then the brand voice profile (tone, vocabulary, examples) is injected into the system prompt
- Given a content item in DRAFT state, when the agent or user moves it to REVIEW, then it appears in the approval queue on the Marketing UI
- Given a content item in REVIEW state, when it is approved, then it transitions to APPROVED and can be scheduled
- Given a content item in APPROVED state, when a publish time is set, then it transitions to SCHEDULED and a calendar event is created
- Given a scheduled content item, when the publish time arrives, then the appropriate platform plugin is invoked to publish and the item transitions to PUBLISHED
- Given a published content item, when the platform returns an external ID (post ID), then it is stored for engagement tracking
- Given the attribution module, when a UTM link is generated, then it includes campaign, source, medium, and content parameters
- Given the marketing REST API, when `/api/marketing/campaigns` is called, then campaign CRUD operations are available with proper authentication

**Priority:** P0
**Dependencies:** None (standalone marketing framework)
**Estimated Effort:** 1-2 sessions

#### 5.3.3 Feature: Social Media Plugin

**Description:** Ayrshare integration for multi-platform social media management. Post, schedule, monitor engagement, and reply across Twitter/X, LinkedIn, Instagram, Facebook, TikTok, and Pinterest through a single API. A direct Twitter/X adapter via `tweepy` is available for advanced features not covered by Ayrshare.

**New File:** `backend/plugins/social_media_plugin.py` (~400 LOC)

**Tools:**
- `social_post` — Publish content to one or more platforms immediately
- `social_schedule` — Schedule content for future publication
- `social_analytics` — Retrieve engagement metrics per post/platform/date range
- `social_monitor` — Check for new mentions, comments, and DMs
- `social_reply` — Post a reply to a comment or DM with brand voice
- `social_trending` — Analyze trending topics relevant to the business

**Acceptance Criteria:**
- Given content approved for Instagram, when `social_post` is invoked, then the content is published via Ayrshare with platform-appropriate formatting (image size, caption length, hashtags)
- Given a scheduled post, when `social_schedule` is invoked with a datetime, then Ayrshare's scheduling API is used and the content item transitions to SCHEDULED
- Given a published post, when `social_analytics` is invoked, then impressions, reach, engagement rate, likes, comments, and shares are returned per platform
- Given a new comment on a social post, when `social_monitor` detects it, then the agent drafts a brand-voice response and queues it for human approval (never auto-publishes replies without explicit permission)
- Given platform connection management, when the Admin UI is accessed, then Ayrshare API key and connected platform accounts are configurable
- Given content for multiple platforms, when `social_post` is invoked with `platforms=['instagram', 'facebook', 'linkedin']`, then platform-specific formatting is applied (character limits, image requirements, hashtag strategy) before publishing to each

**Priority:** P0
**Dependencies:** Core Marketing Framework (5.3.2)
**Estimated Effort:** 2 sessions

#### 5.3.4 Feature: Email Marketing Plugin

**Description:** Mailchimp integration for full email marketing: campaign creation, list management, template generation, automations, analytics, and A/B testing. A secondary SendGrid adapter handles transactional email (order confirmations, password resets, appointment reminders).

**New File:** `backend/plugins/email_marketing_plugin.py` (~350 LOC)

**Tools:**
- `email_create_campaign` — Create a new email campaign with audience, subject, and content
- `email_set_content` — Set or update email content with brand-voice HTML/text
- `email_schedule` — Schedule campaign delivery
- `email_analytics` — Open rate, click rate, bounce rate, unsubscribe rate per campaign
- `email_list_manage` — Create, update, and segment email lists
- `email_ab_test` — Set up A/B test with variants and winner criteria

**Acceptance Criteria:**
- Given a campaign brief, when `email_create_campaign` is invoked, then a Mailchimp campaign is created with the specified audience segment and content
- Given a brand profile, when email content is generated, then the brand voice is applied to subject line, preheader, and body content
- Given an A/B test setup, when `email_ab_test` is invoked, then two variants are created with different subject lines or content and a winning metric (open rate or click rate) is configured
- Given a sent campaign, when `email_analytics` is invoked, then detailed metrics including open rate, click-through rate, bounce rate, and revenue attribution are returned from Mailchimp
- Given a transactional email need, when SendGrid is configured, then order confirmations and appointment reminders are sent through SendGrid (not Mailchimp) to maintain domain reputation

**Priority:** P1
**Dependencies:** Core Marketing Framework (5.3.2)
**Estimated Effort:** 1-2 sessions

#### 5.3.5 Feature: SEO Plugin and Content Optimizer

**Description:** A built-in SEO content optimization system that analyzes top-10 SERP results for target keywords, extracts content patterns, and scores user content against competitors using LLM analysis. Integrates with Google Search Console for rank tracking and site audit data. Optional Ahrefs/SEMrush integration for advanced keyword research.

**New File:** `backend/plugins/seo_plugin.py` (~400 LOC)
**New File:** `backend/core/marketing/seo_engine.py` (~400 LOC)

**Tools:**
- `seo_keyword_research` — Analyze keyword difficulty, search volume, related terms
- `seo_site_audit` — Check indexing status, crawl errors, Core Web Vitals via Search Console
- `seo_content_optimize` — Score content against top-10 SERP competitors for a keyword
- `seo_rank_check` — Current rankings for tracked keywords
- `seo_serp_analysis` — Fetch and analyze top-10 results for a query (uses existing `web_fetch`)

**Acceptance Criteria:**
- Given a target keyword, when `seo_serp_analysis` is invoked, then the top 10 search results are fetched via `web_fetch`, content is extracted, and common patterns (headings, word count, topic clusters, FAQ sections) are analyzed
- Given a draft blog post and target keyword, when `seo_content_optimize` is invoked, then the content is scored on keyword density, heading structure, content depth, readability, and alignment with SERP patterns, with specific improvement suggestions
- Given Google Search Console credentials, when `seo_rank_check` is invoked, then current rankings for tracked keywords are returned with position changes over time
- Given the SEO engine, when keyword clustering is performed, then semantically related keywords are grouped into topic clusters for content planning

**Priority:** P1
**Dependencies:** Core Marketing Framework (5.3.2), existing `web_fetch` infrastructure
**Estimated Effort:** 1-2 sessions

#### 5.3.6 Feature: Advertising Plugin

**Description:** Direct integrations with Google Ads and Meta Marketing APIs for campaign management, audience targeting, bid optimization, and performance reporting. Budget guardrails prevent overspending: maximum daily spend limits and approval requirements for budget increases.

**New File:** `backend/plugins/ads_plugin.py` (~500 LOC)

**Tools:**
- `ads_create_campaign` — Create a new ad campaign on Google Ads or Meta
- `ads_manage_budget` — View, adjust, or cap campaign budgets
- `ads_performance` — Retrieve campaign performance metrics (impressions, clicks, conversions, CPA, ROAS)
- `ads_keywords` — Manage Google Ads keywords (add, pause, adjust bids)
- `ads_audiences` — Manage Meta audience segments (custom, lookalike, saved)
- `ads_recommendations` — AI-generated optimization recommendations based on performance data

**Acceptance Criteria:**
- Given a Google Ads campaign brief, when `ads_create_campaign` is invoked, then a campaign is created via the Google Ads API (GAQL) with the specified budget, targeting, and ad copy
- Given a Meta campaign brief, when `ads_create_campaign` is invoked, then a campaign is created via the Meta Marketing API with the specified audience, placement, and creative
- Given campaign performance data, when `ads_performance` is invoked, then metrics are returned in a normalized format regardless of platform (Google or Meta)
- Given a budget increase request exceeding the configured maximum daily spend, when `ads_manage_budget` is invoked, then the agent blocks the increase and notifies the user for approval
- Given campaign performance data, when `ads_recommendations` is invoked, then the agent analyzes spend efficiency and suggests specific optimizations (bid adjustments, audience refinements, ad copy improvements)

**Priority:** P1
**Dependencies:** Core Marketing Framework (5.3.2)
**Estimated Effort:** 2 sessions

#### 5.3.7 Feature: Marketing UI Panel

**Description:** A React application served at `/marketing` providing campaign management, content calendar, social media feeds, analytics dashboard, and content approval queue.

**New Directory:** `marketing-ui/` (~3000 LOC)

**Pages:**
- **Campaign Dashboard** — Active campaigns with status, budget utilization, and key metrics
- **Content Calendar** — Drag-and-drop scheduling of content items across platforms and dates
- **Social Media Feed** — Multi-platform preview of scheduled and published posts with engagement metrics
- **Analytics Dashboard** — Cross-channel metrics: impressions, clicks, conversions, attribution, ROI
- **Content Approval Queue** — Pending content items with one-click approve/reject and inline editing
- **Brand Voice** — Brand profile editor with tone, vocabulary, examples, and platform guidelines

**Acceptance Criteria:**
- Given the content calendar, when a content item is dragged to a new date, then the scheduled publish time is updated via the marketing REST API
- Given the approval queue, when the user clicks "Approve", then the content item transitions from REVIEW to APPROVED
- Given the analytics dashboard, when cross-channel data is displayed, then metrics from social media, email, ads, and SEO are shown on a unified timeline
- Given the social media feed, when a platform is selected, then posts are displayed with platform-specific formatting previews (Instagram grid, Twitter timeline, LinkedIn feed)

**Priority:** P1
**Dependencies:** Social Media Plugin (5.3.3), Email Marketing Plugin (5.3.4)
**Estimated Effort:** 2-3 sessions

#### 5.3.8 Feature: Sub-Agent Marketing Workflows

**Description:** Pre-built multi-agent orchestration patterns for marketing tasks. These leverage the existing `SubAgentOrchestrator` to parallelize work and use build-review patterns for quality control.

**Workflow Patterns:**
- **Campaign Launch**: 2 researcher agents (audience + competitor analysis) -> 3 content writer agents (social, email, ad copy) -> 1 synthesizer (unified campaign brief)
- **Competitor Analysis**: N researcher agents (one per competitor) -> 1 synthesizer (competitive landscape report)
- **A/B Content Generation**: 2 builder agents (different prompts/models) -> 1 reviewer (comparing variants)
- **Monthly Report**: N data collector agents (one per channel) -> 1 report writer -> 1 reviewer

**Acceptance Criteria:**
- Given a "launch campaign" request, when the marketing workflow is triggered, then researchers run in parallel followed by content writers followed by synthesis
- Given all marketing workflows, when they execute, then they register in WorkRegistry and appear on the KanBan board with real-time progress
- Given the A/B workflow, when two content variants are produced, then the reviewer agent compares them against the brand voice profile and selects the winner with reasoning

**Priority:** P2
**Dependencies:** All marketing plugins, existing `SubAgentOrchestrator`
**Estimated Effort:** 1 session

---

## 6. Vertical Framework PRD

### 6.1 Overview

The vertical framework is the mechanism by which industry-specific modules are loaded, configured, and served. Each vertical is a self-contained directory containing a plugin (tools), SQLAlchemy models (database tables), REST API routes, pre-built workflows, system prompt extensions, and a React UI application. The framework handles auto-discovery, license gating, route mounting, and database schema management.

### 6.2 Directory Structure

```
backend/verticals/
    base.py                    # VerticalModule ABC
    loader.py                  # Auto-discovery, license gating, route mounting
    cafe/
        __init__.py
        plugin.py              # NexusPlugin subclass with domain-specific tools
        models.py              # SQLAlchemy models
        routes.py              # FastAPI router with REST API endpoints
        workflows.py           # Pre-built sub-agent workflow definitions
        prompts.py             # System prompt extensions
        ui/                    # React app (Vite + Radix + Tailwind 4)
            src/
                pages/
                    dashboard.tsx
                    ...
    gym/
        __init__.py
        plugin.py
        models.py
        routes.py
        workflows.py
        prompts.py
        ui/
            src/
                pages/
                    dashboard.tsx
                    ...
```

### 6.3 Feature: VerticalModule Base Class

**Description:** An abstract base class that all verticals implement. Defines the contract for plugin registration, route mounting, database schema creation, system prompt injection, and workflow registration.

**New File:** `backend/verticals/base.py` (~200 LOC)

**Interface:**
```python
class VerticalModule(ABC):
    name: str                  # 'cafe', 'gym', 'healthcare'
    display_name: str          # 'Cafe/Restaurant', 'Gym/Fitness'
    route_prefix: str          # '/cafe', '/gym'
    version: str               # Semantic version

    @abstractmethod
    def get_plugin(self) -> NexusPlugin: ...
    @abstractmethod
    def get_router(self) -> APIRouter: ...
    @abstractmethod
    async def ensure_tables(self, engine): ...
    @abstractmethod
    def get_system_prompt_extension(self, config: dict) -> str: ...
    @abstractmethod
    def get_workflows(self) -> list[WorkflowDefinition]: ...
    @abstractmethod
    def get_ui_build_path(self) -> Path: ...
```

**Acceptance Criteria:**
- Given a class that extends `VerticalModule`, when it implements all abstract methods, then it can be loaded by the vertical loader
- Given a vertical's `get_plugin()`, when called, then it returns a `NexusPlugin` subclass with tools prefixed by `{vertical_name}__` (e.g., `cafe__menu_list`)
- Given a vertical's `get_system_prompt_extension()`, when the agent processes a message, then the vertical's context is injected into the system prompt (e.g., "You are managing a cafe called {name}. You know the menu, hours, and can take orders.")
- Given a vertical's `ensure_tables()`, when called at startup, then all database tables for the vertical are created if they do not exist (same pattern as existing `ensure_org_id_columns()`)

**Priority:** P0
**Dependencies:** None
**Estimated Effort:** Included in Vertical Framework sessions

### 6.4 Feature: Vertical Loader and Auto-Discovery

**Description:** Automatically discovers vertical modules in the `backend/verticals/` directory, validates their license status, mounts their routes, registers their plugins, creates their database tables, and serves their UI static files.

**New File:** `backend/verticals/loader.py` (~300 LOC)

**Acceptance Criteria:**
- Given a directory `backend/verticals/cafe/` with a valid `__init__.py` exporting a `VerticalModule` subclass, when the application starts, then the vertical is discovered and loaded
- Given a vertical without a valid license, when the loader attempts to load it, then a `VerticalNotLicensed` exception is raised and the vertical is skipped (not loaded)
- Given a licensed vertical, when it is loaded, then its FastAPI router is mounted at `route_prefix`, its plugin is registered with the plugin manager, and its database tables are created
- Given a vertical's UI build path, when a request is made to `/{vertical_name}/`, then the React application is served with appropriate cache-control headers (same pattern as existing frontend serving)
- Given multiple verticals, when the application starts, then each vertical is loaded independently and a failure in one vertical does not prevent others from loading

**Priority:** P0
**Dependencies:** VerticalModule Base Class (6.3)
**Estimated Effort:** Part of 2-3 session vertical framework build

### 6.5 Feature: License Gating for Verticals

**Description:** Integration with the licensing system to enforce vertical access based on subscription tier. Free tier gets no verticals. Pro tier gets 1 vertical. Business tier gets up to 3 verticals. Enterprise gets unlimited.

**Acceptance Criteria:**
- Given a Free tier license, when any vertical is accessed, then a "Vertical not available on your plan" message is returned
- Given a Pro tier license with the cafe vertical enabled, when the cafe vertical is accessed, then it loads normally; when the gym vertical is accessed, then it is blocked
- Given a Business tier license, when up to 3 verticals are configured, then all 3 load; the 4th is blocked
- Given an Enterprise tier license, when any number of verticals are configured, then all load without restriction

**Priority:** P1
**Dependencies:** Licensing system (Section 11), Vertical Loader (6.4)
**Estimated Effort:** Included in Vertical Framework sessions

---

## 7. Vertical: Gym/Fitness

### 7.1 Overview

The gym vertical is primarily an automated messaging engine powered by the Nexus agent. It replaces a front desk manager, a marketing person, and a retention specialist through 8 automation sequence categories covering the full member lifecycle from lead capture through cancellation and reactivation. Every sequence fires through Core Comms (SMS via Twilio, email via Mailchimp/SendGrid) with the agent making intelligent decisions about timing, content, and escalation.

### 7.2 Automation Sequences

#### 7.2.1 New Leads Pipeline

**Description:** Automated lead capture and nurturing from website signup, chatbot interaction, or social media through to trial booking and follow-up.

**Triggers and Actions:**

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| New profile/website signup | Instant welcome + trial booking CTA | SMS + Email | Immediate |
| Website chatbot interaction | Agent books trial via conversational flow | WhatsApp/Web chat | Real-time |
| Trial booked | Booking confirmation + what to expect | SMS + Email | Immediate |
| First session completed | Check-in: "How was your first session?" | SMS | 2 hours after |
| No response to initial outreach | Follow-up sequence | SMS | Day 1, 3, 7 |

**Lead Scoring System:**
- +10: Opened email
- +20: Clicked link
- +30: Visited pricing page (tracked via UTM)
- +50: Booked trial
- +100: Attended trial
- -10/day: No engagement decay
- Hot (score > 80), Warm (40-80), Cold (< 40)
- Agent adjusts outreach cadence and tone based on score

**Acceptance Criteria:**
- Given a new website signup, when the lead is created via `gym__add_lead`, then a welcome SMS and email are sent within 60 seconds
- Given a lead with no response after Day 1, when the follow-up scheduler runs, then a Day 1 follow-up SMS is sent with a different message than the initial outreach
- Given a lead with score > 80 (hot), when the agent generates outreach, then the tone is more direct with specific trial time suggestions
- Given a lead with score < 40 (cold), when the agent generates outreach, then the tone is softer with value-proposition content

**Priority:** P0
**Dependencies:** Core Comms (SMS, WhatsApp), gym_members table
**Estimated Effort:** Included in Gym Session 2-3

#### 7.2.2 Trials Management

**Description:** Automated trial session lifecycle from booking through attendance (or no-show) to post-trial conversion.

**Triggers and Actions:**

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| Trial booked | Reminder with venue/parking/what to wear | SMS | 24h before |
| Trial day | Final reminder | SMS | 2h before |
| No-show | "We missed you! Let's reschedule" | SMS | 30 min after |
| Late cancellation | Understanding message + rebook CTA | SMS | Immediate |
| Trial completed | Post-trial survey + membership CTA | SMS + Email | 1h after |
| Trial completed, no signup (Day 1) | "Any questions about membership?" | SMS | Next day |
| Trial completed, no signup (Day 3) | Special offer or benefit reminder | SMS | Day 3 |
| Trial completed, no signup (Day 7) | Final personal outreach | SMS | Day 7 |

**Acceptance Criteria:**
- Given a trial booked for tomorrow, when the reminder scheduler runs, then a personalized SMS with venue details is sent 24 hours before the session
- Given a trial no-show, when 30 minutes pass after the scheduled time, then a compassionate rescheduling SMS is sent
- Given a completed trial with no signup by Day 3, when the follow-up scheduler runs, then a message highlighting a specific benefit or offer is sent
- Given all trial follow-up messages, when they are composed, then the agent personalizes them using the lead's name, the specific class they attended, and their expressed interests

**Priority:** P0
**Dependencies:** New Leads Pipeline (7.2.1), Core Comms (SMS)
**Estimated Effort:** Included in Gym Session 3

#### 7.2.3 Member Retention

**Description:** Proactive retention through attendance monitoring, milestone celebrations, birthday greetings, periodic check-ins, and Google review prompts.

**Triggers and Actions:**

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| No attendance in X days (configurable: 7/14/21) | "We miss you!" check-in | SMS | Configurable |
| Milestone: 50th/100th/200th session | Celebration message + share prompt | SMS + Email | After session |
| Birthday | Birthday greeting + special offer | SMS | Morning of |
| No-show / late cancel | Understanding follow-up | SMS | 30 min after |
| Monthly check-in | "How are you tracking toward your goals?" | SMS | Monthly (configurable day) |
| Quarterly feedback | NPS survey | SMS + Email | Quarterly |
| Positive interaction detected | Google review prompt | SMS | After milestone or positive response |

**Acceptance Criteria:**
- Given a member who has not attended for 14 days (default configurable threshold), when the retention scheduler runs, then a personalized check-in SMS is sent referencing their last class and goals
- Given a member who completes their 100th session, when the attendance is recorded, then a celebration message is sent within 2 hours and a social media share prompt is offered
- Given a member's birthday, when the day arrives, then a birthday greeting with a configurable special offer is sent in the morning
- Given an NPS response below 7, when received, then the agent flags the member as at-risk and schedules a follow-up conversation

**Priority:** P0
**Dependencies:** gym_attendance table, gym_comms_log table, Core Comms (SMS, Email)
**Estimated Effort:** Included in Gym Session 4

#### 7.2.4 Cancellations and Reactivation

**Description:** Retention conversation on cancellation request, graceful farewell messaging, and timed reactivation outreach at 30 and 90 days post-cancellation.

**Triggers and Actions:**

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| Cancellation request | Retention conversation (agent asks why, offers alternatives) | SMS/WhatsApp/Voice | Immediate |
| Member cancelled | Farewell + door-open message | Email | Day of |
| 30 days post-cancel | Reactivation offer | SMS | Day 30 |
| 90 days post-cancel | "We'd love to have you back" + new program info | SMS + Email | Day 90 |
| Cold leads (> 60 days inactive) | Reactivation sequence | SMS | Automated |

**Acceptance Criteria:**
- Given a cancellation request, when the agent processes it, then it initiates a retention conversation asking for the reason and offering alternatives (freeze, downgrade, schedule change) before processing the cancellation
- Given a cancelled member at 30 days, when the reactivation scheduler runs, then a personalized offer is sent referencing their previous membership and any new programs
- Given all reactivation messages, when sent, then they include a one-click re-signup link and the offer expires in 7 days

**Priority:** P0
**Dependencies:** Member Retention (7.2.3), Core Comms
**Estimated Effort:** Included in Gym Session 4

#### 7.2.5 Suspended Members

**Description:** Support for members on temporary suspension (injury, pregnancy, travel) with caring check-ins and welcome-back messaging.

**Acceptance Criteria:**
- Given a member with a suspension starting today, when the scheduler runs, then a confirmation message is sent with estimated return date
- Given a long-term suspended member (injury/pregnancy), when the monthly check-in runs, then a caring message is sent with no pressure to return
- Given a suspension ending in 3 days, when the scheduler runs, then a "welcome back" message is sent with the current week's class schedule

**Priority:** P1
**Dependencies:** gym_members table (suspension fields)
**Estimated Effort:** Included in Gym Session 4

#### 7.2.6 Challenges and Training Blocks

**Description:** Support for gym challenges (6-week challenges, transformation challenges) and training block rotations with automated communications for signups, check-ins, and transitions.

**Acceptance Criteria:**
- Given a new challenge announced, when the challenge is created via `gym__active_challenges`, then sign-up prompts are sent via SMS and posted to social media
- Given a challenge in progress, when the fortnightly check-in is due, then an encouragement message is sent to all participants
- Given a new training block starting next week, when the notification is triggered, then all active members receive a preview of the new block including main lifts and programming notes
- Given a block changeover day, when the day arrives, then a "new block starts today" message with what to expect is sent to all active members

**Priority:** P1
**Dependencies:** gym_challenges table, gym_blocks table, Core Comms, Core Marketing (Social)
**Estimated Effort:** Included in Gym Session 4

#### 7.2.7 Social Media Automation (Core Marketing Integration)

**Description:** Instagram DM lead capture, weekly content calendar generation, challenge promotion, and member milestone social posts, all powered by the Core Marketing social media plugin.

**Acceptance Criteria:**
- Given a new Instagram follower, when detected, then the agent sends an automated DM welcoming them and offering a trial session
- Given a DM conversation that captures lead details, when the lead flow completes, then the contact is added to `gym_members` as a lead with `lead_source='instagram'` and a trial booking SMS is sent
- Given the weekly content calendar, when generated, then 5-7 posts are created aligned to the current training block/challenge schedule with platform-appropriate formatting

**Priority:** P1
**Dependencies:** Core Marketing Social Media Plugin (5.3.3)
**Estimated Effort:** Included in Gym Session 2

#### 7.2.8 New Member Onboarding

**Description:** Structured onboarding sequence from membership activation through the first 30 days.

**Acceptance Criteria:**
- Given a new membership activation, when the member is created, then a welcome message with essentials (app download, parking, schedule) is sent via SMS and email
- Given the member's first session completed, when recorded, then a "Welcome to the family!" message with a link to the Facebook group is sent
- Given 5 sessions completed, when recorded, then a goal-setting check-in message is sent
- Given 30 days since signup, when the scheduler runs, then a first-month survey and Google review prompt are sent

**Priority:** P0
**Dependencies:** gym_members table, gym_attendance table, Core Comms
**Estimated Effort:** Included in Gym Session 2

### 7.3 Gym Tools

30 tools organized into 7 categories:

**Member Management (4 tools):**
- `gym__add_member` — Create new member with profile, plan, start date
- `gym__update_member` — Update status, plan, contact details
- `gym__member_search` — Find member by name, email, phone, status
- `gym__member_profile` — Full member view: attendance, score, comms history

**Attendance and Scheduling (4 tools):**
- `gym__check_attendance` — Query attendance for member/class/date range
- `gym__class_schedule` — View/manage class timetable
- `gym__book_trial` — Book a trial session for a lead
- `gym__record_attendance` — Mark member as attended/no-show

**Lead Management (3 tools):**
- `gym__add_lead` — Create lead from any source (web, social, walk-in)
- `gym__score_lead` — Calculate/update lead score
- `gym__lead_pipeline` — View leads by stage (new, contacted, trial booked, trial complete, signed up, lost)

**Retention and Engagement (4 tools):**
- `gym__member_milestones` — Check approaching milestones (50th session, birthday)
- `gym__at_risk_members` — Members with declining attendance or approaching cancel
- `gym__send_checkin` — Trigger a personalized check-in message
- `gym__survey_results` — View NPS and feedback data

**Challenges and Blocks (4 tools):**
- `gym__active_challenges` — Current and upcoming challenges
- `gym__challenge_signup` — Register member for a challenge
- `gym__block_schedule` — Current/upcoming training blocks with program details
- `gym__block_notify` — Trigger block change notifications

**Cancellations and Suspensions (3 tools):**
- `gym__process_cancellation` — Handle cancellation with retention conversation
- `gym__suspend_member` — Apply suspension with return date
- `gym__reactivation_queue` — Members eligible for reactivation outreach

**Reporting (3 tools):**
- `gym__daily_summary` — Today's attendance, signups, cancellations, revenue
- `gym__retention_report` — Churn rate, at-risk count, reactivation success
- `gym__lead_report` — Pipeline conversion rates, source attribution

**Acceptance Criteria (all tools):**
- Given any gym tool, when invoked, then it operates within the calling user's `org_id` (tenant isolation)
- Given any gym tool, when invoked, then the execution is logged in the audit trail with duration_ms
- Given the `gym__daily_summary` tool, when invoked, then it returns a structured summary with today's attendance count, new signups, cancellations, at-risk members, and estimated revenue

**Priority:** P0 (member management, attendance, leads), P1 (retention, challenges, reporting)
**Dependencies:** Gym database tables (Section 9)
**Estimated Effort:** Gym Session 1 (core tools), Session 2-4 (remaining tools)

### 7.4 Gym UI Pages

9 pages served at `/gym`:

| Page | Purpose | Priority |
|------|---------|----------|
| **Dashboard** | Today's attendance, new leads, at-risk members, upcoming milestones, revenue | P0 |
| **Members** | Member list with search/filter, status tabs (Active/Trial/Suspended/Cancelled), inline profile | P0 |
| **Leads** | Lead pipeline board (KanBan: New, Contacted, Trial Booked, Trial Complete, Signed Up, Lost) | P0 |
| **Schedule** | Class timetable, attendance heatmap, booking management | P1 |
| **Sequences** | Automation sequence editor: enable/disable, edit templates, set triggers and timing | P1 |
| **Challenges** | Active/upcoming challenges, participant list, check-in tracking | P1 |
| **Blocks** | Training block calendar, program details, notification preview | P2 |
| **Reports** | Retention rate, churn, lead conversion, attendance trends, revenue, NPS | P1 |
| **Comms Log** | Every message sent by the agent, with delivery status and member responses | P1 |

**Estimated Effort:** Gym Session 5

---

## 8. Vertical: Cafe/Restaurant

### 8.1 Overview

The cafe vertical's primary capability is supplier ordering automation. Based on real operational data from a London cafe, this vertical manages 13 suppliers with different ordering methods (Rekki app, email, online portals, supplier apps), frequencies (daily, weekly, bi-weekly, monthly, ad hoc), delivery windows, and payment terms. The Nexus agent automates daily milk and pastry orders, weekly coffee and ingredient orders, monitors inventory against par levels, tracks invoices, and handles customer ordering via WhatsApp and voice.

### 8.2 Supplier Registry

13 suppliers with varying integration methods:

| Supplier | Products | Order Frequency | Order Method | Lead Time | Payment |
|----------|----------|----------------|-------------|-----------|---------|
| Stones Supply | Milk and Bottled Drinks | Daily | Rekki App | 1 day | Direct Debit |
| Delaserr | Pastries | Daily | Owned App | 1 day | Direct Debit |
| Triple Co Roast | Coffee Products | Weekly | Online Portal | 1 day | Direct Debit |
| Cake Hoard | Bakes | Weekly | Online Portal | 1 day | In-Portal |
| House of Cine | Cinnamon Buns | Weekly | Email | 3 day | Invoice + Manual |
| Becker | Fresh Ingredients and Sundries | Weekly | Owned App | 1 day | In-App |
| Amkava | Disposable Packaging | Bi-Weekly | Rekki App | 1 day | In-App |
| Purpose Foods Ltd | Protein Balls | Bi-Weekly | Email | 2 day | Invoice + Manual |
| Cups Direct | Cup Sleeves | Monthly | Online Portal | 1 day | In-Portal |
| Carrier Bag Shop | Paper Bags | Monthly | Online Portal | 1 day | In-Portal |
| The Estate Dairy | Milk (Emergency) | Ad Hoc | Rekki App | 1 day | In-App |
| Amazon Prime | Miscellaneous | Ad Hoc | Online Portal | Various | In-Portal |
| Nisbets | Catering Supplies | Ad Hoc | Online Portal | Various | In-Portal |

### 8.3 Ordering Automation

#### 8.3.1 Daily Ordering (Milk, Pastries)

**Description:** Each evening the agent checks inventory levels, calculates tomorrow's order based on day-of-week demand patterns, weather forecast, events/holidays, and historical sell-through data. The order is sent to the owner for approval via WhatsApp before being placed.

**Acceptance Criteria:**
- Given the evening scheduler, when daily ordering runs, then inventory levels are checked and an order is drafted for each daily supplier (Stones Supply, Delaserr)
- Given a draft order, when sent for approval, then the owner receives a WhatsApp message with supplier name, items, quantities, and estimated cost
- Given owner approval (reply "yes"), when received, then the agent places the order via the appropriate channel (Rekki API, supplier app)
- Given Stones Supply cannot deliver on Thursday to West London, when Thursday ordering runs, then the agent automatically switches to The Estate Dairy for emergency milk cover and notifies the owner
- Given weather data indicating a hot day, when calculating milk order quantities, then the agent increases iced drink ingredient quantities based on historical hot-day patterns

**Priority:** P0
**Dependencies:** cafe_suppliers table, cafe_inventory table, Core Comms (WhatsApp)
**Estimated Effort:** Cafe Session 2

#### 8.3.2 Weekly Ordering (Coffee, Bakes, Fresh Ingredients)

**Description:** Agent generates weekly orders based on current stock, next week's bookings/events, seasonal menu items, and supplier minimum order quantities (MOQs).

**Acceptance Criteria:**
- Given the weekly scheduler (e.g., Sunday evening), when weekly ordering runs, then orders are drafted for each weekly supplier (Triple Co Roast, Cake Hoard, House of Cine, Becker)
- Given an email-based supplier (House of Cine), when the order is approved, then the agent composes and sends an order email via SendGrid using the supplier's standard template format
- Given a portal-based supplier (Triple Co Roast), when the order is approved, then the order details are surfaced for the owner to place (or automated via browser if API is available)
- Given a delivery, when received, then the agent confirms receipt and flags any shortages

**Priority:** P0
**Dependencies:** Daily Ordering (8.3.1)
**Estimated Effort:** Included in Cafe Session 2

#### 8.3.3 Bi-Weekly, Monthly, and Ad Hoc Ordering

**Description:** Stock-level-triggered reordering for packaging and sundries. Invoice tracking and payment reminders for manual-payment suppliers.

**Acceptance Criteria:**
- Given inventory below par level for a bi-weekly/monthly item, when the monitoring scheduler runs, then a reorder is triggered
- Given an invoice from House of Cine, when the agent tracks it, then a WhatsApp reminder is sent to the owner before the payment due date
- Given a staff member messages via WhatsApp "We're running low on takeaway cups", when the agent receives it, then it checks the supplier (Cups Direct), lead time, last order price, and drafts the order for approval

**Priority:** P1
**Dependencies:** Weekly Ordering (8.3.2)
**Estimated Effort:** Included in Cafe Session 2

### 8.4 Customer Ordering Automation

**Description:** Customer-facing ordering via WhatsApp and voice calls. The Nexus agent takes orders from the cafe menu, confirms totals and pickup times, registers orders on the internal dashboard, and sends notifications when orders are ready.

**Acceptance Criteria:**
- Given a WhatsApp message "Can I order 2 flat whites and a banana bread for pickup at 10?", when processed by the agent, then the order is created via `cafe__take_order` with items, total, and pickup time
- Given a voice call, when the customer requests items, then the agent uses speech recognition to capture the order, confirms it verbally, and creates the order
- Given an order created, when it appears on the `/cafe` dashboard, then staff can see the items, pickup time, and channel of origin
- Given an order marked as ready by staff, when the status changes, then the customer receives a "Your order is ready for pickup!" notification on the original channel

**Priority:** P0
**Dependencies:** cafe_menu table, cafe_orders table, Core Comms (WhatsApp, Voice)
**Estimated Effort:** Cafe Session 3

### 8.5 Reviews and Reputation Management

**Description:** Monitor Google, TripAdvisor, and Yelp reviews. The agent detects new reviews, drafts brand-voice responses, and queues them for owner approval before posting.

**Acceptance Criteria:**
- Given a new Google review, when detected by `cafe__monitor_reviews`, then the agent drafts a brand-voice response and sends it to the owner for approval via WhatsApp
- Given a positive review (4-5 stars), when the response is approved, then a thank-you response is posted and a social share prompt is offered
- Given a negative review (1-2 stars), when the response is approved, then an empathetic response with an offer to make it right is posted
- Given the weekly review summary, when generated, then the owner receives "This week: X new reviews, Y.Z average, +/- from last week" via WhatsApp

**Priority:** P1
**Dependencies:** Core Comms (WhatsApp), Core Marketing (Brand Voice)
**Estimated Effort:** Cafe Session 4

### 8.6 Cafe Tools

18 tools organized into 6 categories:

**Menu Management (3 tools):**
- `cafe__menu_list` — View current menu with prices, categories, availability
- `cafe__menu_update` — Add/edit/disable menu items, set daily specials
- `cafe__menu_pricing` — Update prices, cost analysis (COGS tracking)

**Customer Ordering (3 tools):**
- `cafe__take_order` — Process customer order (WhatsApp/voice/walk-in)
- `cafe__order_status` — Check order status for customer
- `cafe__order_history` — Customer's past orders (for personalization)

**Supplier Management (6 tools):**
- `cafe__supplier_list` — All suppliers with ordering methods, schedules, contacts
- `cafe__supplier_order` — Generate and place supplier order
- `cafe__check_inventory` — Current stock levels vs par levels
- `cafe__order_schedule` — What needs ordering today/this week
- `cafe__track_delivery` — Mark deliveries as received, flag shortages
- `cafe__invoice_tracker` — Outstanding invoices, payment reminders

**Loyalty and Customers (3 tools):**
- `cafe__loyalty_balance` — Check/update customer loyalty points
- `cafe__customer_profile` — Regular customers: preferences, order history, spend
- `cafe__loyalty_reward` — Issue reward (free coffee, discount)

**Reviews and Reputation (3 tools):**
- `cafe__monitor_reviews` — Check new reviews across platforms
- `cafe__draft_review_reply` — Generate brand-voice response to review
- `cafe__review_stats` — Average rating, trend, volume by platform

**Reporting (3 tools):**
- `cafe__daily_summary` — Sales, orders, popular items, waste, inventory
- `cafe__weekly_report` — Revenue trends, best sellers, supplier costs, marketing ROI
- `cafe__cogs_report` — Cost of goods sold analysis per menu item

**Priority:** P0 (menu, ordering, supplier), P1 (loyalty, reviews, reporting)
**Dependencies:** Cafe database tables (Section 9)
**Estimated Effort:** Cafe Sessions 1-4

### 8.7 Cafe UI Pages

8 pages served at `/cafe`:

| Page | Purpose | Priority |
|------|---------|----------|
| **Dashboard** | Today's orders, revenue, inventory alerts, pending supplier orders, review summary | P0 |
| **Orders** | Live order board (kitchen display), order history, per-customer view | P0 |
| **Menu** | Menu editor with categories, pricing, availability toggle, daily specials | P0 |
| **Inventory** | Stock levels with par-level alerts, reorder triggers, waste logging | P0 |
| **Suppliers** | Supplier registry, order schedule, delivery calendar, invoice tracker | P0 |
| **Customers** | Loyalty members, order history, preferences, review correlation | P1 |
| **Reviews** | All-platform review feed, response drafts, rating trends | P1 |
| **Reports** | Daily/weekly/monthly: revenue, COGS, popular items, supplier spend, marketing ROI | P1 |

**Estimated Effort:** Cafe Session 5

---

## 9. Database Schema

### 9.1 Communications Tables

```sql
-- Cross-channel user identity linking
CREATE TABLE channel_identities (
    id SERIAL PRIMARY KEY,
    nexus_user_id UUID NOT NULL,
    channel VARCHAR(20) NOT NULL,
    channel_user_id VARCHAR(100) NOT NULL,
    display_name VARCHAR(100),
    paired_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(channel, channel_user_id)
);

CREATE INDEX idx_channel_identities_user ON channel_identities(nexus_user_id);
CREATE INDEX idx_channel_identities_lookup ON channel_identities(channel, channel_user_id);

-- Voice call records
CREATE TABLE voice_calls (
    id SERIAL PRIMARY KEY,
    call_sid VARCHAR(50) UNIQUE,
    conv_id UUID,
    nexus_user_id UUID,
    direction VARCHAR(10) NOT NULL,
    caller_number VARCHAR(30),
    status VARCHAR(20) NOT NULL,
    duration_seconds INTEGER,
    transcript TEXT,
    stt_provider VARCHAR(20),
    tts_provider VARCHAR(20),
    tts_chars INTEGER,
    cost_usd DECIMAL(8,4),
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP
);

CREATE INDEX idx_voice_calls_conv ON voice_calls(conv_id);
CREATE INDEX idx_voice_calls_user ON voice_calls(nexus_user_id);
```

### 9.2 Marketing Tables

```sql
-- Brand voice profiles
CREATE TABLE brand_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    tone VARCHAR(50),
    vocabulary_rules JSONB,
    examples JSONB,
    platform_guidelines JSONB,
    is_default BOOLEAN DEFAULT FALSE,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Marketing campaigns
CREATE TABLE campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    status VARCHAR(20) DEFAULT 'planning',
    campaign_type VARCHAR(30),
    budget_usd DECIMAL(10,2),
    spent_usd DECIMAL(10,2) DEFAULT 0,
    start_date DATE,
    end_date DATE,
    goals JSONB,
    strategy TEXT,
    brand_profile_id INTEGER REFERENCES brand_profiles(id),
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_campaigns_status ON campaigns(status);
CREATE INDEX idx_campaigns_org ON campaigns(org_id);

-- Content items (posts, emails, ads)
CREATE TABLE content_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID REFERENCES campaigns(id),
    content_type VARCHAR(30) NOT NULL,
    platform VARCHAR(30),
    status VARCHAR(20) DEFAULT 'draft',
    title VARCHAR(200),
    body TEXT,
    media_urls JSONB,
    scheduled_at TIMESTAMP,
    published_at TIMESTAMP,
    external_id VARCHAR(100),
    metrics JSONB,
    brand_profile_id INTEGER REFERENCES brand_profiles(id),
    created_by VARCHAR(50),
    approved_by VARCHAR(50),
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_content_items_status ON content_items(status);
CREATE INDEX idx_content_items_campaign ON content_items(campaign_id);
CREATE INDEX idx_content_items_scheduled ON content_items(scheduled_at)
    WHERE status = 'scheduled';

-- Calendar events (unified content calendar)
CREATE TABLE calendar_events (
    id SERIAL PRIMARY KEY,
    campaign_id UUID REFERENCES campaigns(id),
    content_item_id UUID REFERENCES content_items(id),
    event_type VARCHAR(20) NOT NULL,
    title VARCHAR(200),
    scheduled_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    org_id UUID
);

CREATE INDEX idx_calendar_events_date ON calendar_events(scheduled_at);

-- Marketing metrics (time-series)
CREATE TABLE marketing_metrics (
    id SERIAL PRIMARY KEY,
    source VARCHAR(30) NOT NULL,
    metric_name VARCHAR(50) NOT NULL,
    metric_value DECIMAL(12,4),
    dimensions JSONB,
    recorded_at TIMESTAMP NOT NULL,
    org_id UUID
);

CREATE INDEX idx_marketing_metrics_source ON marketing_metrics(source, metric_name);
CREATE INDEX idx_marketing_metrics_time ON marketing_metrics(recorded_at);

-- Platform connections (encrypted OAuth tokens)
CREATE TABLE platform_connections (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(30) NOT NULL,
    account_name VARCHAR(100),
    credentials_encrypted TEXT,
    scopes JSONB,
    status VARCHAR(20) DEFAULT 'active',
    last_refreshed_at TIMESTAMP,
    org_id UUID,
    connected_at TIMESTAMP DEFAULT NOW()
);
```

### 9.3 Gym/Fitness Tables

```sql
-- Members
CREATE TABLE gym_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    email VARCHAR(200),
    phone VARCHAR(30),
    status VARCHAR(20) DEFAULT 'active',
    membership_plan VARCHAR(50),
    start_date DATE,
    end_date DATE,
    lead_score INTEGER DEFAULT 0,
    lead_source VARCHAR(50),
    lead_stage VARCHAR(30) DEFAULT 'new',
    goals TEXT,
    birthday DATE,
    total_sessions INTEGER DEFAULT 0,
    last_attendance DATE,
    suspension_start DATE,
    suspension_end DATE,
    suspension_reason VARCHAR(100),
    cancellation_date DATE,
    cancellation_reason TEXT,
    notes JSONB,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_gym_members_status ON gym_members(status);
CREATE INDEX idx_gym_members_org ON gym_members(org_id);
CREATE INDEX idx_gym_members_phone ON gym_members(phone);
CREATE INDEX idx_gym_members_email ON gym_members(email);
CREATE INDEX idx_gym_members_lead ON gym_members(lead_stage) WHERE status = 'lead';

-- Attendance records
CREATE TABLE gym_attendance (
    id SERIAL PRIMARY KEY,
    member_id UUID REFERENCES gym_members(id) ON DELETE CASCADE,
    class_name VARCHAR(100),
    attended BOOLEAN DEFAULT TRUE,
    late_cancel BOOLEAN DEFAULT FALSE,
    session_date TIMESTAMP NOT NULL,
    org_id UUID
);

CREATE INDEX idx_gym_attendance_member ON gym_attendance(member_id);
CREATE INDEX idx_gym_attendance_date ON gym_attendance(session_date);

-- Communication log
CREATE TABLE gym_comms_log (
    id SERIAL PRIMARY KEY,
    member_id UUID REFERENCES gym_members(id) ON DELETE CASCADE,
    channel VARCHAR(20) NOT NULL,
    sequence_name VARCHAR(50),
    message_content TEXT,
    sent_at TIMESTAMP DEFAULT NOW(),
    delivered BOOLEAN,
    response TEXT,
    responded_at TIMESTAMP,
    org_id UUID
);

CREATE INDEX idx_gym_comms_member ON gym_comms_log(member_id);
CREATE INDEX idx_gym_comms_sequence ON gym_comms_log(sequence_name);

-- Automation sequences (configurable triggers)
CREATE TABLE gym_sequences (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    trigger_type VARCHAR(50) NOT NULL,
    trigger_config JSONB,
    message_template TEXT NOT NULL,
    channel VARCHAR(20) DEFAULT 'sms',
    enabled BOOLEAN DEFAULT TRUE,
    delay_hours INTEGER DEFAULT 0,
    max_sends INTEGER,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Challenges
CREATE TABLE gym_challenges (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    start_date DATE,
    end_date DATE,
    signup_cutoff DATE,
    status VARCHAR(20) DEFAULT 'upcoming',
    checkin_frequency_days INTEGER DEFAULT 14,
    participant_count INTEGER DEFAULT 0,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Challenge participants (join table)
CREATE TABLE gym_challenge_participants (
    id SERIAL PRIMARY KEY,
    challenge_id INTEGER REFERENCES gym_challenges(id) ON DELETE CASCADE,
    member_id UUID REFERENCES gym_members(id) ON DELETE CASCADE,
    signed_up_at TIMESTAMP DEFAULT NOW(),
    completed BOOLEAN DEFAULT FALSE,
    UNIQUE(challenge_id, member_id)
);

-- Training blocks
CREATE TABLE gym_blocks (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    main_lifts JSONB,
    flow_notes TEXT,
    start_date DATE,
    end_date DATE,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 9.4 Cafe/Restaurant Tables

```sql
-- Menu items
CREATE TABLE cafe_menu (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    price DECIMAL(8,2) NOT NULL,
    cost DECIMAL(8,2),
    available BOOLEAN DEFAULT TRUE,
    is_daily_special BOOLEAN DEFAULT FALSE,
    image_url TEXT,
    allergens JSONB,
    display_order INTEGER DEFAULT 0,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_cafe_menu_category ON cafe_menu(category);
CREATE INDEX idx_cafe_menu_available ON cafe_menu(available) WHERE available = TRUE;

-- Suppliers
CREATE TABLE cafe_suppliers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    products TEXT,
    order_frequency VARCHAR(20) NOT NULL,
    order_method VARCHAR(30) NOT NULL,
    order_method_details JSONB,
    delivery_days VARCHAR(100),
    lead_time_days INTEGER DEFAULT 1,
    payment_method VARCHAR(30),
    contact_name VARCHAR(100),
    contact_email VARCHAR(200),
    contact_phone VARCHAR(30),
    min_order_value DECIMAL(8,2),
    notes TEXT,
    active BOOLEAN DEFAULT TRUE,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Inventory / stock levels
CREATE TABLE cafe_inventory (
    id SERIAL PRIMARY KEY,
    item_name VARCHAR(200) NOT NULL,
    category VARCHAR(50),
    current_qty DECIMAL(10,2) NOT NULL DEFAULT 0,
    unit VARCHAR(20) NOT NULL,
    par_level DECIMAL(10,2),
    reorder_qty DECIMAL(10,2),
    supplier_id INTEGER REFERENCES cafe_suppliers(id),
    last_ordered DATE,
    last_delivery DATE,
    cost_per_unit DECIMAL(8,2),
    org_id UUID,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_cafe_inventory_below_par ON cafe_inventory(current_qty, par_level)
    WHERE current_qty < par_level;

-- Customer orders
CREATE TABLE cafe_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID,
    customer_name VARCHAR(100),
    channel VARCHAR(20),
    items JSONB NOT NULL,
    total DECIMAL(8,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    pickup_time TIMESTAMP,
    completed_at TIMESTAMP,
    notes TEXT,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_cafe_orders_status ON cafe_orders(status);
CREATE INDEX idx_cafe_orders_date ON cafe_orders(created_at);

-- Supplier orders
CREATE TABLE cafe_supplier_orders (
    id SERIAL PRIMARY KEY,
    supplier_id INTEGER REFERENCES cafe_suppliers(id),
    items JSONB NOT NULL,
    total_estimated DECIMAL(8,2),
    status VARCHAR(20) DEFAULT 'draft',
    order_date DATE,
    expected_delivery DATE,
    actual_delivery DATE,
    placed_via VARCHAR(30),
    invoice_amount DECIMAL(8,2),
    invoice_due_date DATE,
    invoice_paid BOOLEAN DEFAULT FALSE,
    approved_by VARCHAR(100),
    notes TEXT,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_cafe_supplier_orders_status ON cafe_supplier_orders(status);
CREATE INDEX idx_cafe_supplier_orders_unpaid ON cafe_supplier_orders(invoice_paid)
    WHERE invoice_paid = FALSE AND invoice_amount IS NOT NULL;

-- Loyalty program
CREATE TABLE cafe_loyalty (
    id SERIAL PRIMARY KEY,
    customer_id UUID NOT NULL,
    customer_name VARCHAR(100),
    phone VARCHAR(30),
    email VARCHAR(200),
    points INTEGER DEFAULT 0,
    total_spend DECIMAL(10,2) DEFAULT 0,
    total_visits INTEGER DEFAULT 0,
    last_visit DATE,
    tier VARCHAR(20) DEFAULT 'bronze',
    preferences JSONB,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_cafe_loyalty_customer ON cafe_loyalty(customer_id);
CREATE INDEX idx_cafe_loyalty_phone ON cafe_loyalty(phone);
```

---

## 10. API Endpoints

### 10.1 Communications API

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/channels/twilio/webhook` | Twilio webhook for WhatsApp/SMS | Twilio signature |
| POST | `/api/channels/twilio/status` | Twilio delivery status callback | Twilio signature |
| POST | `/api/channels/twilio/voice` | Twilio voice webhook (returns TwiML) | Twilio signature |
| WS | `/api/voice/stream` | Twilio Media Streams WebSocket for real-time voice | Internal |
| GET | `/api/channels` | List active channels with status | Admin |
| GET | `/api/channels/{channel}/messages` | Message history for a channel | Admin |
| GET | `/api/channels/identities/{user_id}` | Cross-channel identities for a user | Admin |
| POST | `/api/channels/identities/link` | Link a channel identity to a nexus user | Admin |
| GET | `/api/voice/calls` | Voice call history with transcripts | Admin |
| GET | `/api/voice/calls/{id}` | Single call detail with full transcript | Admin |

### 10.2 Marketing API

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/marketing/campaigns` | List campaigns with status and metrics | Admin |
| POST | `/api/marketing/campaigns` | Create a new campaign | Admin |
| GET | `/api/marketing/campaigns/{id}` | Campaign detail with content items | Admin |
| PUT | `/api/marketing/campaigns/{id}` | Update campaign status, budget, dates | Admin |
| DELETE | `/api/marketing/campaigns/{id}` | Archive a campaign (soft delete) | Admin |
| GET | `/api/marketing/content` | List content items with filters | Admin |
| POST | `/api/marketing/content` | Create a new content item | Admin |
| PUT | `/api/marketing/content/{id}` | Update content item (edit, approve, schedule) | Admin |
| POST | `/api/marketing/content/{id}/approve` | Approve a content item for scheduling | Admin |
| POST | `/api/marketing/content/{id}/publish` | Publish a content item immediately | Admin |
| GET | `/api/marketing/calendar` | Content calendar events for date range | Admin |
| POST | `/api/marketing/calendar` | Add a calendar event | Admin |
| GET | `/api/marketing/analytics` | Cross-channel marketing metrics | Admin |
| GET | `/api/marketing/analytics/{source}` | Metrics for a specific source | Admin |
| GET | `/api/marketing/brand-profiles` | List brand voice profiles | Admin |
| POST | `/api/marketing/brand-profiles` | Create a brand voice profile | Admin |
| PUT | `/api/marketing/brand-profiles/{id}` | Update a brand voice profile | Admin |
| GET | `/api/marketing/platforms` | List connected platforms with status | Admin |
| POST | `/api/marketing/platforms/connect` | Initiate OAuth flow for a platform | Admin |
| DELETE | `/api/marketing/platforms/{id}` | Disconnect a platform | Admin |

### 10.3 Gym Vertical API

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/gym/members` | List members with search/filter/pagination | Admin |
| POST | `/api/gym/members` | Create a new member or lead | Admin |
| GET | `/api/gym/members/{id}` | Member profile with attendance and comms history | Admin |
| PUT | `/api/gym/members/{id}` | Update member details | Admin |
| GET | `/api/gym/members/{id}/attendance` | Attendance history for a member | Admin |
| POST | `/api/gym/members/{id}/attendance` | Record attendance for a member | Admin |
| GET | `/api/gym/leads` | Lead pipeline with stage counts | Admin |
| GET | `/api/gym/leads/scoring` | Lead scores with engagement breakdown | Admin |
| GET | `/api/gym/attendance/summary` | Daily/weekly attendance summary | Admin |
| GET | `/api/gym/sequences` | List automation sequences | Admin |
| PUT | `/api/gym/sequences/{id}` | Update sequence (enable/disable, edit template) | Admin |
| GET | `/api/gym/challenges` | List challenges with participant counts | Admin |
| POST | `/api/gym/challenges` | Create a new challenge | Admin |
| POST | `/api/gym/challenges/{id}/signup` | Sign up a member for a challenge | Admin |
| GET | `/api/gym/blocks` | List training blocks | Admin |
| POST | `/api/gym/blocks` | Create a training block | Admin |
| GET | `/api/gym/reports/daily` | Daily summary report | Admin |
| GET | `/api/gym/reports/retention` | Retention and churn report | Admin |
| GET | `/api/gym/reports/leads` | Lead conversion report | Admin |
| GET | `/api/gym/comms` | Communication log with filters | Admin |

### 10.4 Cafe Vertical API

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/cafe/menu` | Current menu with availability | Public (read) |
| POST | `/api/cafe/menu` | Add a menu item | Admin |
| PUT | `/api/cafe/menu/{id}` | Update a menu item | Admin |
| GET | `/api/cafe/orders` | List orders with status filters | Admin |
| POST | `/api/cafe/orders` | Create a new order | Admin |
| PUT | `/api/cafe/orders/{id}/status` | Update order status (preparing/ready/collected) | Admin |
| GET | `/api/cafe/suppliers` | List suppliers with ordering schedules | Admin |
| POST | `/api/cafe/suppliers` | Add a supplier | Admin |
| PUT | `/api/cafe/suppliers/{id}` | Update supplier details | Admin |
| GET | `/api/cafe/inventory` | Current inventory levels | Admin |
| PUT | `/api/cafe/inventory/{id}` | Update inventory quantity | Admin |
| GET | `/api/cafe/supplier-orders` | List supplier orders | Admin |
| POST | `/api/cafe/supplier-orders` | Create a supplier order | Admin |
| PUT | `/api/cafe/supplier-orders/{id}` | Update order status (approved/placed/delivered) | Admin |
| GET | `/api/cafe/loyalty/{customer_id}` | Customer loyalty balance | Admin |
| POST | `/api/cafe/loyalty/{customer_id}/reward` | Issue a loyalty reward | Admin |
| GET | `/api/cafe/reviews` | Recent reviews across platforms | Admin |
| POST | `/api/cafe/reviews/{id}/reply` | Post a reply to a review | Admin |
| GET | `/api/cafe/reports/daily` | Daily summary (sales, orders, inventory) | Admin |
| GET | `/api/cafe/reports/weekly` | Weekly report (revenue, trends, supplier spend) | Admin |

---

## 11. Licensing and Monetization

### 11.1 Tier Structure

| Feature | Free | Pro ($49/mo) | Business ($149/mo) | Enterprise (Custom) |
|---------|------|-------------|-------------------|-------------------|
| **Core: Chat + Admin** | Yes | Yes | Yes | Yes |
| **Core: Marketing** | No | Yes | Yes | Yes |
| **Core: Comms** | No | Yes | Yes | Yes |
| **Core: Workflow** | No | Yes | Yes | Yes |
| **Verticals** | None | 1 included | Up to 3 | Unlimited + custom |
| **Agents** | 1 | 5 (clustered) | 10 | Unlimited |
| **Models** | Ollama only | Ollama + Claude | All | All |
| **Sub-agents** | No | 3 concurrent | 10 concurrent | Unlimited |
| **Memory** | Basic PostgreSQL | + Vector search | + Graph memory | Full + cross-cluster |
| **Conversations** | 100/month | Unlimited | Unlimited | Unlimited |
| **Credits** | 1,000/mo | 50,000/mo | 200,000/mo | Custom |
| **Auth** | API key | Email/password + org | + SSO/SAML | + SCIM provisioning |
| **Support** | Community | Priority (48h) | Priority (24h) | Dedicated (4h SLA) |
| **Deployment** | Self-hosted | Cloud + self-hosted | Cloud + self-hosted | + On-prem + air-gap |
| **API access** | No | Yes | Yes | + Webhooks |
| **Clustering** | No | Yes | Yes | + Multi-region |

### 11.2 Credit Economy

```
1 credit = $0.001 USD

Credit costs by operation:
    Ollama request (any size):              0 credits (free, local compute)
    Claude Sonnet 1K input tokens:          3 credits
    Claude Sonnet 1K output tokens:         15 credits
    Claude Opus 1K input tokens:            15 credits
    Claude Opus 1K output tokens:           75 credits
    Plugin tool call:                       1 credit
    Sub-agent orchestration (per agent):    5 credits + model tokens
    Web fetch (headless render):            2 credits
    Marketplace plugin tool call:           Per plugin pricing
```

**Key Principle:** Local model usage (Ollama) is always free. Credits apply only to cloud model usage and premium features. This aligns with the local-first philosophy.

### 11.3 Feature Gating Integration Points

| File | Gating Check |
|------|-------------|
| `agent_runner.py` | `max_agents` check at agent creation |
| `sub_agent.py` | `require_feature("sub_agents")` at orchestration start |
| `models/router.py` | Filter available models by plan tier |
| `plugins/manager.py` | `max_plugins` + `custom_plugins` check at plugin load |
| `core/cluster/` | `require_feature("clustering")` on entire module |
| `routers/api.py` | `require_feature("api_access")` on API endpoints |
| `context_manager.py` | `max_conversations` per billing period |
| `verticals/loader.py` | `has_vertical(name)` check per vertical |
| `core/marketing/` | `has_feature("marketing")` on all marketing operations |
| `channels/` | `has_feature("comms")` on non-websocket channels |

### 11.4 Billing Integration

**Provider:** Stripe Billing (subscription + metered usage hybrid)

- **Stripe Billing**: $49/mo or $149/mo base subscription + $0.001/credit overage
- **Stripe Connect**: Marketplace developer payouts (Express accounts, auto-split revenue)
- **Stripe Checkout**: Payment collection (handles SCA/3DS, tax)
- **Stripe Customer Portal**: Self-service billing management

**Key Webhooks:**
- `checkout.session.completed` -> Provision license
- `invoice.payment_failed` -> Start 7-day grace period
- `customer.subscription.deleted` -> Downgrade to Free tier

**Grace Periods:**
- Payment failure: 7 days before downgrade to Free
- License expired: 14 days of continued access
- Server unreachable: 30 days cached validation
- Principle: Never lock out, never delete data. Graceful degradation to Free tier.

### 11.5 Plugin Marketplace

- **Revenue share**: 100/0 (developer keeps 100%) in Year 1 to build ecosystem; 85/15 at maturity
- **Security review**: Automated (Bandit + semgrep + dependency audit) + manual code review (3-5 days)
- **Plugin signing**: Ed25519 manifest signing + Nexus marketplace co-signature
- **Developer SDK**: `nexus-plugin-sdk` pip package with CLI (init, test, package, publish)

---

## 12. Dependencies and Costs

### 12.1 Python Packages (New)

```
# Communications
twilio>=8.0.0                  # WhatsApp, SMS, Voice
elevenlabs>=0.3.0              # Text-to-speech
deepgram-sdk>=3.0.0            # Speech-to-text
webrtcvad>=2.0.10              # Voice activity detection

# Marketing
social-post-api>=2.0.0         # Ayrshare social media
mailchimp-marketing>=3.0.0     # Email marketing
sendgrid>=6.0.0                # Transactional email
google-ads>=22.0.0             # Google Ads API
facebook-business>=17.0.0     # Meta Marketing API
tweepy>=4.14.0                 # Twitter/X direct access

# Workflow
libtmux>=0.30.0                # tmux programmatic control

# Frontend (npm, per UI app)
xterm                          # Terminal viewer component
@xterm/addon-fit               # Auto-fit terminal to container
```

### 12.2 External Service Costs (Monthly Estimates)

| Service | Plan | Estimated Cost | Used By |
|---------|------|---------------|---------|
| **Twilio** | 1 number + WhatsApp + SMS + Voice | $15-40 | Comms |
| **ElevenLabs** | Creator plan | $22 | Comms (TTS) |
| **Deepgram** | Pay-as-you-go | $5-15 | Comms (STT) |
| **Ayrshare** | Business plan | $99 | Marketing (Social) |
| **Mailchimp** | Standard plan | $0-20 | Marketing (Email) |
| **Google Ads API** | Free (ad spend separate) | $0 | Marketing (Ads) |
| **Meta Marketing API** | Free (ad spend separate) | $0 | Marketing (Ads) |
| **Google Search Console** | Free | $0 | Marketing (SEO) |
| **Ahrefs/SEMrush** | Optional | $99-130 | Marketing (SEO, optional) |
| **Stripe** | 2.9% + $0.30 per transaction | Variable | Billing |
| | | | |
| **Total (minimum)** | | **$141-227/month** | |
| **Total (with optional SEO tool)** | | **$240-357/month** | |

### 12.3 Infrastructure Costs (Existing)

| Resource | Purpose | Notes |
|----------|---------|-------|
| PostgreSQL | Primary database | Already running on localhost |
| Redis | Clustering, hot state (Phase 6) | Not yet deployed |
| Ollama | Local model inference | Already running, kimi-k2.5 |
| Claude API | Cloud model fallback | Pay per token |

---

## 13. Implementation Roadmap

### 13.1 Phase Ordering

The implementation follows three parallel streams (Communications, Terminal/Workflow, Marketing) with interleaved phases. The channel adapter framework (C1) is built first because it is a dependency for both Communications and Vertical automations.

| Phase | Stream | Description | Sessions | Cumulative |
|-------|--------|-------------|----------|------------|
| **C1** | Comms | Channel adapter framework + Telegram refactor | 1 | 1 |
| **C2** | Comms | WhatsApp + SMS via Twilio | 1-2 | 2-3 |
| **T1** | Terminal | PersistentTerminalSession (PTY) | 1 | 3-4 |
| **T2** | Terminal | EventBus + typed events | 1 | 4-5 |
| **M1** | Marketing | Core framework + brand voice + content workflow | 1-2 | 5-7 |
| **C3** | Comms | ElevenLabs TTS | 1 | 6-8 |
| **M2** | Marketing | Social media plugin (Ayrshare) | 2 | 8-10 |
| **T3** | Terminal | OrchestratorConductor (state machine) | 2 | 10-12 |
| **M3** | Marketing | Email marketing plugin (Mailchimp) | 1-2 | 11-14 |
| **C4** | Comms | Voice calls (Deepgram STT + pipeline) | 2-3 | 13-17 |
| **M4** | Marketing | SEO plugin + content optimizer | 1-2 | 14-19 |
| **T4** | Terminal | Workflow UI panel | 1-2 | 15-21 |
| **M5** | Marketing | Ads plugin (Google + Meta) | 2 | 17-23 |
| **T5** | Terminal | BLD:APP v2 integration | 1 | 18-24 |
| **M6** | Marketing | Marketing UI panel | 2-3 | 20-27 |
| **C5** | Comms | Cross-channel unification | 1 | 21-28 |
| **M7** | Marketing | Sub-agent marketing workflows | 1 | 22-29 |
| **V1** | Verticals | Vertical framework (base class + loader) | 2-3 | 24-32 |
| **V2** | Verticals | Cafe vertical (reference implementation) | 4-5 | 28-37 |
| **V3** | Verticals | Gym vertical (reference implementation) | 4-5 | 32-42 |

### 13.2 Estimated Totals by Stream

| Stream | New Files | New LOC | Sessions |
|--------|-----------|---------|----------|
| Terminal/Workflow | ~8 + workflow-ui | ~3,200 | 6-7 |
| Communications | ~12 + comms-ui | ~4,150 | 6-8 |
| Marketing | ~12 + marketing-ui | ~7,400 | 10-14 |
| Vertical Framework | ~6 | ~1,500 | 2-3 |
| Cafe Vertical | ~8 + cafe-ui | ~3,500 | 4-5 |
| Gym Vertical | ~8 + gym-ui | ~3,500 | 4-5 |
| **Total** | **~54 + 5 UIs** | **~23,250** | **32-42** |

### 13.3 Shared Infrastructure (Built Once, Used by All)

- `channels/base.py` — ChannelAdapter pattern (used by comms, extensible to marketing notifications)
- `core/event_bus.py` — Typed events (used by terminal, voice pipeline, marketing campaign events)
- `core/marketing/content.py` — Content workflow (used by marketing, applicable to any approval flow)
- `routers/channels.py` — Webhook framework (Twilio for comms, expandable for Ayrshare/Mailchimp webhooks)
- `verticals/base.py` — VerticalModule ABC (plugin + routes + UI + models + workflows + prompts)
- `verticals/loader.py` — Auto-discovery and loading of vertical modules

### 13.4 Vertical Implementation Sessions (Cafe)

| Session | Focus | Deliverables |
|---------|-------|-------------|
| Cafe-1 | Database + core tools | Tables created, menu and inventory tools working |
| Cafe-2 | Supplier management | Supplier registry, ordering schedules, automated order generation, approval via WhatsApp |
| Cafe-3 | Customer ordering | WhatsApp/voice order flow, order board, loyalty program |
| Cafe-4 | Reviews + operations | Review monitoring, brand-voice responses, daily operations workflows |
| Cafe-5 | UI | `/cafe` React app with all 8 pages |

### 13.5 Vertical Implementation Sessions (Gym)

| Session | Focus | Deliverables |
|---------|-------|-------------|
| Gym-1 | Database + core tools | Tables created, member management and attendance tools working |
| Gym-2 | Automation engine | Sequence trigger/delay/message pipeline, configurable sequences, new member onboarding |
| Gym-3 | Lead pipeline | Lead scoring, stages, conversion tracking, trial management workflow |
| Gym-4 | Retention engine | At-risk detection, milestone tracking, reactivation, challenge/block management, suspensions |
| Gym-5 | UI | `/gym` React app with all 9 pages |

---

## 14. Success Metrics

### 14.1 Platform-Level KPIs

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Agent response latency (p95)** | < 3s for text channels, < 1s TTFT for voice | Instrumented in AgentRunner |
| **Agent uptime** | 99.5% | Health endpoint monitoring |
| **Cross-channel conversation continuity** | 95% successful identity resolution | channel_identities match rate |
| **Tool execution success rate** | > 98% | Audit trail analysis |
| **Memory retrieval relevance** | > 85% user satisfaction on recalled facts | Periodic sampling |

### 14.2 Communications KPIs

| Metric | Target | Measurement |
|--------|--------|-------------|
| **WhatsApp message delivery rate** | > 99% | Twilio delivery callbacks |
| **Voice call completion rate** | > 90% (calls answered and resolved) | voice_calls table |
| **Voice TTFT (time to first TTS byte)** | < 800ms | Pipeline instrumentation |
| **STT accuracy** | > 95% word error rate | Deepgram analytics |
| **SMS delivery rate** | > 97% | Twilio delivery callbacks |

### 14.3 Marketing KPIs

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Content publish success rate** | > 99% | content_items status tracking |
| **Brand voice consistency** | > 90% (rated by owner/reviewer) | Approval rate in content workflow |
| **Social media post scheduling accuracy** | 100% posts published within 5 min of schedule | Ayrshare callback timestamps |
| **Email open rate** | Above industry average for vertical | Mailchimp analytics |
| **Campaign ROI tracking** | Automated attribution for > 80% of conversions | marketing_metrics + UTM tracking |

### 14.4 Vertical KPIs (Gym)

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Lead-to-trial conversion** | > 40% | gym_members lead_stage transitions |
| **Trial-to-member conversion** | > 30% | gym_members status transitions |
| **Automation sequence delivery rate** | > 99% | gym_comms_log delivery status |
| **At-risk member detection accuracy** | > 85% | At-risk flagged vs actual cancellations |
| **Retention improvement** | 10%+ improvement in 90-day retention | Baseline vs post-implementation |

### 14.5 Vertical KPIs (Cafe)

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Supplier order accuracy** | > 98% (items/quantities match approval) | cafe_supplier_orders audit |
| **Order-to-ready time** | < 15 min average | cafe_orders timestamps |
| **Customer WhatsApp order completion** | > 90% of started orders completed | cafe_orders by channel |
| **Review response time** | < 4 hours for new reviews | Review detection to response posting |
| **Inventory stockout incidents** | < 2 per month | cafe_inventory below-par alerts |

---

## 15. Risks and Mitigations

### 15.1 Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Twilio webhook reliability** | Missed WhatsApp/SMS messages | Low | Twilio retries 3x; implement idempotency keys; monitor delivery status callbacks |
| **Voice latency exceeds conversational threshold** | Unnatural voice calls | Medium | Default to Claude API (300ms TTFT); sentence-boundary TTS streaming; pre-warm model |
| **Ayrshare API rate limits or downtime** | Failed social media posts | Medium | Queue with retry; direct platform API fallback for critical posts; schedule buffer |
| **Ollama cold start during voice calls** | 5-10s silence on voice | High | Force Claude API for voice channel; keep Ollama warm with periodic pings |
| **Database table proliferation** | Schema complexity, migration difficulty | Medium | Vertical tables are self-contained; versioned migrations per vertical; automated schema diff |
| **Plugin tool count exceeds Ollama context** | Tool selection degradation | Medium | ToolSelector already filters to ~15 tools; vertical tools added to relevant categories |
| **Cross-channel identity resolution failures** | Fragmented conversations | Low | Phone number as primary key for WhatsApp/SMS/Voice; explicit pairing flow for Telegram/Web |

### 15.2 Business Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **External API pricing changes** | Increased operating costs | Medium | Abstract all integrations behind adapters; maintain alternative provider options |
| **Ayrshare discontinuation** | Social media capability loss | Low | Direct platform API adapters as backup (tweepy for Twitter, httpx for LinkedIn) |
| **WhatsApp Business API policy changes** | Template approval delays, messaging restrictions | Medium | Maintain template library; proactive template approval; fallback to SMS |
| **SMB customer churn** | Revenue loss | High | Proactive value demonstration via agent insights; sticky vertical-specific workflows |
| **Competitor catch-up** | Market share erosion | Medium | Rapid vertical expansion; cross-domain intelligence as moat; local-first privacy advantage |

### 15.3 Operational Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Agent sends incorrect supplier order** | Financial loss, operational disruption | Medium | Human approval gate for all orders above configurable threshold; undo within 5 minutes |
| **Agent auto-publishes inappropriate content** | Brand reputation damage | Low | Content approval workflow enforced; never auto-publish without explicit permission |
| **Agent sends wrong message to customer** | Customer confusion, brand damage | Low | Template-based messaging for automated sequences; personalization reviewed at template level |
| **Voice call agent misunderstands customer** | Wrong orders, frustrated customers | Medium | Confirmation step before finalizing any action; "Did I get that right?" verification |

---

## 16. Non-Functional Requirements

### 16.1 Performance

| Requirement | Target | Measurement |
|-------------|--------|-------------|
| Text channel response latency (p50) | < 2s | AgentRunner instrumentation |
| Text channel response latency (p95) | < 5s | AgentRunner instrumentation |
| Voice TTFT (time to first TTS byte) | < 800ms | VoicePipeline instrumentation |
| Voice end-to-end latency | < 2s from user speech end to TTS start | VoicePipeline instrumentation |
| Webhook processing time | < 200ms (excluding agent response) | Router instrumentation |
| RAG retrieval latency (p50) | < 50ms | Memory system instrumentation (currently 25ms) |
| UI initial load time | < 2s (Vite-optimized bundles) | Browser performance API |
| Database query latency (p95) | < 100ms | SQLAlchemy instrumentation |

### 16.2 Security

| Requirement | Implementation |
|-------------|---------------|
| Webhook signature validation | Twilio signature validation on all webhook endpoints |
| API key encryption | All external service credentials encrypted at rest via ConfigManager pattern |
| OAuth token storage | Platform connection tokens encrypted in `platform_connections` table |
| Tenant isolation | All database queries filtered by `org_id`; Redis keys namespaced by tenant |
| Input sanitization | All user input validated and sanitized before database insertion |
| Rate limiting | 60 calls/min per tool (existing); webhook endpoints rate-limited per source IP |
| HTTPS enforcement | All external API calls over TLS; Twilio webhooks require HTTPS |
| Audit logging | All tool calls, content approvals, and order placements logged with user, timestamp, and details |
| HIPAA awareness | Healthcare vertical: encrypted PHI fields, access logging, data retention policies (future) |

### 16.3 Scalability

| Requirement | Target | Approach |
|-------------|--------|----------|
| Concurrent voice calls | 10 simultaneous | asyncio-based pipeline; horizontal scaling via Redis clustering |
| WhatsApp messages per minute | 100 | Async webhook processing; message queue for burst handling |
| Social media posts per day | 50 across platforms | Ayrshare handles platform rate limits; internal queue with retry |
| Content items in review | 500 | Database-backed state machine; paginated API queries |
| Members per gym vertical | 10,000 | Indexed database queries; pagination on all list endpoints |
| Supplier orders per day | 50 | Async processing; approval queue |

### 16.4 Reliability

| Requirement | Target | Implementation |
|-------------|--------|----------------|
| Agent availability | 99.5% uptime | launchd daemon with auto-restart; health endpoint monitoring |
| Message delivery guarantee | At-least-once for all channels | Twilio delivery receipts; retry on failure; idempotency keys |
| Data durability | Zero data loss on crash | PostgreSQL WAL; transaction-based state changes |
| Graceful degradation | Core functionality maintained if external services fail | Agent responds via available channels; queues failed external calls for retry |
| Voice call failover | Graceful handoff if agent fails | TwiML fallback to voicemail or human transfer |
| Scheduled content delivery | Publish within 5 minutes of scheduled time | Background scheduler with missed-execution catchup |

### 16.5 Observability

| Requirement | Implementation |
|-------------|---------------|
| Structured logging | JSON logging with ContextVar request tracing (already implemented) |
| Metrics collection | Per-tool execution timing, per-channel message counts, per-campaign performance |
| Error tracking | Typed error classification with `classify_error()` (already implemented) |
| Event bus audit trail | All events persisted to `work_items` table |
| Health endpoints | `/health` (basic), `/admin/health` (detailed with model status, memory, external service connectivity) |
| Cost tracking | Per-channel Twilio costs, per-campaign ad spend, per-request model token costs |

---

*End of Product Requirements Document*
