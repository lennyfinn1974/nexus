# Nexus Feature Streams: Implementation Plan

**Three Feature Streams — Full Research → Architecture → Implementation**
**Created: Feb 18, 2026**

---

## Platform Architecture: Core + Verticals

Nexus is a **vertical SaaS platform** where one AI agent powers every business type. The platform has two layers:

### Layer 1: Core Services (licensed across all verticals)

These are industry-agnostic capabilities available to every Nexus customer:

| Core Service | Route | Purpose |
|-------------|-------|---------|
| **Chat UI** | `/` | Conversational interface (existing) |
| **Admin UI** | `/admin` | System config, models, API keys, licensing (existing) |
| **Workflow** | `/workflow` | Terminal orchestration, BLD:APP, agent task management |
| **Marketing** | `/marketing` | Campaign management, social, email, ads, SEO |
| **Comms** | `/comms` | Voice calls, WhatsApp, SMS, channel management |

### Layer 2: Industry Verticals (business-specific modules)

Each vertical is a dedicated panel with domain-specific tools, workflows, dashboards, and integrations:

| Vertical | Route | Target Business | Key Features |
|----------|-------|-----------------|--------------|
| **Café/Restaurant** | `/cafe` | Cafés, restaurants, bakeries | Menu management, ordering, reservations, inventory, supplier ordering, loyalty, reviews |
| **Gym/Fitness** | `/gym` | Gyms, studios, personal trainers | Membership management, class scheduling, attendance, workout plans, body tracking, billing |
| **Healthcare** | `/healthcare` | Clinics, practitioners, therapists | Appointment booking, patient intake, records (HIPAA-aware), treatment plans, referrals, billing |
| **Legal** | `/legal` | Law firms, solicitors, barristers | Matter management, time tracking, document assembly, conflict checks, court dates, billing |
| **Accounting** | `/accounting` | Accountants, bookkeepers, tax advisors | Client management, tax deadlines, document collection, lodgement tracking, advisory workflows |
| *(future)* | `/realestate` | Agents, property managers | Listings, inspections, tenant management, property reports |
| *(future)* | `/trades` | Plumbers, electricians, builders | Job scheduling, quoting, invoicing, compliance certificates |

### How Core + Verticals Interact

```
┌──────────────────────────────────────────────────────────────────┐
│                        THE NEXUS AGENT                           │
│   One AI • One Memory • All Tools • All Channels • All Context   │
└──────────────────────────┬───────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   ┌─────────────┐  ┌───────────┐  ┌─────────────┐
   │ CORE LAYER  │  │ CORE LAYER│  │ CORE LAYER  │
   │ Marketing   │  │ Comms     │  │ Workflow     │
   │ (all biz)   │  │ (all biz) │  │ (all biz)   │
   └──────┬──────┘  └─────┬─────┘  └──────┬──────┘
          │               │               │
   ┌──────┴───────────────┴───────────────┴──────┐
   │           VERTICAL MODULES                   │
   │  ┌──────┐ ┌─────┐ ┌──────────┐ ┌─────────┐ │
   │  │ Café │ │ Gym │ │Healthcare│ │  Legal   │ │
   │  └──────┘ └─────┘ └──────────┘ └─────────┘ │
   └─────────────────────────────────────────────┘
```

**Example: A Café using Nexus**
- **Core Marketing**: Agent manages the café's Instagram, creates posts with brand voice, runs Google Ads for local delivery
- **Core Comms**: WhatsApp for customer orders ("I'd like 2 flat whites for pickup at 10"), phone for reservations
- **Core Workflow**: Agent handles internal tasks, staff scheduling workflows
- **Vertical `/cafe`**: Menu builder, POS integration, supplier ordering, loyalty program, review management, health inspection checklist

**Example: A Law Firm using Nexus**
- **Core Marketing**: Agent manages LinkedIn presence, blog content for SEO, email newsletters
- **Core Comms**: Voice calls from clients routed through Nexus, WhatsApp for quick updates on matters
- **Core Workflow**: Document review workflows, deadline tracking
- **Vertical `/legal`**: Matter management, conflict checks, time tracking, court date calendar, document assembly, trust accounting

### Vertical Module Architecture

Each vertical is a self-contained package:

```
verticals/
  cafe/
    cafe_plugin.py        # NexusPlugin subclass — domain-specific tools
    models.py             # SQLAlchemy models (menus, orders, inventory, etc.)
    routes.py             # REST API endpoints for the vertical
    workflows.py          # Pre-built sub-agent workflows (e.g., "weekly supplier order")
    prompts.py            # Domain-specific system prompt additions
    ui/                   # React app (Vite + Radix + Tailwind 4)
      src/
        pages/
          dashboard.tsx   # Café-specific dashboard
          menu.tsx        # Menu management
          orders.tsx      # Order management
          inventory.tsx   # Stock levels, supplier ordering
          loyalty.tsx     # Customer loyalty program
```

