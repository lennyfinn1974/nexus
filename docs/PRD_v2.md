# Nexus AI Agent Platform — Product Requirements Document

**Version:** 2.0
**Date:** 2 February 2026
**Status:** Draft for Review

---

## 1. Executive Summary

Nexus is a self-hosted personal AI agent that runs on local hardware (Mac Mini). It provides an intelligent assistant with dual-model routing (cloud Claude API + local Ollama models), a learnable knowledge base, document ingestion, and an extensible plugin system for tool integrations (GitHub, browser automation, etc.).

**v1.0 (current state)** established the core architecture: chat interface, model routing, skills/research system, document ingestion, and initial plugin framework. However, the admin experience relies heavily on manual terminal commands and `.env` file editing. Settings entered via the admin UI don't persist reliably, plugin activation requires command-line setup, and the platform lacks the management layer needed to operate it day-to-day without touching code.

**v2.0 (this PRD)** focuses on making Nexus a production-grade, self-administering platform where all configuration, plugin management, monitoring, and expansion happens through the browser UI.

---

## 2. Problems to Solve

### 2.1 Settings Don't Persist Reliably
- The admin panel writes to `.env` but the running process doesn't pick up changes without a restart
- Password fields show masked values but don't distinguish "unchanged" from "cleared"
- No validation, no confirmation that saves succeeded
- Race condition: `.env` can be edited by both the admin UI and manually

### 2.2 Plugin Management Is Manual
- Enabling a plugin requires: install Python package via terminal, edit `.env`, restart server
- No way to see what a plugin needs or why it failed from the UI
- No hot-reload — every change requires kill + restart

### 2.3 No Operational Visibility
- No request/error logs in the UI
- No token usage tracking or cost estimates
- No conversation analytics
- No health monitoring or alerts

### 2.4 Limited Expandability
- Adding a new plugin requires Python knowledge
- No marketplace or catalogue of available plugins
- No way to configure plugin-specific settings from the UI
- System prompt customisation is fragile

---

## 3. Architecture Overview (v2.0)

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (Web UI)                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │   Chat   │ │  Admin   │ │ Plugins  │ │  Monitor   │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘  │
└───────┼────────────┼────────────┼──────────────┼─────────┘
        │ WebSocket  │ REST API   │ REST API     │ SSE
