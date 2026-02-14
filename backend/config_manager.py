"""Database-backed live configuration (PostgreSQL).

Settings are stored in PostgreSQL, encrypted where sensitive, and can be
changed at runtime without restarting the server.  Components can
subscribe to key changes and react immediately.

On first boot the manager migrates values from .env into the database
so that existing installations carry over seamlessly.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from storage.encryption import decrypt, encrypt
from storage.models import Setting, SettingsAudit

logger = logging.getLogger("nexus.config")

# ── Schema: every setting the platform knows about ──────────────
# key, default, encrypted?, category, label, field_type, description, extra
SETTINGS_SCHEMA: list[dict] = [
    # Models
    {
        "key": "ANTHROPIC_API_KEY",
        "default": "",
        "encrypted": True,
        "category": "Models",
        "label": "Anthropic API Key",
        "type": "password",
        "description": "Your Claude API key from console.anthropic.com",
    },
    {
        "key": "CLAUDE_MODEL",
        "default": "claude-sonnet-4-20250514",
        "encrypted": False,
        "category": "Models",
        "label": "Claude Model",
        "type": "select",
        "description": "Which Claude model to use",
        "options": ["claude-sonnet-4-20250514", "claude-haiku-4-20250414", "claude-opus-4-20250514"],
    },
    {
        "key": "OLLAMA_BASE_URL",
        "default": "http://localhost:11434",
        "encrypted": False,
        "category": "Models",
        "label": "Ollama URL",
        "type": "text",
        "description": "Ollama server address",
    },
    {
        "key": "OLLAMA_MODEL",
        "default": "kimi-k2.5:cloud",
        "encrypted": False,
        "category": "Models",
        "label": "Ollama Model",
        "type": "text",
        "description": "Local model name (e.g. llama3.1, kimi-k2.5:cloud)",
    },
    # Claude Code (headless CLI)
    {
        "key": "CLAUDE_CODE_ENABLED",
        "default": "false",
        "encrypted": False,
        "category": "Models",
        "label": "Enable Claude Code",
        "type": "select",
        "description": "Enable Claude Code CLI as a third model provider (requires claude CLI installed)",
        "options": ["false", "true"],
    },
    {
        "key": "CLAUDE_CODE_CLI_PATH",
        "default": "/opt/homebrew/bin/claude",
        "encrypted": False,
        "category": "Models",
        "label": "Claude Code CLI Path",
        "type": "text",
        "description": "Path to the Claude Code CLI binary",
    },
    {
        "key": "CLAUDE_CODE_MODEL",
        "default": "sonnet",
        "encrypted": False,
        "category": "Models",
        "label": "Claude Code Model",
        "type": "select",
        "description": "Which Claude model to use in Claude Code mode",
        "options": ["sonnet", "opus", "haiku"],
    },
    # Routing
    {
        "key": "COMPLEXITY_THRESHOLD",
        "default": "60",
        "encrypted": False,
        "category": "Routing",
        "label": "Complexity Threshold",
        "type": "range",
        "description": "0 = always Claude, 100 = always local. Score above this → Claude.",
        "min": 0,
        "max": 100,
    },
    # Sub-Agent Orchestration
    {
        "key": "SUB_AGENT_ENABLED",
        "default": "true",
        "encrypted": False,
        "category": "Sub-Agents",
        "label": "Enable Sub-Agents",
        "type": "select",
        "description": "Allow Aries to spawn parallel sub-agents for research, build/review, and verification",
        "options": ["true", "false"],
    },
    {
        "key": "SUB_AGENT_AUTO_ENABLED",
        "default": "false",
        "encrypted": False,
        "category": "Sub-Agents",
        "label": "Auto-Detect Multi-Part Questions",
        "type": "select",
        "description": "Automatically detect multi-part requests and spawn sub-agents (experimental)",
        "options": ["false", "true"],
    },
    {
        "key": "SUB_AGENT_MAX_CONCURRENT",
        "default": "4",
        "encrypted": False,
        "category": "Sub-Agents",
        "label": "Max Concurrent Sub-Agents",
        "type": "number",
        "description": "Maximum sub-agents running in parallel (all model types)",
        "min": 1,
        "max": 8,
    },
    {
        "key": "SUB_AGENT_CLAUDE_CODE_CONCURRENT",
        "default": "2",
        "encrypted": False,
        "category": "Sub-Agents",
        "label": "Max Concurrent Claude Code Sub-Agents",
        "type": "number",
        "description": "Maximum Claude Code subprocesses (each uses ~200-500MB RAM)",
        "min": 1,
        "max": 4,
    },
    {
        "key": "SUB_AGENT_BUILDER_MODEL",
        "default": "",
        "encrypted": False,
        "category": "Sub-Agents",
        "label": "Default Builder Model",
        "type": "select",
        "description": "Model for builder sub-agents (empty = auto-route)",
        "options": ["", "ollama", "claude", "claude_code"],
    },
    {
        "key": "SUB_AGENT_REVIEWER_MODEL",
        "default": "claude",
        "encrypted": False,
        "category": "Sub-Agents",
        "label": "Default Reviewer Model",
        "type": "select",
        "description": "Model for reviewer sub-agents",
        "options": ["claude", "ollama", "claude_code"],
    },
    {
        "key": "SUB_AGENT_CODE_BUILDER_MODEL",
        "default": "claude_code",
        "encrypted": False,
        "category": "Sub-Agents",
        "label": "Code Builder Model",
        "type": "select",
        "description": "Model for code build sub-agents (full MCP tool access)",
        "options": ["claude_code", "claude", "ollama"],
    },
    {
        "key": "SUB_AGENT_CODE_REVIEWER_MODEL",
        "default": "claude_code",
        "encrypted": False,
        "category": "Sub-Agents",
        "label": "Code Reviewer Model",
        "type": "select",
        "description": "Model for code review sub-agents (can read files, run tests)",
        "options": ["claude_code", "claude", "ollama"],
    },
    {
        "key": "SUB_AGENT_TIMEOUT",
        "default": "120",
        "encrypted": False,
        "category": "Sub-Agents",
        "label": "Sub-Agent Timeout (seconds)",
        "type": "number",
        "description": "Per-sub-agent timeout (Claude Code gets 300s automatically)",
        "min": 30,
        "max": 600,
    },
    # Files
    {
        "key": "DOCS_DIR",
        "default": "",
        "encrypted": False,
        "category": "Files",
        "label": "Documents Directory",
        "type": "text",
        "description": "Folder path for document ingestion",
    },
    # Tasks
    {
        "key": "MAX_RESEARCH_TASKS",
        "default": "3",
        "encrypted": False,
        "category": "Tasks",
        "label": "Max Concurrent Tasks",
        "type": "number",
        "description": "Maximum background tasks running at once",
        "min": 1,
        "max": 10,
    },
    # Plugins
    {
        "key": "GITHUB_TOKEN",
        "default": "",
        "encrypted": True,
        "category": "Plugins",
        "label": "GitHub Token",
        "type": "password",
        "description": "Personal access token from github.com/settings/tokens",
    },
    {
        "key": "TELEGRAM_BOT_TOKEN",
        "default": "",
        "encrypted": True,
        "category": "Plugins",
        "label": "Telegram Bot Token",
        "type": "password",
        "description": "Bot token from @BotFather",
    },
    {
        "key": "TELEGRAM_ALLOWED_USERS",
        "default": "",
        "encrypted": False,
        "category": "Plugins",
        "label": "Telegram Allowed Users (Legacy)",
        "type": "text",
        "description": "Legacy allowlist. Use pairing codes instead (Link Telegram in chat UI).",
    },
    # RAG & Knowledge Systems
    {
        "key": "RAG_ENABLED",
        "default": "true",
        "encrypted": False,
        "category": "Memory",
        "label": "Enable RAG",
        "type": "select",
        "description": "Retrieval-Augmented Generation — enriches responses with relevant memories",
        "options": ["true", "false"],
    },
    {
        "key": "EMBEDDING_MODEL",
        "default": "nomic-embed-text",
        "encrypted": False,
        "category": "Memory",
        "label": "Embedding Model",
        "type": "text",
        "description": "Ollama model for generating embeddings (768-dim for nomic-embed-text)",
    },
    {
        "key": "EMBEDDING_DIMS",
        "default": "768",
        "encrypted": False,
        "category": "Memory",
        "label": "Embedding Dimensions",
        "type": "number",
        "description": "Vector dimensions (768 for nomic-embed-text, 1536 for OpenAI)",
        "min": 128,
        "max": 4096,
    },
    {
        "key": "RAG_MAX_RESULTS",
        "default": "5",
        "encrypted": False,
        "category": "Memory",
        "label": "RAG Max Results",
        "type": "number",
        "description": "Maximum memories retrieved per query",
        "min": 1,
        "max": 20,
    },
    {
        "key": "RAG_AUTO_INGEST",
        "default": "true",
        "encrypted": False,
        "category": "Memory",
        "label": "Auto-Ingest Conversations",
        "type": "select",
        "description": "Automatically store conversation turns for future retrieval",
        "options": ["true", "false"],
    },
    {
        "key": "KNOWLEDGE_GRAPH_ENABLED",
        "default": "true",
        "encrypted": False,
        "category": "Memory",
        "label": "Enable Knowledge Graph",
        "type": "select",
        "description": "Extract entities and relationships from conversations",
        "options": ["true", "false"],
    },
    # Mem0 (Long-term Memory)
    {
        "key": "MEM0_API_KEY",
        "default": "",
        "encrypted": True,
        "category": "Memory",
        "label": "Mem0 API Key",
        "type": "password",
        "description": "API key from app.mem0.ai (leave blank for open-source mode)",
    },
    {
        "key": "MEM0_USER_ID",
        "default": "default",
        "encrypted": False,
        "category": "Memory",
        "label": "Mem0 User ID",
        "type": "text",
        "description": "User identifier for memory scoping",
    },
    # Google Search
    {
        "key": "GOOGLE_API_KEY",
        "default": "",
        "encrypted": True,
        "category": "Search",
        "label": "Google API Key",
        "type": "password",
        "description": "Google Custom Search API key",
    },
    {
        "key": "GOOGLE_CSE_ID",
        "default": "",
        "encrypted": False,
        "category": "Search",
        "label": "Google CSE ID",
        "type": "text",
        "description": "Google Custom Search Engine ID",
    },
    # Server (bootstrap — also in .env)
    {
        "key": "HOST",
        "default": "127.0.0.1",
        "encrypted": False,
        "category": "Server",
        "label": "Server Host",
        "type": "text",
        "description": "Bind address (127.0.0.1 = local, 0.0.0.0 = network)",
    },
    {
        "key": "PORT",
        "default": "8080",
        "encrypted": False,
        "category": "Server",
        "label": "Server Port",
        "type": "number",
        "description": "Port number",
        "min": 1024,
        "max": 65535,
    },
    {
        "key": "TIMEZONE",
        "default": "",
        "encrypted": False,
        "category": "Server",
        "label": "Timezone",
        "type": "text",
        "description": "IANA timezone (e.g. Asia/Dubai, Europe/London). Leave blank for auto-detect.",
    },
    # Persona
    {
        "key": "AGENT_NAME",
        "default": "Nexus",
        "encrypted": False,
        "category": "Persona",
        "label": "Agent Name",
        "type": "text",
        "description": "The name the agent uses to identify itself",
    },
    {
        "key": "CUSTOM_SYSTEM_PROMPT",
        "default": "",
        "encrypted": False,
        "category": "Persona",
        "label": "Custom Instructions",
        "type": "textarea",
        "description": "Extra instructions appended to the system prompt",
    },
    {
        "key": "PERSONA_TONE",
        "default": "balanced",
        "encrypted": False,
        "category": "Persona",
        "label": "Response Tone",
        "type": "select",
        "description": "Overall tone for responses",
        "options": ["professional", "balanced", "casual", "technical"],
    },
    # Authentication
    {
        "key": "ADMIN_ACCESS_KEY",
        "default": "",
        "encrypted": True,
        "category": "Authentication",
        "label": "Admin Console Access Key",
        "type": "password",
        "description": "Bearer token for admin API access. Set this to protect the /admin dashboard.",
    },
    {
        "key": "AUTH_ENABLED",
        "default": "false",
        "encrypted": False,
        "category": "Authentication",
        "label": "Enable Auth",
        "type": "select",
        "description": "Require login to access Nexus (restart required)",
        "options": ["false", "true"],
    },
    {
        "key": "GOOGLE_CLIENT_ID",
        "default": "",
        "encrypted": False,
        "category": "Authentication",
        "label": "Google Client ID",
        "type": "text",
        "description": "OAuth 2.0 client ID from Google Cloud Console",
    },
    {
        "key": "GOOGLE_CLIENT_SECRET",
        "default": "",
        "encrypted": True,
        "category": "Authentication",
        "label": "Google Client Secret",
        "type": "password",
        "description": "OAuth 2.0 client secret from Google Cloud Console",
    },
    {
        "key": "AUTH_WHITELIST_MODE",
        "default": "open",
        "encrypted": False,
        "category": "Authentication",
        "label": "Whitelist Mode",
        "type": "select",
        "description": "Who can sign in: open = anyone with Google, whitelist = pre-approved emails only",
        "options": ["open", "whitelist"],
    },
    {
        "key": "JWT_ACCESS_TTL",
        "default": "1800",
        "encrypted": False,
        "category": "Authentication",
        "label": "Access Token TTL (s)",
        "type": "number",
        "description": "Access token lifetime in seconds (default 1800 = 30 min)",
        "min": 300,
        "max": 86400,
    },
    {
        "key": "JWT_REFRESH_TTL",
        "default": "604800",
        "encrypted": False,
        "category": "Authentication",
        "label": "Refresh Token TTL (s)",
        "type": "number",
        "description": "Refresh token lifetime in seconds (default 604800 = 7 days)",
        "min": 3600,
        "max": 2592000,
    },
    # Clustering (Phase 6)
    {
        "key": "CLUSTER_ENABLED",
        "default": "false",
        "encrypted": False,
        "category": "Clustering",
        "label": "Enable Agent Clustering",
        "type": "select",
        "description": "Enable Redis-based agent clustering for multi-instance coordination (requires Redis)",
        "options": ["false", "true"],
    },
    {
        "key": "REDIS_URL",
        "default": "redis://localhost:6379",
        "encrypted": False,
        "category": "Clustering",
        "label": "Redis URL",
        "type": "text",
        "description": "Redis connection URL (e.g. redis://localhost:6379, redis://user:pass@host:port)",
    },
    {
        "key": "REDIS_PASSWORD",
        "default": "",
        "encrypted": True,
        "category": "Clustering",
        "label": "Redis Password",
        "type": "password",
        "description": "Redis authentication password (if required)",
    },
    {
        "key": "REDIS_TLS",
        "default": "false",
        "encrypted": False,
        "category": "Clustering",
        "label": "Redis TLS",
        "type": "select",
        "description": "Enable TLS/SSL for Redis connection",
        "options": ["false", "true"],
    },
    {
        "key": "REDIS_KEY_PREFIX",
        "default": "nexus:",
        "encrypted": False,
        "category": "Clustering",
        "label": "Redis Key Prefix",
        "type": "text",
        "description": "Namespace prefix for all Redis keys (useful for shared Redis instances)",
    },
    {
        "key": "CLUSTER_AGENT_ID",
        "default": "",
        "encrypted": False,
        "category": "Clustering",
        "label": "Agent ID",
        "type": "text",
        "description": "Unique identifier for this agent instance (auto-generated if blank)",
    },
    {
        "key": "CLUSTER_ROLE",
        "default": "auto",
        "encrypted": False,
        "category": "Clustering",
        "label": "Agent Role",
        "type": "select",
        "description": "Role assignment: auto = first agent becomes primary, rest secondary",
        "options": ["auto", "primary", "secondary"],
    },
    {
        "key": "CLUSTER_MAX_LOAD",
        "default": "20",
        "encrypted": False,
        "category": "Clustering",
        "label": "Max Concurrent Load",
        "type": "number",
        "description": "Maximum concurrent requests this agent can handle",
        "min": 1,
        "max": 100,
    },
    {
        "key": "CLUSTER_HEARTBEAT_INTERVAL",
        "default": "2",
        "encrypted": False,
        "category": "Clustering",
        "label": "Heartbeat Interval (s)",
        "type": "number",
        "description": "Seconds between heartbeat pings to Redis",
        "min": 1,
        "max": 30,
    },
    {
        "key": "CLUSTER_FAILURE_THRESHOLD",
        "default": "3",
        "encrypted": False,
        "category": "Clustering",
        "label": "Failure Threshold",
        "type": "number",
        "description": "Missed heartbeats before an agent is considered failed",
        "min": 2,
        "max": 10,
    },
    {
        "key": "CLUSTER_ELECTION_TIMEOUT",
        "default": "5",
        "encrypted": False,
        "category": "Clustering",
        "label": "Election Timeout (s)",
        "type": "number",
        "description": "Seconds to wait for election to complete during failover",
        "min": 2,
        "max": 30,
    },
    # Setup
    {
        "key": "SETUP_COMPLETE",
        "default": "false",
        "encrypted": False,
        "category": "System",
        "label": "Setup Complete",
        "type": "select",
        "description": "Whether the initial setup wizard has been completed",
        "options": ["false", "true"],
    },
]

# Build a fast lookup
_SCHEMA_MAP = {s["key"]: s for s in SETTINGS_SCHEMA}
SENSITIVE_KEYS = {s["key"] for s in SETTINGS_SCHEMA if s.get("encrypted")}

# Keys whose change triggers model reconnection
MODEL_KEYS = {
    "ANTHROPIC_API_KEY", "CLAUDE_MODEL", "OLLAMA_BASE_URL", "OLLAMA_MODEL",
    "COMPLEXITY_THRESHOLD", "CLAUDE_CODE_ENABLED", "CLAUDE_CODE_CLI_PATH", "CLAUDE_CODE_MODEL",
}

# Keys whose change triggers cluster reconnection
CLUSTER_KEYS = {
    "CLUSTER_ENABLED", "REDIS_URL", "REDIS_PASSWORD", "REDIS_TLS",
    "REDIS_KEY_PREFIX", "CLUSTER_AGENT_ID", "CLUSTER_ROLE",
    "CLUSTER_MAX_LOAD", "CLUSTER_HEARTBEAT_INTERVAL", "CLUSTER_FAILURE_THRESHOLD",
    "CLUSTER_ELECTION_TIMEOUT",
}


class ConfigManager:
    """Live, database-backed configuration (PostgreSQL via SQLAlchemy)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], base_dir: str):
        self._session_factory = session_factory
        self.base_dir = base_dir
        self._cache: dict[str, str] = {}
        self._subscribers: list[tuple[set, Callable]] = []

    # ── Lifecycle ────────────────────────────────────────────────

    async def initialize(self):
        """Load settings cache. Tables are created by Alembic migrations."""
        await self._load_cache()
        logger.info(f"ConfigManager ready — {len(self._cache)} settings loaded")

    # Keep connect() as alias for backward compatibility
    async def connect(self):
        await self.initialize()

    async def close(self):
        """No-op. Engine lifecycle is external."""
        pass

    async def _load_cache(self):
        """Load all values into an in-memory dict for fast reads."""
        async with self._session_factory() as session:
            result = await session.execute(select(Setting))
            rows = result.scalars().all()
            for row in rows:
                val = decrypt(row.value) if row.encrypted and row.value else row.value
                self._cache[row.key] = val

    # ── .env Migration ──────────────────────────────────────────

    async def migrate_from_env(self, env_path: str):
        """One-time import: read .env values into the settings DB.
        Only writes keys that don't already exist in the database."""
        if not os.path.exists(env_path):
            return 0

        from dotenv import dotenv_values

        env = dotenv_values(env_path)

        imported = 0
        for key, value in env.items():
            if not value or value == "sk-ant-your-key-here":
                continue
            # Only import if key is known and not already in DB
            if key in _SCHEMA_MAP and key not in self._cache:
                await self.set(key, value, changed_by="migration")
                imported += 1

        if imported:
            logger.info(f"Migrated {imported} settings from .env")
        return imported

    async def seed_defaults(self):
        """Ensure every schema key exists in the database with its default."""
        for s in SETTINGS_SCHEMA:
            if s["key"] not in self._cache:
                default = s["default"]
                # For DOCS_DIR, resolve relative to base_dir
                if s["key"] == "DOCS_DIR" and not default:
                    default = os.path.join(self.base_dir, "docs_input")
                await self.set(s["key"], default, changed_by="system")

    # ── Read ────────────────────────────────────────────────────

    def get(self, key: str, default: str = "") -> str:
        """Get a setting value (from cache — instant)."""
        return self._cache.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self._cache.get(key, str(default)))
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        v = self._cache.get(key, "").lower()
        if v in ("1", "true", "yes"):
            return True
        if v in ("0", "false", "no", ""):
            return default
        return default

    def get_section(self, category: str) -> dict:
        """Get all settings in a category."""
        return {s["key"]: self.get(s["key"]) for s in SETTINGS_SCHEMA if s["category"] == category}

    # ── Write ───────────────────────────────────────────────────

    async def set(self, key: str, value: str, changed_by: str = "admin"):
        """Set a value — writes to DB, updates cache, notifies subscribers."""
        schema = _SCHEMA_MAP.get(key)
        is_encrypted = schema.get("encrypted", False) if schema else False
        category = schema.get("category", "general") if schema else "general"

        old_value = self._cache.get(key)
        store_value = encrypt(value) if is_encrypted and value else value
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            # PostgreSQL upsert
            stmt = (
                pg_insert(Setting)
                .values(
                    key=key,
                    value=store_value,
                    encrypted=is_encrypted,
                    category=category,
                    updated_at=now,
                    updated_by=changed_by,
                )
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={
                        "value": store_value,
                        "encrypted": is_encrypted,
                        "updated_at": now,
                        "updated_by": changed_by,
                    },
                )
            )
            await session.execute(stmt)

            # Audit (don't log actual secret values)
            audit_old = "***" if is_encrypted else (old_value or "")
            audit_new = "***" if is_encrypted else value
            session.add(
                SettingsAudit(
                    key=key,
                    old_value=audit_old,
                    new_value=audit_new,
                    changed_at=now,
                    changed_by=changed_by,
                )
            )

            await session.commit()

        self._cache[key] = value

        logger.info(f"Setting updated: {key} (by {changed_by})")
        await self._notify(key, old_value, value)

    async def set_many(self, updates: dict, changed_by: str = "admin") -> list:
        """Update multiple settings. Returns list of keys actually changed."""
        changed = []
        for key, value in updates.items():
            if key not in _SCHEMA_MAP:
                continue
            old = self._cache.get(key)
            if old != str(value):
                await self.set(key, str(value), changed_by=changed_by)
                changed.append(key)
        return changed

    # ── Subscriptions ───────────────────────────────────────────

    def subscribe(self, keys: set, callback: Callable):
        """Register a callback for when any of these keys change.
        callback(key, old_value, new_value) — can be async."""
        self._subscribers.append((keys, callback))

    async def _notify(self, key: str, old: str, new: str):
        for keys, callback in self._subscribers:
            if key in keys or "*" in keys:
                try:
                    import asyncio

                    if asyncio.iscoroutinefunction(callback):
                        await callback(key, old, new)
                    else:
                        callback(key, old, new)
                except Exception as e:
                    logger.error(f"Subscriber error for {key}: {e}")

    # ── Audit Log ───────────────────────────────────────────────

    async def get_audit_log(self, limit: int = 100) -> list[dict]:
        """Return recent settings audit entries."""
        async with self._session_factory() as session:
            result = await session.execute(select(SettingsAudit).order_by(SettingsAudit.changed_at.desc()).limit(limit))
            rows = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "key": r.key,
                    "old_value": r.old_value,
                    "new_value": r.new_value,
                    "changed_at": r.changed_at.isoformat() if r.changed_at else None,
                    "changed_by": r.changed_by,
                }
                for r in rows
            ]

    # ── API Helpers ─────────────────────────────────────────────

    def get_all_for_api(self) -> list[dict]:
        """Return all settings formatted for the admin API (masks secrets)."""
        results = []
        for s in SETTINGS_SCHEMA:
            value = self._cache.get(s["key"], s.get("default", ""))
            is_secret = s.get("encrypted", False)
            results.append(
                {
                    **{k: v for k, v in s.items() if k != "default"},
                    "value": self._mask(value) if is_secret else value,
                    "has_value": bool(value),
                }
            )
        return results

    @staticmethod
    def _mask(value: str) -> str:
        if not value:
            return ""
        return "***REDACTED***"

    @property
    def schema(self):
        return SETTINGS_SCHEMA

    # ── Convenience Properties (match old Config fields) ────────

    @property
    def anthropic_api_key(self):
        return self.get("ANTHROPIC_API_KEY")

    @property
    def claude_model(self):
        return self.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

    @property
    def ollama_base_url(self):
        return self.get("OLLAMA_BASE_URL", "http://localhost:11434")

    @property
    def ollama_model(self):
        return self.get("OLLAMA_MODEL", "kimi-k2.5:cloud")

    @property
    def complexity_threshold(self):
        return self.get_int("COMPLEXITY_THRESHOLD", 60)

    @property
    def github_token(self):
        return self.get("GITHUB_TOKEN")

    @property
    def telegram_bot_token(self):
        return self.get("TELEGRAM_BOT_TOKEN")

    @property
    def telegram_allowed_users(self):
        raw = self.get("TELEGRAM_ALLOWED_USERS", "")
        if not raw.strip():
            return []
        return [int(u.strip()) for u in raw.split(",") if u.strip()]

    @property
    def host(self):
        return self.get("HOST", "127.0.0.1")

    @property
    def port(self):
        return self.get_int("PORT", 8080)

    @property
    def max_research_tasks(self):
        return self.get_int("MAX_RESEARCH_TASKS", 3)

    @property
    def agent_name(self):
        return self.get("AGENT_NAME", "Nexus")

    @property
    def custom_system_prompt(self):
        return self.get("CUSTOM_SYSTEM_PROMPT", "")

    @property
    def persona_tone(self):
        return self.get("PERSONA_TONE", "balanced")

    @property
    def docs_dir(self):
        d = self.get("DOCS_DIR")
        return d if d else os.path.join(self.base_dir, "docs_input")

    @property
    def skills_dir(self):
        return os.path.join(self.base_dir, "skills")

    @property
    def data_dir(self):
        return os.path.join(self.base_dir, "data")

    @property
    def has_anthropic(self):
        key = self.anthropic_api_key
        return bool(key and key != "sk-ant-your-key-here")

    @property
    def has_telegram(self):
        return bool(self.telegram_bot_token)

    @property
    def setup_complete(self):
        return self.get_bool("SETUP_COMPLETE", False)

    @property
    def admin_access_key(self):
        return self.get("ADMIN_ACCESS_KEY")

    @property
    def auth_enabled(self):
        return self.get_bool("AUTH_ENABLED", False)

    @property
    def google_client_id(self):
        return self.get("GOOGLE_CLIENT_ID")

    @property
    def google_client_secret(self):
        return self.get("GOOGLE_CLIENT_SECRET")

    @property
    def auth_whitelist_mode(self):
        return self.get("AUTH_WHITELIST_MODE", "open")

    @property
    def jwt_access_ttl(self):
        return self.get_int("JWT_ACCESS_TTL", 1800)

    @property
    def jwt_refresh_ttl(self):
        return self.get_int("JWT_REFRESH_TTL", 604800)

    @property
    def timezone(self):
        return self.get("TIMEZONE", "")

    @property
    def has_oauth(self):
        return bool(self.google_client_id and self.google_client_secret)

    # ── Clustering Properties ────────────────────────────────────

    @property
    def cluster_enabled(self):
        return self.get_bool("CLUSTER_ENABLED", False)

    @property
    def redis_url(self):
        return self.get("REDIS_URL", "redis://localhost:6379")

    @property
    def redis_password(self):
        return self.get("REDIS_PASSWORD", "")

    @property
    def redis_tls(self):
        return self.get_bool("REDIS_TLS", False)

    @property
    def redis_key_prefix(self):
        return self.get("REDIS_KEY_PREFIX", "nexus:")

    @property
    def cluster_agent_id(self):
        return self.get("CLUSTER_AGENT_ID", "")

    @property
    def cluster_role(self):
        return self.get("CLUSTER_ROLE", "auto")

    @property
    def cluster_max_load(self):
        return self.get_int("CLUSTER_MAX_LOAD", 20)

    @property
    def cluster_heartbeat_interval(self):
        return self.get_int("CLUSTER_HEARTBEAT_INTERVAL", 2)

    @property
    def cluster_failure_threshold(self):
        return self.get_int("CLUSTER_FAILURE_THRESHOLD", 3)

    @property
    def cluster_election_timeout(self):
        return self.get_int("CLUSTER_ELECTION_TIMEOUT", 5)

    def get_cluster_config(self) -> dict:
        """Return all cluster settings as a dict for ClusterManager init."""
        return {
            "CLUSTER_ENABLED": self.cluster_enabled,
            "REDIS_URL": self.redis_url,
            "REDIS_PASSWORD": self.redis_password,
            "REDIS_TLS": self.redis_tls,
            "REDIS_KEY_PREFIX": self.redis_key_prefix,
            "CLUSTER_AGENT_ID": self.cluster_agent_id,
            "CLUSTER_ROLE": self.cluster_role,
            "CLUSTER_MAX_LOAD": self.cluster_max_load,
            "CLUSTER_HEARTBEAT_INTERVAL": self.cluster_heartbeat_interval,
            "CLUSTER_FAILURE_THRESHOLD": self.cluster_failure_threshold,
            "CLUSTER_ELECTION_TIMEOUT": self.cluster_election_timeout,
            "CLUSTER_VECTOR_DIMS": int(self.get("EMBEDDING_DIMS", "768")),
        }
