# Nexus — Personal AI Agent

## Architecture Overview

Nexus is a locally-hosted autonomous AI agent with a dual-model brain, a learnable skills system, and optional Telegram integration. It's designed to be stable, secure, and actually useful — not a sprawling platform, but a focused tool.

```
┌─────────────────────────────────────────────────────┐
│                    YOU (User)                        │
│          Web UI  ◄──────►  Telegram Bot              │
└──────────┬──────────────────────┬────────────────────┘
           │                      │
           ▼                      ▼
┌─────────────────────────────────────────────────────┐
│                  NEXUS GATEWAY                       │
│  ┌───────────┐  ┌───────────┐  ┌─────────────────┐  │
│  │  Router   │  │  Session   │  │  Task Queue     │  │
│  │  (decides │  │  Manager   │  │  (background    │  │
│  │  which    │  │  (context, │  │   research,     │  │
│  │  model)   │  │  memory)   │  │   learning)     │  │
│  └─────┬─────┘  └───────────┘  └─────────────────┘  │
│        │                                             │
│        ▼                                             │
│  ┌───────────────────────────────────────────────┐   │
│  │            MODEL PROVIDER LAYER               │   │
│  │                                               │   │
│  │  ┌─────────────┐    ┌──────────────────────┐  │   │
│  │  │   Ollama    │    │   Anthropic API      │  │   │
│  │  │  (Kimi K2.5 │    │   (Claude Sonnet/    │  │   │
│  │  │   or any    │    │    Opus for complex  │  │   │
│  │  │   local)    │    │    reasoning)        │  │   │
│  │  └─────────────┘    └──────────────────────┘  │   │
│  └───────────────────────────────────────────────┘   │
│                                                      │
│  ┌───────────────────────────────────────────────┐   │
│  │              SKILLS ENGINE                    │   │
│  │                                               │   │
│  │  Research ─► Summarise ─► Extract ─► Store    │   │
│  │                                               │   │
│  │  Skills are stored as structured knowledge    │   │
│  │  that the agent can reference and apply       │   │
│  │  in future conversations.                     │   │
│  └───────────────────────────────────────────────┘   │
│                                                      │
│  ┌───────────────────────────────────────────────┐   │
│  │              LOCAL STORAGE                    │   │
│  │  SQLite DB: conversations, skills, tasks      │   │
│  │  Files: research outputs, generated docs      │   │
│  └───────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

## Core Design Principles

1. **Stability over features** — Simple, well-tested components. No fragile gateway architecture.
2. **Security by default** — Runs on localhost only. No exposed ports. API keys in `.env` only.
3. **Dual-model routing** — Fast/cheap model for simple tasks, powerful model for complex ones.
4. **Learnable skills** — Research a topic → distill knowledge → store as a skill → apply later.
5. **Graceful degradation** — If Ollama is down, route everything to Claude. If API is down, use local only.

## Component Breakdown

### 1. Backend (Python / FastAPI)
- **Why Python**: Best ecosystem for AI/ML integration, simple async support, massive library availability.
- **FastAPI**: Async, fast, auto-generates API docs, WebSocket support for streaming.
- **SQLite**: Zero-config database. No separate process to crash. Backups are just file copies.

### 2. Model Router
Routes each request to the appropriate model based on:
- **Complexity estimation**: Simple questions → Ollama/local. Complex reasoning → Claude API.
- **User override**: User can force a specific model with `/use claude` or `/use local`.
- **Fallback chain**: If primary model fails, automatically try the next one.
- **Cost awareness**: Tracks API usage so you know what you're spending.

### 3. Skills Engine
This is the core differentiator. When you ask Nexus to "learn about" a topic:
1. **Research phase**: Uses Claude to perform deep research on the topic.
2. **Extraction phase**: Distills the research into structured knowledge (key concepts, decision trees, references).
3. **Storage phase**: Saves as a skill file (Markdown + metadata) in the skills directory.
4. **Application phase**: When future questions match a skill's domain, the skill context is injected into the prompt.

Skills are stored as simple Markdown files with YAML frontmatter, making them human-readable and editable.

### 4. Task Queue
Background task processing for autonomous work:
- Research tasks that run while you're away.
- Periodic skill updates (re-research to keep knowledge fresh).
- Scheduled summaries or reports.
- Uses Python's built-in `asyncio` — no Redis/Celery overhead.

### 5. Web UI
- Clean, modern single-page app.
- Real-time streaming responses via WebSocket.
- Skill management panel (view, edit, delete learned skills).
- Task queue visibility (see what's running, what's queued).
- Model indicator (shows which model is handling each response).

### 6. Telegram Integration (Optional)
- Simple bot using `python-telegram-bot` library.
- Bridges messages to the same backend as the Web UI.
- Supports text, voice messages (transcribed), and file sharing.

## File Structure

```
nexus/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Configuration management
│   ├── models/
│   │   ├── router.py        # Model routing logic
│   │   ├── ollama_client.py # Ollama API client
│   │   └── claude_client.py # Anthropic API client
│   ├── skills/
│   │   ├── engine.py        # Skills learning & retrieval
│   │   └── researcher.py    # Autonomous research logic
│   ├── tasks/
│   │   └── queue.py         # Background task management
│   ├── storage/
│   │   └── database.py      # SQLite operations
│   ├── channels/
│   │   └── telegram.py      # Telegram bot integration
│   └── utils/
│       └── streaming.py     # SSE/WebSocket helpers
├── frontend/
│   └── index.html           # Single-file Web UI
├── skills/                  # Learned skill files (Markdown)
│   └── .gitkeep
├── data/                    # SQLite DB & generated files
│   └── .gitkeep
├── .env.example             # Environment variable template
├── requirements.txt         # Python dependencies
├── setup.sh                 # One-command setup script
└── docs/
    └── ARCHITECTURE.md      # This file
```

## Getting Started

See `setup.sh` for automated setup, or manually:

```bash
# 1. Clone and enter directory
cd nexus

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit .env with your API keys

# 5. Ensure Ollama is running (if using local models)
# ollama serve
# ollama pull kimi-k2.5:cloud  (or any model you prefer)

# 6. Run
python backend/main.py
# Open http://localhost:8080
```

## Security Notes

- All traffic stays on `localhost` by default.
- API keys are stored in `.env` (never committed to git).
- SQLite database is local — no external database connections.
- Telegram bot token is the only outbound credential.
- No admin interface exposed on any port.
- Skills and data stored in plain files you can audit anytime.