┌───────┴────────────┴────────────┴──────────────┴─────────┐
│                    FastAPI Backend                         │
│  ┌─────────┐ ┌─────────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Config  │ │  Settings   │ │  Plugin  │ │  Monitor │  │
│  │ Manager │ │  Database   │ │  Manager │ │  Service │  │
│  └────┬────┘ └──────┬──────┘ └────┬─────┘ └────┬─────┘  │
│       │             │             │             │         │
│  ┌────┴─────────────┴─────────────┴─────────────┴────┐   │
│  │              SQLite Database                       │   │
│  │  settings │ plugins │ logs │ conversations │ skills│   │
│  └───────────────────────────────────────────────────┘   │
│       │                                                   │
│  ┌────┴────────────────┐  ┌───────────────────────────┐  │
│  │    Model Router     │  │     Task Queue            │  │
│  │  Ollama ←→ Claude   │  │  Research │ Ingest │ ...  │  │
│  └─────────────────────┘  └───────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
```

### Key Change: Settings Move from .env to Database

The single biggest architectural change is moving runtime configuration from `.env` file parsing to a **settings database table**. The `.env` file becomes a bootstrap-only file (server host/port, database path). Everything else — API keys, model selection, plugin config, persona — lives in SQLite and is editable live.

---

## 4. Functional Requirements

### 4.1 Settings Management (P0 — Must Have)

**FR-4.1.1: Database-backed settings**
- All configuration stored in `settings` table: `key TEXT PRIMARY KEY, value TEXT, encrypted INTEGER, updated_at TEXT`
- Sensitive values (API keys, tokens) encrypted at rest using a local machine key
- On first boot, migrate any existing `.env` values into the database
- `.env` retains only: `HOST`, `PORT`, `DB_PATH`, `SECRET_KEY` (auto-generated)

**FR-4.1.2: Live settings updates**
- Changing a setting takes effect immediately (no restart)
- Config manager holds current values in memory, reloads on update
- Model router reconnects when API keys or model names change
- Plugin manager re-evaluates plugin eligibility when tokens change

**FR-4.1.3: Settings UI**
- Grouped by section (Models, Routing, Plugins, Server, Persona)
- Field types: text, password (with show/hide toggle), number, range slider, select dropdown, toggle
- Save button per section with success/error toast feedback
- "Test Connection" button next to each API key field
- Validation: URL format, port range, threshold bounds
- Change indicator: unsaved changes shown with dot/highlight

**FR-4.1.4: Settings import/export**
- Export all non-sensitive settings as JSON
- Import settings from JSON (for backup/restore/migration)
- Export encrypted backup including secrets (password-protected)

### 4.2 Plugin System (P0 — Must Have)

**FR-4.2.1: Plugin lifecycle management**
- States: `available` → `configured` → `active` → `error`
- Each plugin declares its requirements: `{"GITHUB_TOKEN": {"type": "password", "required": true, "description": "..."}}`
- Plugin settings stored in the settings database with `plugin.<name>.<key>` prefix
- Enable/disable toggle per plugin (persisted, survives restart)

**FR-4.2.2: Plugin configuration from UI**
- When user clicks a plugin, show its required settings fields
- "Configure & Enable" flow: fill in fields → save → plugin activates immediately
- Status indicator: green (active), yellow (configured but error), red (missing config), grey (disabled)
- Error details shown inline (e.g. "GitHub returned 401: Bad credentials")

**FR-4.2.3: Plugin dependency management**
- Plugin declares pip dependencies: `pip_requires = ["playwright"]`
- UI shows missing dependencies with install command
- Optional: one-click install button that runs pip in background task

**FR-4.2.4: Improved plugin base class**
- `required_settings` — dict of settings the plugin needs
- `pip_requires` — list of pip packages
- `on_settings_changed()` — called when relevant settings update (hot-reload)
- `health_check()` — periodic check returns status + error message
- Plugin-specific slash commands auto-registered with help text

**FR-4.2.5: Built-in plugins (ship with Nexus)**
- GitHub — repository, issue, PR, code management
- Browser — headless Chromium automation via Playwright
- Web Search — web search and page fetching
- File System — sandboxed local file operations (read, write, list within allowed directories)
- Scheduler — cron-style recurring tasks (e.g. "check GitHub issues every morning")

### 4.3 Admin Dashboard (P0 — Must Have)

**FR-4.3.1: Dashboard home**
- System health at a glance: model status, active plugins, task queue, disk/memory
- Token usage chart (daily/weekly/monthly) with estimated cost
- Recent conversations list with message counts
- Quick actions: new chat, run research, toggle model

**FR-4.3.2: Conversations management**
- List all conversations with title, date, message count, model used
- Search conversations by content
- Delete individual or bulk delete
- Export conversation as Markdown or JSON

**FR-4.3.3: Skills management**
- List all skills with name, domain, usage count, date created
- View full skill content
- Edit skill content inline
- Delete skills
- Force re-research a skill (refresh from latest information)
- Import/export skills as files

**FR-4.3.4: Task management**
- Live task queue view with status (pending, running, completed, failed)
- Task output/error details
- Cancel running tasks
- Retry failed tasks
- Task history with filtering

**FR-4.3.5: Log viewer**
- Real-time log stream (via Server-Sent Events)
- Filter by level (DEBUG, INFO, WARNING, ERROR)
- Filter by component (router, skills, plugins, tasks)
- Searchable
- Download log file

### 4.4 Agent Persona & Behaviour (P1 — Should Have)

**FR-4.4.1: Persona configuration**
- Agent name (used in system prompt and UI branding)
- Custom system prompt instructions (appended to base prompt)
- Tone setting: professional, casual, technical, creative
- Response length preference: concise, balanced, detailed
- Preview: show the full assembled system prompt

**FR-4.4.2: Per-conversation context**
- Pin documents or skills to a conversation (always injected into context)
- Set conversation-specific model override
- Conversation title editing

### 4.5 Model Management (P1 — Should Have)

**FR-4.5.1: Model configuration**
- List available Ollama models (fetched from Ollama API)
- Select active Ollama model from dropdown
- Claude model selection from supported list
- Complexity threshold slider with live preview ("this message would route to: Claude")

**FR-4.5.2: Model testing**
- "Test" button that sends a probe message and shows response + latency
- Token counter: show estimated tokens for current conversation context
- Model comparison: send same prompt to both models, show side-by-side

**FR-4.5.3: Usage tracking**
- Track tokens in/out per model per conversation
- Estimated cost calculation for Claude usage
- Daily/weekly/monthly usage charts
- Budget alert: configurable warning when approaching spend threshold

### 4.6 Security (P0 — Must Have)

**FR-4.6.1: Admin authentication**
- Optional admin password (for when server is exposed on local network)
- Session-based auth with configurable timeout
- API endpoints require auth token when password is set

**FR-4.6.2: Secrets management**
- API keys encrypted in database using Fernet (symmetric encryption)
- Machine-local secret key auto-generated on first boot, stored in `.nexus_secret`
- Keys never returned in full via API (always masked)
- Audit log for settings changes

**FR-4.6.3: File system sandboxing**
- Plugins can only access explicitly allowed directories
- Document ingestion limited to configured `docs_dir`
- Browser plugin screenshots stored in designated folder
- No arbitrary file system access from the chat interface

### 4.7 Reliability (P1 — Should Have)

**FR-4.7.1: Graceful error handling**
- Model timeout: configurable per-model, with automatic fallback
- Plugin crash isolation: one plugin failure doesn't take down others
- Database corruption recovery: automatic backup before migrations
- WebSocket reconnection with message queue (no lost messages)

**FR-4.7.2: Auto-restart**
- Process manager wrapper (simple Python watchdog or systemd unit)
- Crash detection and automatic restart
- Health endpoint for external monitoring

**FR-4.7.3: Data backup**
- Automatic daily SQLite backup (configurable retention)
- Skills directory backup
- One-click manual backup from admin UI
- Restore from backup

---

## 5. UI/UX Specifications

### 5.1 Layout

The UI has two modes:

**Chat Mode** (default) — current layout: sidebar + chat area + slide-out panels

**Admin Mode** — full-page admin dashboard accessed via sidebar "Admin" button or gear icon:

```
┌──────────┬───────────────────────────────────────────┐
│          │  Admin > Settings                         │
│  Admin   │  ┌─────────────────────────────────────┐  │
│  Nav     │  │ Models          [Test] [Save]       │  │
│          │  │ ┌─────────────────────────────────┐  │  │
│ Dashboard│  │ │ Anthropic API Key  [••••••••]   │  │  │
│ Settings │  │ │ Claude Model   [claude-sonnet ▾] │  │  │
│ Plugins  │  │ │ Ollama URL     [localhost:11434] │  │  │
│ Skills   │  │ └─────────────────────────────────┘  │  │
│ Tasks    │  │                                       │  │
│ Logs     │  │ Routing         [Save]               │  │
│ System   │  │ ┌─────────────────────────────────┐  │  │
│          │  │ │ Threshold  ◀──────●──────▶  60  │  │  │
│          │  │ └─────────────────────────────────┘  │  │
│          │  │                                       │  │
│ ← Chat   │  │ Plugins         [Save]               │  │
│          │  │ ┌─────────────────────────────────┐  │  │
│          │  │ │ GitHub Token   [••••••••] [Test] │  │  │
│          │  │ └─────────────────────────────────┘  │  │
│          │  └─────────────────────────────────────┘  │
└──────────┴───────────────────────────────────────────┘
```

### 5.2 Design System

Existing design language (maintained from v1):
- Dark theme: `#0a0a0f` background, purple `#6c5ce7` accent
- Fonts: DM Sans (UI), JetBrains Mono (code/data)
- Border radius: 12px (cards), 8px (inputs)
- Slide-out panels for quick access, full pages for deep management