Each vertical plugin:
1. **Registers domain tools** — `cafe__create_menu_item`, `cafe__take_order`, `cafe__check_inventory`
2. **Extends the system prompt** — "You are managing a café called {name}. You know the menu, opening hours, and can take orders."
3. **Adds DB tables** — via `ensure_tables()` in the plugin setup (same pattern as existing plugins)
4. **Provides pre-built workflows** — "Morning open" (check inventory, prep specials, post daily social), "End of day" (reconcile POS, place supplier orders, schedule tomorrow's social post)
5. **Has its own React UI** — served at the vertical's route prefix

### Licensing Integration

Maps directly to the licensing architecture in `docs/LICENSING_ARCHITECTURE.md`:

| Tier | Core Services | Verticals | Price |
|------|--------------|-----------|-------|
| **Free** | Chat + Admin (limited) | None | $0 |
| **Pro** | Chat + Admin + Marketing + Comms + Workflow | 1 vertical included | $49/mo |
| **Business** | All core (unlimited) | Up to 3 verticals | $149/mo |
| **Enterprise** | All core + clustering + SSO | Unlimited verticals + custom | Custom |

Feature gating in code:
```python
# In vertical plugin setup()
if not license.has_vertical("cafe"):
    raise VerticalNotLicensed("cafe")

# In core marketing plugin
if not license.has_feature("marketing"):
    raise FeatureNotLicensed("marketing")
```

Each new panel is a separate React app (like admin-ui) built with Vite + Radix UI + Tailwind 4, served by FastAPI at its route prefix. Config-level settings (API keys, provider selection) stay in Admin UI.

---

## Core Principle: Nexus Agent as Customer Point of Contact

**Every touchpoint runs through the Nexus agent.** The agent isn't a backend service — it IS the customer-facing intelligence. Whether someone sends a WhatsApp message, calls a phone number, asks for a marketing report, approves a social media post, or checks a workflow status, they're talking to the same Nexus agent with the same personality, memory, tools, and context.

### What This Means Architecturally

```
                    ┌─────────────────────────┐
                    │     The Nexus Agent      │
                    │  (AgentRunner + Memory   │
                    │   + KG + Tools + Skills) │
                    │                          │
                    │  One personality.         │
                    │  One memory.              │
                    │  All tools available.     │
                    │  All context shared.      │
                    └─────────┬───────────────┘
                              │
        ┌─────────┬───────────┼───────────┬──────────┐
        ▼         ▼           ▼           ▼          ▼
    WhatsApp   Voice Call   Chat UI    Marketing   Workflow
    Customer   Customer    Developer   Manager     Engineer
```

### Key Rules

1. **Single AgentRunner pipeline** — Every channel adapter normalizes to `ChannelMessage`, routes through `AgentRunner.run()`. The agent sees all tools (marketing, terminal, comms, social) regardless of channel. A WhatsApp customer can ask "what's the status of my campaign?" and get an answer because the agent has `ads_performance` and `social_analytics` tools.

2. **Unified memory across channels** — A conversation started on WhatsApp continues seamlessly on voice or web. The Knowledge Graph, RAG pipeline, and passive memory are shared. If the agent learns a customer's preferences on a phone call, it remembers them in WhatsApp.

3. **Channel-aware responses** — The agent knows which channel it's speaking through (via system prompt context) and adapts: concise for SMS, conversational for voice, rich Markdown for web, structured for WhatsApp (buttons/lists). But it's the same agent making the same decisions.

4. **Agent-driven UI panels** — The Marketing UI and Workflow UI aren't separate products. They're visual interfaces to what the agent already does. "Show me campaign performance" in chat produces the same data as the Marketing UI dashboard. The UIs are power-user views into the agent's capabilities.

5. **Agent handles customer-facing marketing** — When the marketing plugin posts to social media, monitors engagement, or sends email campaigns, the Nexus agent IS the marketer. It responds to social media comments with the brand voice. It handles email replies. It manages ad campaigns. The customer's experience of the brand comes through Nexus.

6. **Agent orchestrates terminal workflows** — When BLD:APP runs, the conductor IS the Nexus agent delegating to sub-agents. Status updates flow through the same WebSocket/WhatsApp/Telegram channels. A developer can ask "how's the build going?" on WhatsApp and get a real-time status from the conductor.

7. **Model routing per channel context** — Voice calls default to Claude API (300ms TTFT for natural conversation). Marketing content generation can use Claude for quality. Quick WhatsApp status checks use local Ollama. The agent picks the right model for the context, not the channel.

### Integration Points in Existing Code

- `agent_runner.py` → `build_system_prompt()` receives channel context: `"User is contacting via WhatsApp. Be concise, use interactive buttons for choices."`
- `tool_selector.py` → All marketing/comms/terminal tools available to all channels. Tool selection is intent-based, not channel-based.
- `passive_memory.py` → Learns from all channels: customer preferences, brand interactions, workflow patterns
- `work_registry.py` → Campaigns, calls, terminal sessions, social posts all appear on KanBan
- `sub_agent.py` → Marketing sub-agents (content writers, researchers) and terminal sub-agents (builders, reviewers) use the same orchestration

---

## Stream 1: Terminal Orchestration & Multi-Agent BLD:APP

### What Exists Today
- `terminal_plugin.py`: Terminal.app control (osascript), tmux session management, Claude Code interactive sessions, `claude_multi_agent` tool (up to 5 parallel agents)
- `sovereign_plugin.py`: BLD:APP procedure (creates 4 tmux sessions, starts server/dev/logs/work), BLD:DEV, BLD:TEST, BLD:STOP, SYS:STATUS
- `sub_agent.py`: SubAgentOrchestrator with 5 roles (Builder/Reviewer/Researcher/Verifier/Synthesizer), topological dependency layers, parallel execution, WebSocket progress streaming
- `work_registry.py`: Unified tracking for all work items, SSE streaming to admin KanBan

### What We're Building
A conductor-driven multi-agent development system with full observability.

### Architecture

```
User Request ("build feature X")
    │
    ▼
┌─────────────────────────┐
│   OrchestratorConductor │  ← State machine: PLAN→RESEARCH→BUILD→REVIEW→FIX→TEST→DONE
│   (core/conductor.py)   │  ← Reactive loops (review fails → re-enter BUILD)
└────────┬────────────────┘
         │ dispatches
    ┌────┴────┬────────────┬──────────────┐
    ▼         ▼            ▼              ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│Research│ │Builder │ │Reviewer  │ │ Tester   │
│ Agent  │ │ Agent  │ │ Agent    │ │ Agent    │
└───┬────┘ └───┬────┘ └────┬─────┘ └────┬─────┘
    │          │           │             │
    ▼          ▼           ▼             ▼
┌──────────────────────────────────────────────┐
│        PersistentTerminalSession (PTY)       │
│  Each agent owns a named shell session       │
│  with working dir, env vars, history         │
└──────────────────┬───────────────────────────┘
                   │ all events
                   ▼
┌──────────────────────────────────────────────┐
│              EventBus (asyncio.Queue)         │
│  Types: terminal_command, terminal_output,    │
│  agent_decision, git_event, phase_change     │
└─────┬──────────┬──────────┬──────────────────┘
      │          │          │
      ▼          ▼          ▼
  WorkRegistry  WebSocket  Metrics
  (KanBan)     (Chat UI)  (Dashboard)
```

### New Files

| File | Purpose | ~LOC |
|------|---------|------|
| `core/terminal_session.py` | PersistentShell using `pty.openpty()` + asyncio event loop | ~300 |
| `core/event_bus.py` | Typed event bus (asyncio.Queue, typed dataclasses) | ~200 |
| `core/conductor.py` | State machine orchestrator with reactive loops | ~500 |
| `core/git_coordinator.py` | Branch-per-agent strategy, merge as approval | ~200 |
| `workflow-ui/` | React app for orchestration monitoring | ~2000 |

### Modified Files
- `sub_agent.py` — Add conductor loop, reactive phases, retry on review failure
- `sovereign_plugin.py` — BLD:APP delegates to conductor instead of raw tmux
- `terminal_plugin.py` — Add persistent session management via PersistentShell
- `work_registry.py` — New event types: terminal_command, agent_decision, phase_change
- `app.py` — Initialize event bus, conductor, serve workflow-ui

### Implementation Phases

**Phase T1: PersistentTerminalSession (1 session)**
- `pty.openpty()` with asyncio `loop.add_reader()` for non-blocking I/O
- ANSI stripping for agent context, raw preservation for UI viewer
- Working directory tracking, environment variable capture
- Session lifecycle: create, execute, read, destroy
- `libtmux` integration for visible layout alongside programmatic control

**Phase T2: EventBus + Typed Events (1 session)**
- Typed event dataclasses: TerminalCommand, TerminalOutput, AgentDecision, GitEvent, PhaseChange
- asyncio.Queue-based bus with subscriber pattern
- Subscribers: WorkRegistry writer, WebSocket broadcaster, log writer, metrics collector
- Event persistence to `work_items` table for audit trail

**Phase T3: OrchestratorConductor (2 sessions)**
- State machine: PLANNING → RESEARCHING → BUILDING → REVIEWING → FIXING → TESTING → COMPLETE
- Reactive transitions: Reviewer score < 7 → re-enter BUILDING with feedback
- Agent dispatch via existing SubAgentOrchestrator (extend, don't replace)
- Git branch coordination: `feature/builder-{task_id}`, merge on approval
- Conductor uses EventBus to publish phase changes and decisions
- Max 3 build-review cycles before escalating to user

**Phase T4: Workflow UI Panel (1-2 sessions)**
- React app at `/workflow` (Vite + Radix + Tailwind 4)
- Live terminal viewer per agent (xterm.js component)
- Orchestration timeline: phase transitions with dependency arrows
- Agent status cards with token usage, command count, duration
- Git diff viewer for reviewing agent changes
- One-click approve/reject/retry controls

**Phase T5: BLD:APP v2 Integration (1 session)**
- Sovereign plugin BLD:APP upgraded to use conductor
- Chat UI orchestration panel shows conductor state
- `/workflow` command opens Workflow UI
- Metrics: orchestration.duration, agents_per_run, review_cycles, success_rate

### Dependencies
```
pip3 install libtmux xterm-js-python  # (xterm.js is frontend npm)
```

---

## Stream 2: WhatsApp, Twilio & ElevenLabs Communications

### What Exists Today
- `telegram/message_processor.py`: TelegramChannel with pairing, command handlers, message routing to AgentRunner
- WebSocket chat UI with streaming
- Plugin system for adding new tools

### What We're Building
Unified multi-channel communications: WhatsApp, SMS, Voice calls with AI-powered TTS/STT.

### Architecture

```
                    ┌─────────────┐
                    │   Channels   │
                    │   Router     │
                    │ /api/channels│
                    └──────┬──────┘
                           │
        ┌──────────┬───────┼───────┬──────────┐
        ▼          ▼       ▼       ▼          ▼
  ┌──────────┐ ┌────────┐ ┌────┐ ┌─────┐ ┌────────┐
  │ Telegram │ │WhatsApp│ │SMS │ │Voice│ │WebSocket│
  │ Adapter  │ │Adapter │ │Adpt│ │Adpt │ │(existing)│
  └────┬─────┘ └───┬────┘ └──┬─┘ └──┬──┘ └───┬────┘
       │           │         │      │         │
       └───────────┴────┬────┴──────┘         │
                        ▼                     │
              ┌──────────────────┐            │
              │  ChannelMessage  │            │
              │  (normalized)    │            │
              └────────┬─────────┘            │
                       ▼                      │
              ┌──────────────────┐            │
              │  AgentRunner     │◄───────────┘
              │  (existing)      │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │ ResponseFormatter│
              │ (per-channel)    │
              └──────────────────┘

Voice Pipeline (real-time):
  Caller → Twilio Media Streams → WebSocket → VAD → Deepgram STT
                                                         │
                                                    AgentRunner
                                                         │
                                               ElevenLabs TTS (streaming)
                                                         │
                                            WebSocket → Twilio → Caller
```

### Key Design Decisions

1. **Twilio as single provider** for WhatsApp + SMS + Voice. One SDK, one billing, one webhook format.
2. **Deepgram for STT** ($0.0043/min, mulaw 8kHz native — zero audio conversion)
3. **ElevenLabs for TTS** (`eleven_turbo_v2_5` for voice calls, `eleven_multilingual_v2` for pre-recorded)
4. **ChannelAdapter base class** — every channel normalizes to `ChannelMessage` dataclass, routes through same AgentRunner
5. **Voice defaults to Claude API** — Ollama cold TTFT (5-10s) is fatal for conversation; Claude TTFT ~300ms
6. **The Nexus agent answers every call and message** — Not a dumb IVR or chatbot. The full agent with all tools (including marketing, terminal, search) handles every interaction. A WhatsApp customer can ask for a report, trigger a workflow, or get brand information — same capabilities as the web chat.

### New Files

| File | Purpose | ~LOC |
|------|---------|------|
| `channels/base.py` | ChannelAdapter ABC, ChannelMessage dataclass, ResponseFormatter | ~200 |
| `channels/whatsapp.py` | Twilio WhatsApp adapter (webhook receive, send, media handling) | ~300 |
| `channels/sms.py` | Twilio SMS adapter | ~150 |
| `channels/voice.py` | Twilio voice adapter (TwiML, Media Streams WebSocket) | ~400 |
| `channels/telegram_adapter.py` | Refactor existing TelegramChannel to ChannelAdapter interface | ~250 |
| `voice/stt.py` | Deepgram streaming STT + local Whisper fallback | ~250 |
| `voice/tts.py` | ElevenLabs wrapper (HTTP streaming + WebSocket for real-time) | ~300 |
| `voice/vad.py` | WebRTC VAD wrapper for interruption detection | ~100 |
| `voice/pipeline.py` | VoicePipeline orchestrator (STT→Agent→TTS with interruption) | ~400 |
| `routers/channels.py` | Webhook endpoints for Twilio (WhatsApp, SMS, Voice) | ~300 |
| `core/response_formatter.py` | Per-channel output formatting (Markdown→plain, length limits) | ~200 |
| `comms-ui/` | React app for channel management and voice call dashboard | ~1500 |

### Database Changes
```sql
-- Channel identity linking (cross-channel conversation continuity)
CREATE TABLE channel_identities (
    id SERIAL PRIMARY KEY,
    nexus_user_id UUID NOT NULL,
    channel VARCHAR(20) NOT NULL,        -- 'telegram', 'whatsapp', 'sms', 'voice'
    channel_user_id VARCHAR(100) NOT NULL,
    display_name VARCHAR(100),
    paired_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(channel, channel_user_id)
);

-- Voice call records
CREATE TABLE voice_calls (
    id SERIAL PRIMARY KEY,
    call_sid VARCHAR(50) UNIQUE,
    conv_id UUID,
    direction VARCHAR(10),               -- 'inbound', 'outbound'
    status VARCHAR(20),
    duration_seconds INTEGER,
    stt_provider VARCHAR(20),
    tts_chars INTEGER,
    cost_usd DECIMAL(8,4),
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Implementation Phases

**Phase C1: Channel Adapter Framework (1 session)**
- ChannelAdapter ABC, ChannelMessage/MediaAttachment dataclasses
- ResponseFormatter with per-channel output shaping
- Refactor TelegramChannel to new interface (backward compatible)
- `channel_identities` DB table + cross-channel user linking
- Channel context in system prompt ("User is on WhatsApp — be concise")

**Phase C2: WhatsApp + SMS (1-2 sessions)**
- Twilio webhook router at `/api/channels/twilio/webhook`
- Webhook signature validation (`twilio.request_validator`)
- WhatsApp adapter: text messages, media (images/docs/audio), interactive buttons
- WhatsApp voice messages: transcribe via Deepgram before routing to agent
- SMS adapter: text-only, aggressive brevity mode
- Admin UI: Twilio Account SID, Auth Token, Phone Number config
- ngrok/tunnel setup for local development

**Phase C3: ElevenLabs TTS (1 session)**
- TTS wrapper: HTTP streaming for pre-recorded, WebSocket for real-time
- Voice selection and cloning configuration
- WhatsApp audio message responses (generate audio → send as media)
- New tool: `tts_speak` — any channel can trigger TTS output
- Admin UI: ElevenLabs API key, voice selection, model selection

**Phase C4: Voice Calls (2-3 sessions)**
- Deepgram streaming STT with mulaw 8kHz native input
- WebRTC VAD for speech activity detection
- VoicePipeline: STT → AgentRunner → TTS with sentence-boundary streaming
- Interruption handling: VAD detects user speech → clear Twilio buffer → abort agent → new STT session
- Twilio Media Streams WebSocket at `/api/voice/stream`
- TwiML response generation for call control
- Voice routing: Claude API by default (300ms TTFT vs 5s Ollama cold)
- Comms UI: live call dashboard, call history, transcript viewer

**Phase C5: Cross-Channel Unification (1 session)**
- Conversation continuity: same user across WhatsApp/Telegram/Web shares conversation
- Unified message log in Admin UI
- Per-channel cost tracking and analytics
- Channel preference learning (passive memory: "user prefers WhatsApp for quick questions")

### Dependencies & Costs
```
pip3 install twilio elevenlabs deepgram-sdk webrtcvad
```

| Service | Estimated Monthly Cost |
|---------|----------------------|
| Twilio (1 number + WhatsApp) | $15-40 |
| ElevenLabs (Creator plan) | $22 |
| Deepgram (voice minutes) | $5-15 |
| **Total** | **$42-77/month** |

---

## Stream 3: Marketing Agency Automation

### What Exists Today
- Brave plugin with web search and headless browser (market research capable)
- Sub-agent orchestration (parallel research, build-review patterns)
- Knowledge graph + RAG for persistent brand/competitor intelligence
- Work registry + KanBan for campaign tracking

### What We're Building
Full-service AI marketing agency: strategy → content → distribution → analytics.

### Architecture

```
┌──────────────────────────────────────────────────┐
│                 Marketing UI (/marketing)          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────┐│
│  │ Campaign  │ │ Content  │ │ Social   │ │Report││
│  │ Planner   │ │ Calendar │ │ Feeds    │ │ Hub  ││
│  └──────────┘ └──────────┘ └──────────┘ └──────┘│
└──────────────────────┬───────────────────────────┘
                       │ REST API
                       ▼
┌──────────────────────────────────────────────────┐
│              core/marketing/ (shared)              │
│  BrandVoice │ ContentWorkflow │ UTMBuilder │ Attr │
└──────────────────────┬───────────────────────────┘
                       │
        ┌──────────────┼──────────────┬──────────────┐
        ▼              ▼              ▼              ▼
  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │  Social  │  │  Email   │  │   Ads    │  │   SEO    │
  │  Plugin  │  │  Plugin  │  │  Plugin  │  │  Plugin  │
  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
   Ayrshare      Mailchimp      Google Ads     Search Console
   (+ tweepy)    SendGrid       Meta Ads       Ahrefs/SEMrush
                 Resend         LinkedIn Ads
```

### Key Design Decisions

1. **Ayrshare for social media** ($99/mo) — one API for Twitter/X, LinkedIn, Instagram, Facebook, TikTok, Pinterest. Handles OAuth internally.
2. **Mailchimp for email marketing** (free to $20/mo) — full campaign API, automations, A/B testing
3. **Google Ads + Meta Marketing APIs** — direct integration for advertising (too critical for middleware)
4. **Built-in SEO content optimizer** — analyze top-10 SERPs via existing web_fetch + LLM scoring. Competitive advantage vs paid tools.
5. **Content approval workflow** — AI generates, human approves. Never auto-publish without explicit permission.
6. **Brand voice profiles** — stored in PostgreSQL, enforced on all content generation
7. **Nexus agent IS the marketing agency** — The agent doesn't just have marketing tools — it proactively manages campaigns, responds to social media engagement with the brand voice, drafts email sequences, monitors ad performance, and surfaces recommendations. Ask it "how are our LinkedIn ads performing?" on any channel and it pulls real data. Ask it "draft next week's social calendar" and it produces platform-specific content aligned to the brand profile. The Marketing UI is a visual dashboard into the agent's marketing activity, not a separate product.
8. **Social engagement through the agent** — When someone comments on a social post, the agent can auto-draft a brand-voice response (human approval before posting). The agent monitors mentions, sentiment, and trends — surfacing insights proactively via WhatsApp/Telegram/web notifications.

### New Files

| File | Purpose | ~LOC |
|------|---------|------|
| `core/marketing/brand.py` | Brand voice profiles, tone enforcement, vocabulary rules | ~200 |
| `core/marketing/content.py` | Content workflow state machine (DRAFT→REVIEW→APPROVED→SCHEDULED→PUBLISHED) | ~300 |
| `core/marketing/campaign.py` | Campaign planner, budget allocation, calendar management | ~300 |
| `core/marketing/attribution.py` | Multi-touch attribution (5 models), UTM builder | ~250 |
| `core/marketing/seo_engine.py` | SERP analysis, content scoring, keyword clustering | ~400 |
| `plugins/social_media_plugin.py` | Ayrshare integration + direct Twitter/X adapter | ~400 |
| `plugins/email_marketing_plugin.py` | Mailchimp + SendGrid adapters | ~350 |
| `plugins/ads_plugin.py` | Google Ads + Meta Marketing API integration | ~500 |
| `plugins/seo_plugin.py` | Search Console + Ahrefs/SEMrush + built-in optimizer | ~400 |
| `routers/marketing.py` | Marketing REST API endpoints | ~300 |
| `marketing-ui/` | React app for marketing dashboard | ~3000 |

### Database Changes
```sql
-- Brand voice profiles
CREATE TABLE brand_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    tone VARCHAR(50),                    -- 'professional', 'casual', 'bold', etc.
    vocabulary_rules JSONB,              -- include/exclude word lists
    examples JSONB,                      -- sample posts per platform
    platform_guidelines JSONB,           -- per-platform formatting rules
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Content items (posts, emails, ads)
CREATE TABLE content_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID REFERENCES campaigns(id),
    content_type VARCHAR(30),            -- 'social_post', 'email', 'ad_copy', 'blog', 'landing_page'
    platform VARCHAR(30),
    status VARCHAR(20) DEFAULT 'draft',  -- draft, review, approved, scheduled, published, failed
    title VARCHAR(200),
    body TEXT,
    media_urls JSONB,
    scheduled_at TIMESTAMP,
    published_at TIMESTAMP,
    external_id VARCHAR(100),            -- platform's post ID after publishing
    metrics JSONB,                       -- engagement metrics post-publish
    brand_profile_id INTEGER REFERENCES brand_profiles(id),
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Marketing campaigns
CREATE TABLE campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    status VARCHAR(20) DEFAULT 'planning', -- planning, active, paused, completed
    campaign_type VARCHAR(30),           -- 'social', 'email', 'ads', 'seo', 'multi'
    budget_usd DECIMAL(10,2),
    start_date DATE,
    end_date DATE,
    goals JSONB,                         -- target metrics
    strategy TEXT,                        -- AI-generated strategy document
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Calendar events (unified content calendar)
CREATE TABLE calendar_events (
    id SERIAL PRIMARY KEY,
    campaign_id UUID REFERENCES campaigns(id),
    content_item_id UUID REFERENCES content_items(id),
    event_type VARCHAR(20),              -- 'publish', 'review', 'deadline', 'report'
    scheduled_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    org_id UUID
);

-- Marketing metrics (time-series)
CREATE TABLE marketing_metrics (
    id SERIAL PRIMARY KEY,
    source VARCHAR(30),                  -- 'twitter', 'google_ads', 'mailchimp', etc.
    metric_name VARCHAR(50),             -- 'impressions', 'clicks', 'conversions', etc.
    metric_value DECIMAL(12,4),
    dimensions JSONB,                    -- campaign_id, content_id, keyword, etc.
    recorded_at TIMESTAMP NOT NULL,
    org_id UUID
);

-- Platform connections (encrypted OAuth tokens)
CREATE TABLE platform_connections (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(30) NOT NULL,
    account_name VARCHAR(100),
    credentials_encrypted TEXT,          -- encrypted via ConfigManager pattern
    scopes JSONB,
    status VARCHAR(20) DEFAULT 'active',
    org_id UUID,
    connected_at TIMESTAMP DEFAULT NOW()
);
```

### Implementation Phases

**Phase M1: Core Marketing Framework (1-2 sessions)**
- `core/marketing/` module: brand profiles, content workflow, campaign model
- Database tables + migrations
- Content approval state machine (DRAFT→REVIEW→APPROVED→SCHEDULED→PUBLISHED)
- Brand voice enforcement on all LLM content generation
- Marketing REST API in `routers/marketing.py`

**Phase M2: Social Media Plugin (2 sessions)**
- Ayrshare integration: post, schedule, analytics, monitor engagement
- Direct Twitter/X adapter via `tweepy` for advanced features
- Tools: `social_post`, `social_schedule`, `social_analytics`, `social_monitor`, `social_reply`, `social_trending`
- Platform connection management in Admin UI
- Content preview per platform (character limits, image requirements)

**Phase M3: Email Marketing Plugin (1-2 sessions)**
- Mailchimp adapter: campaigns, lists, templates, automations, analytics
- SendGrid adapter: transactional email
- Tools: `email_create_campaign`, `email_set_content`, `email_schedule`, `email_analytics`, `email_list_manage`, `email_ab_test`
- Email template generation with brand voice
- A/B test setup and winner selection

**Phase M4: SEO Plugin + Content Optimizer (1-2 sessions)**
- Google Search Console integration
- Built-in SERP analysis: fetch top-10 results for keyword, extract content patterns
- Content scoring: compare user content against competitor patterns via LLM
- Keyword clustering and topic mapping
- Tools: `seo_keyword_research`, `seo_site_audit`, `seo_content_optimize`, `seo_rank_check`, `seo_serp_analysis`

**Phase M5: Advertising Plugin (2 sessions)**
- Google Ads API: campaign CRUD, keyword management, bid strategies, reporting (GAQL)
- Meta Marketing API: campaign CRUD, audience management, CAPI, reporting
- Tools: `ads_create_campaign`, `ads_manage_budget`, `ads_performance`, `ads_keywords`, `ads_audiences`, `ads_recommendations`
- Budget guardrails (max daily spend, approval for increases)

**Phase M6: Marketing UI Panel (2-3 sessions)**
- React app at `/marketing` (Vite + Radix + Tailwind 4)
- Campaign planner dashboard
- Content calendar (drag-and-drop scheduling)
- Social media feed preview (multi-platform)
- Analytics dashboard: cross-channel metrics, attribution, ROI
- Content approval queue with one-click approve/reject

**Phase M7: Sub-Agent Marketing Workflows (1 session)**
- Campaign launch pattern: 2 researchers → 3 writers → 1 synthesizer
- Competitor analysis: N researchers (one per competitor) → synthesizer
- A/B content generation: 2 builders (different prompts/models) → 1 reviewer comparing
- Monthly report pattern: N data collectors → 1 report writer → review
- All workflows register in WorkRegistry for KanBan visibility

### Dependencies & Costs
```
pip3 install social-post-api mailchimp-marketing sendgrid google-ads facebook-business tweepy
```

| Service | Estimated Monthly Cost |
|---------|----------------------|
| Ayrshare (Business plan) | $99 |
| Mailchimp (Standard) | $0-20 |
| Google Ads API | Free (ad spend separate) |
| Meta Marketing API | Free (ad spend separate) |
| Search Console | Free |
| Ahrefs/SEMrush (optional) | $99-130 |
| **Total (excl. ad spend)** | **$99-249/month** |

---

## Unified Implementation Roadmap

### Priority Order (recommended)

| Phase | Stream | What | Sessions | Cumulative |
|-------|--------|------|----------|------------|
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

### Total Estimates

| Stream | New Files | New LOC | Sessions |
|--------|-----------|---------|----------|
| Terminal/Workflow | ~8 + UI | ~3,200 | 6-7 |
| Communications | ~12 + UI | ~4,150 | 6-8 |
| Marketing | ~12 + UI | ~7,400 | 10-14 |
| Vertical Framework | ~6 | ~1,500 | 2-3 |
| **Total (core)** | **~38 + 3 UIs** | **~16,250** | **24-32** |

Each vertical module (café, gym, legal, etc.) is an additional ~2,000-4,000 LOC + UI, built on the framework.

### Shared Infrastructure (built once, used by all)

- `channels/base.py` — ChannelAdapter pattern (used by comms, extensible to marketing notifications)
- `core/event_bus.py` — Typed events (used by terminal, comms voice pipeline, marketing campaign events)
- `core/marketing/content.py` — Content workflow (used by marketing, but also applicable to any approval flow)
- `routers/channels.py` — Webhook framework (Twilio for comms, expandable for Ayrshare/Mailchimp webhooks)
- `verticals/base.py` — VerticalModule ABC (plugin + routes + UI + models + workflows + prompts)
- `core/vertical_loader.py` — Auto-discovery and loading of vertical modules (same pattern as plugin manager)

### Vertical Module Framework

Built once, enables rapid development of industry verticals:

```
verticals/
  base.py                    # VerticalModule ABC
  loader.py                  # Auto-discovery, license gating, route mounting
  cafe/                      # One directory per vertical
    __init__.py
    plugin.py                # NexusPlugin subclass — domain tools
    models.py                # SQLAlchemy models
    routes.py                # REST API
    workflows.py             # Pre-built sub-agent workflows
    prompts.py               # System prompt extensions
    ui/                      # React app
  gym/
    ...
  healthcare/
    ...
```

**Phase V1: Vertical Framework (2-3 sessions)**
- `VerticalModule` base class: plugin, routes, models, workflows, prompts, UI path
- Vertical loader with auto-discovery + license gating
- Route mounting in FastAPI (dynamic, based on active verticals)
- System prompt injection from active vertical
- DB table auto-creation per vertical (same pattern as `ensure_org_id_columns()`)

**Phase V2: First Vertical — Café (3-4 sessions)**
- Proof of concept: full café module with all components
- Tools: `cafe__menu`, `cafe__order`, `cafe__inventory`, `cafe__reservations`, `cafe__reviews`, `cafe__loyalty`
- Pre-built workflows: morning open, end of day, weekly supplier order, monthly review response
- React UI: dashboard, menu editor, orders, inventory, loyalty
- Integration with Core Marketing (social posts about daily specials) and Core Comms (WhatsApp ordering)

**Phase V3+: Additional Verticals (3-4 sessions each)**
- Each vertical follows the established framework pattern
- Gym, Healthcare, Legal, Accounting — prioritized by market demand

---

## Vertical Deep-Dive: Gym/Fitness (`/gym`)

This is the reference specification for how detailed a vertical needs to be. Every vertical should be built to this level — not "generic gym management" but the actual automations that replace a front desk manager, a marketing person, and a retention specialist.

### Automation Sequences (Core Comms Integration)

The gym vertical is primarily an **automated messaging engine** powered by the Nexus agent. Every sequence below runs through Core Comms (SMS via Twilio, email via Mailchimp/SendGrid) with the agent making intelligent decisions about timing, content, and escalation.

#### 1. New Leads Pipeline

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| New profile/website signup | Instant welcome + trial booking CTA | SMS + Email | Immediate |
| Website chatbot interaction | Agent books trial via conversational flow | WhatsApp/Web chat | Real-time |
| Trial booked | Booking confirmation + what to expect | SMS + Email | Immediate |
| First session completed | Check-in: "How was your first session?" | SMS | 2 hours after |
| No response to initial outreach | Follow-up sequence | SMS | Day 1, 3, 7 |
| Lead scoring | Agent scores hot/warm/cold based on engagement signals | Internal | Continuous |

**Lead Scoring System** — The agent maintains a lead score per contact:
- +10: Opened email
- +20: Clicked link
- +30: Visited pricing page (tracked via UTM)
- +50: Booked trial
- +100: Attended trial
- -10/day: No engagement decay
- Hot (>80), Warm (40-80), Cold (<40)
- Agent adjusts outreach cadence and tone based on score

#### 2. Trials Management

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| Trial booked | Reminder with venue/parking/what to wear | SMS | 24h before |
| Trial day | Final reminder | SMS | 2h before |
| No-show | "We missed you! Let's reschedule" | SMS | 30 min after |
| Late cancellation | Understanding message + rebook CTA | SMS | Immediate |
| Mid-trial (multi-session trial) | Progress check-in | SMS | Midpoint |
| Trial completed | Post-trial survey + membership CTA | SMS + Email | 1h after |
| Trial → no signup (Day 1) | "Any questions about membership?" | SMS | Next day |
| Trial → no signup (Day 3) | Special offer or benefit reminder | SMS | Day 3 |
| Trial → no signup (Day 7) | Final personal outreach | SMS | Day 7 |

#### 3. Member Retention

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| No attendance in X days | "We miss you!" check-in (configurable: 7/14/21 days) | SMS | Configurable |
| Milestone: 50th/100th/200th session | Celebration message + share prompt | SMS + Email | After session |
| Birthday | Birthday greeting + special offer | SMS | Morning of |
| No-show/late cancel | Understanding follow-up | SMS | 30 min after |
| Monthly check-in | "How are you tracking toward your goals?" | SMS | Monthly (configurable day) |
| Quarterly feedback | NPS survey + "anything we can improve?" | SMS + Email | Quarterly |
| Google review prompt | "Loving your results? Leave us a review!" | SMS | After milestone or positive check-in response |

#### 4. Cancellations & Reactivation

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| Cancellation request | Retention conversation (agent asks why, offers alternatives) | SMS/WhatsApp/Voice | Immediate |
| Member cancelled | "We're sorry to see you go" + door-open message | Email | Day of |
| 30 days post-cancel | Reactivation offer | SMS | Day 30 |
| 90 days post-cancel | "We'd love to have you back" + new program info | SMS + Email | Day 90 |
| Cold leads (>60 days inactive) | Reactivation sequence | SMS | Automated |
| Past trial (never signed up, >30 days) | "Things have changed" + new offering | SMS | Day 30, 60, 90 |

#### 5. Suspended Members

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| Suspension starting | Confirmation + "see you when you're back" | SMS | Day of |
| Long-term suspension check-in (injury/pregnancy) | Caring check-in, no pressure | SMS | Monthly |
| 3 days before suspension lifts | "You're almost back! Here's what's happening this week" | SMS | 3 days before |
| Suspension lifted | Welcome back + class schedule | SMS + Email | Day of |

#### 6. Challenge Periods & Block Changes

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| Challenge announced | Sign-up prompt with details | SMS + Social | Launch day |
| Challenge cutoff approaching | "Last chance to sign up" | SMS | 3 days before |
| Challenge in progress | Fortnightly check-in + encouragement | SMS | Every 2 weeks |
| Challenge completed | Results celebration + share prompt | SMS + Email + Social | Day of |
| New training block starting | Block preview: "Here's what's coming" — aligned with BFT calendar/annual calendar, main lifts, flow notes | SMS + Email | 1 week before |
| Block changeover day | "New block starts today!" + what to expect | SMS | Morning of |

#### 7. Social Media Automation (Core Marketing Integration)

| Trigger | Action | Platform | Timing |
|---------|--------|----------|--------|
| New Instagram follower | Automated DM: "Welcome! Keen to try a session?" (ManyChat-style) | Instagram DM | Immediate |
| DM conversation → lead | Agent captures details, books trial via DM flow | Instagram DM | Real-time |
| New follower shows interest | Lead flow: DM → capture name/email → book trial → SMS confirmation | Instagram → SMS | Real-time |
| Challenge content needed | Auto-generate challenge promo posts/reels with Canva templates | Instagram/Facebook | Scheduled |
| Member milestone | Agent drafts celebration post (with permission) | Instagram/Facebook | After milestone |
| Weekly content calendar | Agent generates 5-7 posts aligned to block/challenge schedule | All platforms | Weekly |

#### 8. New Member Onboarding

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| Membership activated | Welcome message + essentials (app download, parking, schedule) | SMS + Email | Immediate |
| First day | "Welcome to the family!" + link to Facebook group | SMS | After first session |
| 5th session completed | Goal-setting check-in: "Now you're in the groove — what are your targets?" | SMS | After 5th session |
| 30 days in | Survey: "How's your first month been?" + Google review prompt | SMS + Email | Day 30 |

### Gym Vertical Tools

```python
# Member management
gym__add_member          # Create new member with profile, plan, start date
gym__update_member       # Update status, plan, contact details
gym__member_search       # Find member by name, email, phone, status
gym__member_profile      # Full member view: attendance, score, comms history

# Attendance & scheduling
gym__check_attendance    # Query attendance for member/class/date range
gym__class_schedule      # View/manage class timetable
gym__book_trial          # Book a trial session for a lead
gym__record_attendance   # Mark member as attended/no-show

# Lead management
gym__add_lead            # Create lead from any source (web, social, walk-in)
gym__score_lead          # Calculate/update lead score
gym__lead_pipeline       # View leads by stage (new, trial booked, trial complete, etc.)

# Retention & engagement
gym__member_milestones   # Check approaching milestones (50th session, birthday, etc.)
gym__at_risk_members     # Members with declining attendance or approaching cancel
gym__send_checkin        # Trigger a personalised check-in message
gym__survey_results      # View NPS and feedback data

# Challenges & blocks
gym__active_challenges   # Current and upcoming challenges
gym__challenge_signup    # Register member for a challenge
gym__block_schedule      # Current/upcoming training blocks with program details
gym__block_notify        # Trigger block change notifications

# Cancellations & suspensions
gym__process_cancellation  # Handle cancellation with retention conversation
gym__suspend_member        # Apply suspension with return date
gym__reactivation_queue    # Members eligible for reactivation outreach

# Reporting
gym__daily_summary       # Today's attendance, signups, cancellations, revenue
gym__retention_report    # Churn rate, at-risk count, reactivation success
gym__lead_report         # Pipeline conversion rates, source attribution
```

### Gym Database Tables

```sql
-- Members
CREATE TABLE gym_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    email VARCHAR(200),
    phone VARCHAR(30),
    status VARCHAR(20) DEFAULT 'active',     -- lead, trial, active, suspended, cancelled, past
    membership_plan VARCHAR(50),
    start_date DATE,
    end_date DATE,
    lead_score INTEGER DEFAULT 0,
    lead_source VARCHAR(50),                 -- 'website', 'instagram', 'walk_in', 'referral'
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
    created_at TIMESTAMP DEFAULT NOW()
);

-- Attendance records
CREATE TABLE gym_attendance (
    id SERIAL PRIMARY KEY,
    member_id UUID REFERENCES gym_members(id),
    class_name VARCHAR(100),
    attended BOOLEAN DEFAULT TRUE,           -- false = no-show
    late_cancel BOOLEAN DEFAULT FALSE,
    session_date TIMESTAMP NOT NULL,
    org_id UUID
);

-- Communication log (every SMS/email/call the agent sends)
CREATE TABLE gym_comms_log (
    id SERIAL PRIMARY KEY,
    member_id UUID REFERENCES gym_members(id),
    channel VARCHAR(20),                     -- 'sms', 'email', 'whatsapp', 'voice', 'instagram_dm'
    sequence_name VARCHAR(50),               -- 'trial_reminder', 'retention_checkin', 'reactivation', etc.
    message_content TEXT,
    sent_at TIMESTAMP DEFAULT NOW(),
    delivered BOOLEAN,
    response TEXT,                            -- member's reply if any
    org_id UUID
);

-- Automation sequences (configurable triggers)
CREATE TABLE gym_sequences (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,              -- 'new_lead_followup', 'trial_no_show', etc.
    trigger_type VARCHAR(50),                -- 'signup', 'no_attendance_days', 'cancellation', etc.
    trigger_config JSONB,                    -- {"days": 7, "status": "active"} etc.
    message_template TEXT,                   -- with {{name}}, {{days_since}} etc. placeholders
    channel VARCHAR(20) DEFAULT 'sms',
    enabled BOOLEAN DEFAULT TRUE,
    delay_hours INTEGER DEFAULT 0,           -- hours after trigger
    org_id UUID
);

-- Challenges
CREATE TABLE gym_challenges (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    start_date DATE,
    end_date DATE,
    signup_cutoff DATE,
    status VARCHAR(20) DEFAULT 'upcoming',   -- upcoming, active, completed
    checkin_frequency_days INTEGER DEFAULT 14,
    org_id UUID
);

-- Training blocks (aligned with BFT/programming calendar)
CREATE TABLE gym_blocks (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,                        -- block overview
    main_lifts JSONB,                        -- ["Back Squat", "Bench Press", etc.]
    flow_notes TEXT,                          -- programming notes for the block
    start_date DATE,
    end_date DATE,
    org_id UUID
);
```

### Gym `/gym` UI Pages

| Page | Purpose |
|------|---------|
| **Dashboard** | Today's attendance, new leads, at-risk members, upcoming milestones, revenue |
| **Members** | Member list with search/filter, status tabs (Active/Trial/Suspended/Cancelled), inline profile |
| **Leads** | Lead pipeline board (Kanban: New → Contacted → Trial Booked → Trial Complete → Signed Up / Lost) |
| **Schedule** | Class timetable, attendance heatmap, booking management |
| **Sequences** | Automation sequence editor: enable/disable, edit templates, set triggers and timing |
| **Challenges** | Active/upcoming challenges, participant list, check-in tracking |
| **Blocks** | Training block calendar, program details, notification preview |
| **Reports** | Retention rate, churn, lead conversion, attendance trends, revenue, NPS |
| **Comms Log** | Every message sent by the agent, with delivery status and member responses |

### How the Gym Vertical Uses Core Services

| Core Service | Gym Usage |
|-------------|-----------|
| **Core Comms (SMS)** | Every automation sequence above fires through `channels/sms.py` via Twilio |
| **Core Comms (WhatsApp)** | Member conversations, trial bookings, check-ins |
| **Core Comms (Voice)** | Inbound calls ("What classes do you have?"), retention calls for at-risk members |
| **Core Comms (Instagram DM)** | New follower DM flow, lead capture, trial booking |
| **Core Marketing (Social)** | Weekly content calendar, challenge promos, member milestones, Canva template integration |
| **Core Marketing (Email)** | Welcome sequences, monthly newsletters, challenge announcements |
| **Core Marketing (Ads)** | Google Ads for local leads, Meta Ads for Instagram/Facebook targeting |
| **Core Marketing (SEO)** | Local SEO for "gym near me", Google Business Profile management |
| **Core Workflow** | Staff scheduling, maintenance tasks, compliance checklists |

---

## Vertical Deep-Dive: Café/Restaurant (`/cafe`)

Based on real operational data from Dear Coco, a London café (Feb 2026). This defines the supplier management, ordering automation, and daily operations that the café vertical must handle.

### Supplier Ordering Automation

The café vertical's killer feature: the Nexus agent manages the entire supplier ordering process. Each supplier has different ordering methods, frequencies, delivery windows, and payment terms. Today this lives in a spreadsheet or someone's head. Nexus makes it systematic and proactive.

#### Supplier Registry (from Dear Coco process map)

| Supplier | Products | Order Frequency | Order Method | Delivery Days | Lead Time | Payment |
|----------|----------|----------------|-------------|---------------|-----------|---------|
| Stones Supply | Milk & Bottled Drinks | Daily | Rekki App | Weekdays (exc Thurs West London) | 1 day | Direct Debit |
| Delaserr | Pastries | Daily | Owned App | Weekdays | 1 day | Direct Debit |
| Triple Co Roast | Coffee Products | Weekly | Online Portal | Wednesdays | 1 day | Direct Debit |
| Cake Hoard | Bakes | Weekly | Online Portal | Weekdays | 1 day | In-Portal |
| House of Cine | Cinnamon Buns | Weekly | Email | Tue, Thu, Sat | 3 day | Invoice + Manual |
| Becker | Fresh Ingredients & Sundries | Weekly | Owned App | Monday | 1 day | In-App |
| Amkava | Disposable Packaging | Bi-Weekly | Rekki App | Weekdays | 1 day | In-App |
| Purpose Foods Ltd | Protein Balls | Bi-Weekly | Email | Weekdays | 2 day | Invoice + Manual |
| Cups Direct | Disposable Packaging (cup sleeves) | Monthly | Online Portal | Weekdays | 1 day | In-Portal |
| Carrier Bag Shop | Disposable Packaging (paper bags) | Monthly | Online Portal | Weekdays | 1 day | In-Portal |
| The Estate Dairy | Milk (Emergency Cover) | Ad Hoc | Rekki App | Everyday (incl Sundays) | 1 day | In-App |
| Amazon Prime | Miscellaneous Items | Ad Hoc | Online Portal | Everyday | Various | In-Portal |
| Nisbets | Catering Supplies | Ad Hoc | Online Portal | Weekdays | Various | In-Portal |

#### What the Agent Automates

**Daily ordering (milk, pastries):**
- Agent checks inventory levels each evening (POS integration or manual input)
- Calculates tomorrow's order based on: day of week demand patterns, weather forecast (hot = more iced drinks = more milk), events/holidays, historical sell-through data
- Drafts order and sends to owner for approval via WhatsApp: "Tomorrow's order: Stones Supply — 40L whole milk, 20L oat milk, 12 bottled waters. Delaserr — 24 croissants, 12 pain au choc, 6 almond pastries. Approve?"
- Owner replies "yes" → agent places order via appropriate channel (Rekki API, email, etc.)
- Handles exceptions: "Stones can't deliver Thursday in West London — switching to Estate Dairy for emergency milk cover"

**Weekly ordering (coffee, bakes, fresh ingredients):**
- Agent generates weekly order on schedule (e.g., Sunday evening for Monday delivery)
- Factors in: current stock, next week's bookings/events, seasonal menu items, supplier MOQs
- Bundles orders by supplier with appropriate lead times
- Tracks delivery: confirms receipt, flags shortages

**Bi-weekly/monthly ordering (packaging, sundries):**
- Agent monitors stock levels and triggers reorder when threshold hit
- For email-based suppliers (House of Cine, Purpose Foods): agent drafts and sends order email with standard template
- For portal-based suppliers: surfaces order details for owner to place (or automates via browser if API available)
- Tracks invoices for manual payment suppliers: "House of Cine invoice £245 is due Friday — reminder to pay"

**Ad hoc ordering:**
- Staff can tell the agent via WhatsApp: "We're running low on takeaway cups"
- Agent checks supplier, lead time, last order price, and drafts the order
- Emergency cover: agent knows Estate Dairy does Sunday delivery for milk emergencies

#### Supplier Integration Methods

| Method | Automation Level | How |
|--------|-----------------|-----|
| **Rekki App** | API if available, otherwise browser automation via Playwright | Check Rekki for API/webhook support |
| **Owned App** (Delaserr, Becker) | Browser automation or API | Investigate each supplier's platform |
| **Online Portal** | Browser automation via headless Chromium (already in Nexus) | Login, navigate, fill order form |
| **Email** | Fully automated via SendGrid/Mailchimp | Agent composes and sends order email |
| **In-App/In-Portal payment** | Alert owner to pay | Agent sends WhatsApp reminder |
| **Direct Debit** | No action needed | Agent tracks for reconciliation |
| **Invoice + Manual** | Agent tracks invoice, reminds owner to pay | WhatsApp reminder before due date |

### Café Automation Sequences (Core Comms Integration)

#### 1. Customer Ordering (WhatsApp/Voice)

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| Customer messages café number | Agent takes order from menu, confirms total, offers pickup time | WhatsApp | Real-time |
| Customer calls | Agent answers, takes order by voice, confirms | Voice (ElevenLabs) | Real-time |
| Order placed | Appears on `/cafe` dashboard for staff + kitchen display | Internal | Immediate |
| Order ready | "Your order is ready for pickup!" | WhatsApp/SMS | When staff marks ready |
| Post-order (new customer) | "Thanks for visiting Dear Coco! How was everything?" | SMS | 2h after |
| Post-order (repeat customer) | Loyalty point notification | SMS | 2h after |

#### 2. Reviews & Reputation

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| New Google/TripAdvisor review | Agent detects, drafts brand-voice response | Internal → Owner approval | Within 1h |
| Positive review (4-5⭐) | Thank you response + social share prompt | Review platform | After approval |
| Negative review (1-2⭐) | Empathetic response + offer to make it right | Review platform | After approval |
| Customer had positive interaction | Prompt for Google review | SMS | Next day |
| Weekly review summary | "This week: 8 new reviews, 4.6⭐ average, +0.1 from last week" | WhatsApp to owner | Weekly |

#### 3. Marketing & Social

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| Daily special decided | Agent creates Instagram/Facebook post with brand-voice caption | Social (Ayrshare) | Morning |
| New menu item | Photo post + story announcement | Instagram + Facebook | When added |
| Seasonal menu change | Content series: countdown, reveal, first-week promo | Social + Email | Planned |
| Local event nearby | "We're right around the corner from [event]! Pop in for..." | Social + Google Ads | Event day |
| Catering inquiry | Agent handles via WhatsApp/voice, sends menu PDF, books | WhatsApp/Voice/Email | Real-time |
| Quiet period (low POS activity) | Flash offer: "20% off iced coffees next 2 hours!" | Instagram Stories + SMS to loyal customers | Real-time |

#### 4. Staff & Operations

| Trigger | Action | Channel | Timing |
|---------|--------|---------|--------|
| Morning open workflow | Inventory check, supplier order confirmation, daily target, social post | Internal + WhatsApp | 6 AM |
| Shift reminder | "Your shift starts at [time] tomorrow" | SMS to staff | Evening before |
| End of day | Sales reconciliation, inventory update, tomorrow's prep list | Internal + WhatsApp | Close |
| Health inspection approaching | Compliance checklist, reminders for deep clean | WhatsApp + `/cafe` dashboard | 1 week before |
| Equipment issue reported | Log issue, draft supplier contact for repair | Internal | Immediate |

### Café Tools

```python
# Menu management
cafe__menu_list          # View current menu with prices, categories, availability
cafe__menu_update        # Add/edit/disable menu items, set daily specials
cafe__menu_pricing       # Update prices, cost analysis (COGS tracking)

# Ordering (customer-facing)
cafe__take_order         # Process customer order (WhatsApp/voice/walk-in)
cafe__order_status       # Check order status for customer
cafe__order_history      # Customer's past orders (for personalisation)

# Supplier management
cafe__supplier_list      # All suppliers with ordering methods, schedules, contacts
cafe__supplier_order     # Generate and place supplier order
cafe__check_inventory    # Current stock levels vs par levels
cafe__order_schedule     # What needs ordering today/this week (based on frequency + stock)
cafe__track_delivery     # Mark deliveries as received, flag shortages
cafe__invoice_tracker    # Outstanding invoices, payment reminders

# Loyalty & customers
cafe__loyalty_balance    # Check/update customer loyalty points
cafe__customer_profile   # Regular customers: preferences, order history, spend
cafe__loyalty_reward     # Issue reward (free coffee, discount, etc.)

# Reviews & reputation
cafe__monitor_reviews    # Check new Google/TripAdvisor/Yelp reviews
cafe__draft_review_reply # Generate brand-voice response to review
cafe__review_stats       # Average rating, trend, volume by platform

# Reporting
cafe__daily_summary      # Sales, orders, popular items, waste, inventory
cafe__weekly_report      # Revenue trends, best sellers, supplier costs, marketing ROI
cafe__cogs_report        # Cost of goods sold analysis per menu item
```

### Café Database Tables

```sql
-- Menu items
CREATE TABLE cafe_menu (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    category VARCHAR(50),                    -- 'coffee', 'food', 'cold_drinks', 'bakery'
    price DECIMAL(8,2),
    cost DECIMAL(8,2),                       -- COGS for margin tracking
    available BOOLEAN DEFAULT TRUE,
    is_daily_special BOOLEAN DEFAULT FALSE,
    image_url TEXT,
    allergens JSONB,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Suppliers
CREATE TABLE cafe_suppliers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    products TEXT,                            -- what they supply
    order_frequency VARCHAR(20),             -- 'daily', 'weekly', 'bi_weekly', 'monthly', 'ad_hoc'
    order_method VARCHAR(30),                -- 'rekki', 'email', 'portal', 'app', 'phone'
    order_method_details JSONB,              -- login URL, email address, API key, etc.
    delivery_days VARCHAR(100),              -- 'mon,tue,wed,thu,fri' or 'everyday'
    lead_time_days INTEGER DEFAULT 1,
    payment_method VARCHAR(30),              -- 'direct_debit', 'in_app', 'invoice', 'in_portal'
    contact_name VARCHAR(100),
    contact_email VARCHAR(200),
    contact_phone VARCHAR(30),
    notes TEXT,
    org_id UUID
);

-- Inventory / stock levels
CREATE TABLE cafe_inventory (
    id SERIAL PRIMARY KEY,
    item_name VARCHAR(200) NOT NULL,
    category VARCHAR(50),
    current_qty DECIMAL(10,2),
    unit VARCHAR(20),                        -- 'litres', 'units', 'kg', 'boxes'
    par_level DECIMAL(10,2),                 -- reorder when below this
    supplier_id INTEGER REFERENCES cafe_suppliers(id),
    last_ordered DATE,
    last_delivery DATE,
    cost_per_unit DECIMAL(8,2),
    org_id UUID
);

-- Customer orders
CREATE TABLE cafe_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID,                        -- nullable for walk-ins
    channel VARCHAR(20),                     -- 'whatsapp', 'voice', 'walk_in', 'web'
    items JSONB,                             -- [{name, qty, price}]
    total DECIMAL(8,2),
    status VARCHAR(20) DEFAULT 'pending',    -- pending, preparing, ready, collected, cancelled
    pickup_time TIMESTAMP,
    notes TEXT,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Supplier orders
CREATE TABLE cafe_supplier_orders (
    id SERIAL PRIMARY KEY,
    supplier_id INTEGER REFERENCES cafe_suppliers(id),
    items JSONB,                             -- [{item, qty, unit, estimated_cost}]
    total_estimated DECIMAL(8,2),
    status VARCHAR(20) DEFAULT 'draft',      -- draft, approved, placed, delivered, issue
    order_date DATE,
    expected_delivery DATE,
    actual_delivery DATE,
    placed_via VARCHAR(30),                  -- 'rekki', 'email', 'portal', etc.
    invoice_amount DECIMAL(8,2),
    invoice_paid BOOLEAN DEFAULT FALSE,
    notes TEXT,
    org_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Loyalty program
CREATE TABLE cafe_loyalty (
    id SERIAL PRIMARY KEY,
    customer_id UUID NOT NULL,
    points INTEGER DEFAULT 0,
    total_spend DECIMAL(10,2) DEFAULT 0,
    total_visits INTEGER DEFAULT 0,
    last_visit DATE,
    tier VARCHAR(20) DEFAULT 'bronze',       -- bronze, silver, gold
    org_id UUID
);
```

### Café `/cafe` UI Pages

| Page | Purpose |
|------|---------|
| **Dashboard** | Today's orders, revenue, inventory alerts, pending supplier orders, review summary |
| **Orders** | Live order board (kitchen display), order history, per-customer view |
| **Menu** | Menu editor with categories, pricing, availability toggle, daily specials |
| **Inventory** | Stock levels with par-level alerts, reorder triggers, waste logging |
| **Suppliers** | Supplier registry, order schedule, delivery calendar, invoice tracker |
| **Customers** | Loyalty members, order history, preferences, review correlation |
| **Reviews** | All-platform review feed, response drafts, rating trends |
| **Reports** | Daily/weekly/monthly: revenue, COGS, popular items, supplier spend, marketing ROI |

### Implementation: Phase V-CAFE (4-5 sessions)

**Session 1**: Database tables + cafe_plugin.py with menu and inventory tools
**Session 2**: Supplier management (registry, ordering schedules, automated order generation)
**Session 3**: Customer ordering (WhatsApp/voice order flow, order board, loyalty)
**Session 4**: Review management + daily operations workflows (morning open, end of day)
**Session 5**: `/cafe` React UI (dashboard, orders, menu, inventory, suppliers, reviews, reports)

---

### Implementation: Phase V-GYM (4-5 sessions)

**Session 1**: Database tables + gym_plugin.py with member management and attendance tools
**Session 2**: Automation sequence engine (trigger → delay → message pipeline) + configurable sequences table
**Session 3**: Lead pipeline (scoring, stages, conversion tracking) + trial management workflow
**Session 4**: Retention engine (at-risk detection, milestone tracking, reactivation) + challenge/block management
**Session 5**: `/gym` React UI (dashboard, members, leads, sequences, schedule, reports)

### Admin UI Config Additions

All API keys and provider settings go in Admin UI `/admin/settings`:

**Communications:**
- Twilio Account SID, Auth Token, Phone Number
- ElevenLabs API Key, Voice ID, Model selection
- Deepgram API Key
- WhatsApp Business Account ID

**Marketing:**
- Ayrshare API Key
- Mailchimp API Key, Server prefix
- SendGrid API Key
- Google Ads Developer Token, Customer ID
- Meta Marketing App ID, App Secret, Access Token
- Google Search Console credentials
- Ahrefs/SEMrush API Key (optional)

---

## Quick Wins (can ship immediately)

1. **`ChannelMessage` dataclass + `ChannelAdapter` ABC** — 200 lines, unlocks all channels
2. **Twilio webhook endpoint** — 100 lines, receives WhatsApp + SMS immediately
3. **Brand voice table** — simple migration, enables all marketing content generation
4. **PersistentTerminalSession** — 300 lines, upgrades all terminal tools
5. **`core/event_bus.py`** — 200 lines, backbone for all three streams

---

## How It All Connects: The Nexus Agent Experience

### The Nexus Difference: AI-Native, Not AI-Bolted-On

Traditional platforms bolt AI onto existing software: "We added a chatbot to our POS system." Nexus inverts this entirely. **The AI agent IS the platform.** It doesn't integrate into an existing system — it builds and operates the entire business platform from the ground up.

Every feature, every workflow, every customer interaction starts with the agent. The UIs (`/marketing`, `/workflow`, `/cafe`, `/gym`, `/legal`) are visual dashboards into what the agent already knows and does — not the other way around. You don't configure a platform and then add an AI assistant. You deploy an AI agent and it creates the operational platform around itself.

### Scenario: A Day at "The Daily Grind" Café

**6:30 AM** — Nexus agent's morning workflow triggers automatically:
- Checks inventory levels via `cafe__check_inventory` → milk is low
- Auto-generates a supplier order via `cafe__order_supplier` (human approval required for orders > $200)
- Sends the owner a WhatsApp: "Morning! Milk's low — I've drafted an order to Dairy Co for 40L ($180). Approve? Also, today's special: I suggest Maple Pecan Latte based on what sold well last week."
- Owner replies "yes" to both on WhatsApp
- Agent posts the daily special to Instagram and Facebook via `social_post` with brand-voice caption and the café's visual template

**7:15 AM** — Customer WhatsApps the café number: "Can I order 2 flat whites and a banana bread for pickup at 7:45?"
- The Nexus agent (same one, same memory) handles the order via `cafe__take_order`
- Confirms: "Got it! 2 flat whites + banana bread — ready at 7:45. $18.50. Pay on pickup or tap to pay now?"
- Registers the order on the `/cafe` dashboard for staff to prepare

**9:00 AM** — Google review comes in: ⭐⭐⭐ "Coffee was good but waited 15 minutes"
- Agent detects via `cafe__monitor_reviews`, drafts a brand-voice response
- Sends owner for approval: "Suggested reply: 'Thanks for visiting! We're sorry about the wait — mornings can get busy. Next time, try our WhatsApp ordering to skip the queue! ☕'"
- Owner approves, agent posts the response

**10:00 AM** — Owner opens `/cafe` dashboard on their laptop:
- Sees today's orders, inventory levels, loyalty member visits, staff schedule
- Asks the chat widget: "How did last week's promo go?"
- Agent pulls `social_analytics` + `cafe__sales_report`: "The 2-for-1 Tuesday promo drove 34% more foot traffic. Instagram reach was 2,800 (+60%). Revenue was up $420 but margin was tighter. Recommend keeping it monthly rather than weekly."

**11:00 AM** — Phone call comes in via Twilio:
- Nexus agent answers with ElevenLabs voice: "Hi, you've reached The Daily Grind! How can I help?"
- Customer asks about catering for an office event
- Agent uses KG to retrieve catering menu, provides options and pricing
- Books the catering order, sends confirmation email via Mailchimp
- Tags the customer as a B2B lead in the café's CRM

**2:00 PM** — Agent sends a push to the `/cafe` dashboard: "Banana bread sold out by 11 AM again — this is the 3rd time this week. Recommend increasing tomorrow's batch from 12 to 18. I've also updated the supplier order draft."

**5:00 PM** — End-of-day workflow triggers:
- Agent reconciles the day's sales with POS data
- Updates loyalty points for today's customers
- Drafts tomorrow's social post (scheduled for 7 AM)
- Sends owner an evening WhatsApp summary: "Today: 142 orders, $2,340 revenue, 8 new loyalty signups, 4.2⭐ average review score. Banana bread was MVP again."

### The Same Agent, Different Business

Now replace "café" with "gym" and the agent:
- Manages class schedules instead of menu items
- Sends workout summaries instead of daily specials
- Tracks membership renewals instead of loyalty points
- Handles class booking via WhatsApp instead of coffee orders
- Posts transformation stories on Instagram instead of latte art

Or replace with "law firm" and the agent:
- Manages matters instead of orders
- Tracks billable hours instead of inventory
- Sends court date reminders instead of supplier orders
- Handles client intake via voice instead of coffee orders
- Posts thought leadership on LinkedIn instead of daily specials

**The core services (Marketing, Comms, Workflow) are identical.** The vertical module provides the domain-specific tools, data models, workflows, and UI — but the intelligence is the same Nexus agent, learning and operating across everything.

### Why This Wins

1. **One subscription replaces 5-10 SaaS tools**: No Squarespace + Mailchimp + Square POS + Google Ads dashboard + social media scheduler + review management tool. Just Nexus.
2. **Cross-domain intelligence**: The agent connects marketing performance to actual sales. "Your Instagram post about oat milk drove 12 orders today" — no other tool can do this because they're all siloed.
3. **Proactive operations**: The agent doesn't wait to be asked. It notices patterns, suggests actions, handles routine tasks automatically (with approval gates).
4. **Natural language as the primary interface**: The owner doesn't need to learn 10 different dashboards. "How's business?" on WhatsApp gives them everything they need. The dashboards exist for power users who want the full picture.