New components needed:
- Toggle switch (on/off)
- Toast notifications (success/error/info, auto-dismiss)
- Tabs (horizontal, within panels and pages)
- Status badges (green/yellow/red/grey dots with labels)
- Data tables (sortable, with actions)
- Modal dialogs (for confirmations and forms)
- Real-time log viewer (auto-scrolling, filterable)
- Charts (usage over time — lightweight, no heavy dependencies)

### 5.3 Responsive Behaviour

- Desktop (>1024px): full sidebar + content
- Tablet (768-1024px): collapsible sidebar
- Mobile (<768px): sidebar as overlay, single-column admin

---

## 6. Technical Specifications

### 6.1 Settings Database Schema

```sql
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    encrypted INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT 'general',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_by TEXT NOT NULL DEFAULT 'system'
);

CREATE TABLE settings_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TEXT NOT NULL DEFAULT (datetime('now')),
    changed_by TEXT NOT NULL DEFAULT 'admin'
);
```

### 6.2 Plugin Manifest (enhanced base class)

```python
class NexusPlugin:
    name = "my_plugin"
    description = "What this plugin does"
    version = "0.1.0"

    # NEW: Declarative requirements
    required_settings = {
        "GITHUB_TOKEN": {
            "type": "password",
            "label": "GitHub Personal Access Token",
            "description": "Get one at github.com/settings/tokens",
            "required": True,
        }
    }

    pip_requires = ["httpx"]

    async def setup(self): ...
    async def shutdown(self): ...
    async def health_check(self) -> dict:
        return {"status": "ok"}  # or {"status": "error", "message": "..."}
    async def on_settings_changed(self, changed_keys): ...
    def register_tools(self): ...
    def register_commands(self): ...
```

### 6.3 Config Manager (replaces current Config dataclass)

```python
class ConfigManager:
    """Live configuration backed by SQLite."""

    async def get(self, key, default=None) -> str
    async def set(self, key, value, encrypted=False) -> None
    async def get_section(self, category) -> dict
    async def subscribe(self, key_pattern, callback)  # notify on change
    async def migrate_from_env(self, env_path)  # one-time migration
```

### 6.4 API Endpoints (v2)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | All settings (masked secrets) |
| PUT | `/api/settings/{key}` | Update single setting |
| POST | `/api/settings/batch` | Update multiple settings |
| POST | `/api/settings/test/{key}` | Test a connection (API key, URL) |
| GET | `/api/plugins` | All plugins with status |
| POST | `/api/plugins/{name}/enable` | Enable a plugin |
| POST | `/api/plugins/{name}/disable` | Disable a plugin |
| GET | `/api/plugins/{name}/health` | Plugin health check |
| POST | `/api/plugins/{name}/install-deps` | Install pip dependencies |
| GET | `/api/models` | Available models (Ollama list + Claude options) |
| POST | `/api/models/test` | Test model connection |
| GET | `/api/usage` | Token usage statistics |
| GET | `/api/logs/stream` | SSE endpoint for live logs |
| GET | `/api/logs` | Historical logs with filtering |
| GET | `/api/conversations` | List conversations |
| GET | `/api/conversations/{id}/export` | Export as Markdown/JSON |
| GET | `/api/system/health` | System health check |
| POST | `/api/system/backup` | Create backup |
| POST | `/api/system/restore` | Restore from backup |

### 6.5 File Structure (v2)

```
nexus/
├── .env                    # Bootstrap only: HOST, PORT, SECRET_KEY
├── .nexus_secret           # Auto-generated encryption key
├── requirements.txt
├── setup.sh
│
├── backend/
│   ├── main.py             # FastAPI app, lifespan, WebSocket
│   ├── config_manager.py   # Database-backed live configuration
│   ├── admin.py            # Admin API routes
│   ├── monitor.py          # Logging, usage tracking, SSE stream
│   │
│   ├── models/
│   │   ├── router.py       # Complexity scoring + model selection
│   │   ├── ollama_client.py
│   │   └── claude_client.py
│   │
│   ├── plugins/
│   │   ├── base.py         # Enhanced plugin base class
│   │   ├── manager.py      # Discovery, lifecycle, hot-reload
│   │   ├── github_plugin.py
│   │   ├── browser_plugin.py
│   │   ├── websearch_plugin.py
│   │   ├── filesystem_plugin.py
│   │   ├── scheduler_plugin.py
│   │   └── _template.py
│   │
│   ├── skills/
│   │   ├── engine.py       # Skill storage, retrieval, relevance
│   │   └── ingest.py       # Document reading + conversion
│   │
│   ├── storage/
│   │   ├── database.py     # SQLite operations
│   │   └── encryption.py   # Fernet encryption for secrets
│   │
│   ├── tasks/
│   │   └── queue.py        # Async background task runner
│   │
│   └── channels/
│       └── telegram.py     # Telegram bot bridge
│
├── frontend/
│   ├── index.html          # Chat interface
│   └── admin.html          # Full admin dashboard (separate page)
│
├── skills/                 # Learned skill markdown files
├── docs_input/             # Document ingestion folder
├── data/
│   ├── nexus.db            # Main database
│   └── backups/            # Automatic backups
└── docs/
    ├── ARCHITECTURE.md
    └── PLUGIN_GUIDE.md     # How to create plugins
```

---

## 7. Migration Plan (v1 → v2)

### Phase 1: Foundation (Settings Database + Config Manager)
1. Create `config_manager.py` with SQLite-backed settings
2. Create `encryption.py` for secret storage
3. Write migration logic: read `.env` → insert into database → rename `.env` to `.env.backup`
4. Update all components to read from ConfigManager instead of Config dataclass
5. Implement live reload: settings changes propagate without restart

### Phase 2: Admin Dashboard
1. Create `admin.html` as a separate full-page admin interface
2. Build settings UI with sections, validation, test buttons
3. Build plugin management UI with configure-and-enable flow
4. Build conversation and skills management
5. Add log viewer with SSE streaming

### Phase 3: Plugin System Upgrade
1. Enhance `base.py` with `required_settings`, `pip_requires`, `health_check`
2. Update `manager.py` with hot-reload and dependency checking
3. Migrate existing plugins (GitHub, Browser) to new base class
4. Build new plugins: Web Search, File System, Scheduler
5. Plugin settings stored in database with `plugin.<name>.<key>` prefix

### Phase 4: Monitoring & Reliability
1. Token usage tracking in database
2. Usage charts in admin dashboard
3. Auto-backup system
4. Process watchdog for auto-restart
5. Health endpoint for external monitoring

---

## 8. Success Criteria

| Criteria | Measurement |
|----------|-------------|
| Zero terminal commands needed for daily operation | All config, plugin, and skill management via browser |
| Settings persist across restarts | 100% of settings saved in database survive restart |
| Plugin enable/disable from UI | User can activate GitHub plugin in <60 seconds from admin panel |
| Error visibility | All errors surface in admin UI within 5 seconds |
| No data loss | Automatic backups, graceful error handling, conversation persistence |
| Expandable | New plugin from template to working in <30 minutes |

---

## 9. Out of Scope (v2)

- Multi-user support (Nexus is single-user/single-machine)
- Cloud deployment or hosted version
- Mobile native app (web UI is mobile-responsive)
- Voice input/output
- Plugin marketplace / remote plugin installation
- RAG / vector database (skills system serves this role at current scale)

---

## 10. Open Questions

1. **Hot-reload vs restart for model changes?** Changing Ollama model might require reconnecting. Changing Claude API key can be instant. Should we support both?
2. **Admin as separate page or expanded panel?** Separate page is cleaner for complex management. Panel is quicker for simple tweaks. Recommendation: both — panel for quick settings, full page for deep management.
3. **Encryption key management** — `.nexus_secret` file is simple but not ideal. Alternative: derive from a user-chosen password? Adds friction but is more secure.
4. **Plugin sandboxing** — how far do we go? Current approach trusts plugins completely. Should we add permission scoping (e.g. plugin X can only access network, not filesystem)?
