"""App factory and lifespan — creates the FastAPI application."""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from auth import (
    AuthAuditLog,
    IPSecurity,
    JWTManager,
    OAuthManager,
    UserManager,
)
from config_manager import MODEL_KEYS, ConfigManager
from core.security import init_allowed_dirs, validate_path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from middleware import (
    AuditMiddleware,
    AuthMiddleware,
    RateLimitMiddleware,
    register_exception_handlers,
)
from models.claude_client import ClaudeClient
from models.claude_code_client import ClaudeCodeClient
from models.ollama_client import OllamaClient
from models.router import ModelRouter
from plugins.manager import PluginManager
from skills.engine import SkillsEngine
from skills.ingest import get_ingest_prompt, read_file
from storage.database import Database
from storage.encryption import init as init_encryption
from storage.engine import dispose_engine, get_session_factory, init_engine
from tasks.queue import TaskQueue

logger = logging.getLogger("nexus")

# ── Logging setup ──
from core.logging_config import ContextFilter, JSONFormatter

LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

_context_filter = ContextFilter()

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
_console_handler.addFilter(_context_filter)

_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_log_dir, exist_ok=True)

# Human-readable log (existing)
_file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(_log_dir, "access.log"),
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
)
_file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
_file_handler.addFilter(_context_filter)

# Structured JSON log (new — JSON Lines format for machine parsing)
_json_handler = logging.handlers.RotatingFileHandler(
    os.path.join(_log_dir, "nexus.jsonl"),
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
)
_json_handler.setFormatter(JSONFormatter())
_json_handler.addFilter(_context_filter)

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler, _json_handler])


# ── Application State ──


@dataclass
class AppState:
    """Holds all runtime state for the Nexus application."""

    cfg: ConfigManager = None
    db: Database = None
    skills_engine: SkillsEngine = None
    model_router: ModelRouter = None
    task_queue: TaskQueue = None
    plugin_manager: PluginManager = None
    tool_executor: Any = None
    telegram_channel: Any = None
    jwt_manager: JWTManager = None
    oauth_manager: OAuthManager = None
    user_manager: UserManager = None
    ip_security: IPSecurity = None
    audit_log: AuthAuditLog = None
    allowed_origins: list = field(default_factory=list)
    base_dir: str = ""


# ── Task Handlers ──


async def _handle_research_task(payload: dict, state: AppState) -> str:
    topic = payload.get("topic", "")
    logger.info(f"Researching: {topic}")
    prompt = state.skills_engine.get_research_prompt(topic)
    result = await state.model_router.chat(
        messages=[{"role": "user", "content": prompt}],
        system="You are a thorough research analyst. Provide well-structured, accurate information.",
        force_model="claude",
    )
    parsed = state.skills_engine.parse_research_output(result["content"])
    skill = await state.skills_engine.create_knowledge_skill(**parsed)
    return f"Created skill: {skill['name']} ({skill['id']})"


async def _handle_ingest_task(payload: dict, state: AppState) -> str:
    file_path = payload.get("path", "")
    filename = payload.get("name", os.path.basename(file_path))
    try:
        file_path = validate_path(file_path)
    except Exception as exc:
        logger.warning(f"Blocked ingest -- {exc}")
        return f"Blocked: {exc}"
    logger.info(f"Ingesting document: {filename}")
    content = read_file(file_path)
    if content.startswith("["):
        return f"Failed to read file: {content}"
    prompt = get_ingest_prompt(filename, content)
    result = await state.model_router.chat(
        messages=[{"role": "user", "content": prompt}],
        system="You are a knowledge analyst. Extract structured knowledge from documents thoroughly and accurately.",
        force_model="claude",
    )
    parsed = state.skills_engine.parse_research_output(result["content"])
    skill = await state.skills_engine.create_knowledge_skill(**parsed)
    return f"Created skill from '{filename}': {skill['name']} ({skill['id']})"


# ── Model Reconnection ──


async def _on_model_settings_changed(key, old_value, new_value, state: AppState):
    logger.info(f"Model setting changed: {key} -- reconnecting models")
    ollama = OllamaClient(state.cfg.ollama_base_url, state.cfg.ollama_model)
    claude = ClaudeClient(state.cfg.anthropic_api_key, state.cfg.claude_model) if state.cfg.has_anthropic else None

    # Preserve Claude Code client (it's config-driven, not key-driven)
    claude_code = state.model_router.claude_code if state.model_router else None
    if state.cfg.get_bool("CLAUDE_CODE_ENABLED", False) and not claude_code:
        mcp_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp", "mcp_config.json")
        claude_code = ClaudeCodeClient(
            cli_path=state.cfg.get("CLAUDE_CODE_CLI_PATH", "/opt/homebrew/bin/claude"),
            model=state.cfg.get("CLAUDE_CODE_MODEL", "sonnet"),
            mcp_config_path=mcp_config_path,
        )

    state.model_router = ModelRouter(ollama, claude, claude_code, state.cfg.complexity_threshold)
    await state.model_router.check_availability()
    if state.plugin_manager:
        state.plugin_manager.router = state.model_router


def _discover_catalog_sources(cfg) -> list[str]:
    """Find external skill catalog directories (anti-gravity, etc.).

    Checks:
    1. SKILL_CATALOG_SOURCES config setting (comma-separated paths)
    2. Well-known locations: ~/antigravity-awesome-skills, ~/.agent/skills
    """
    sources: list[str] = []

    # Explicit config
    explicit = cfg.get("SKILL_CATALOG_SOURCES", "")
    if explicit:
        for path in explicit.split(","):
            path = path.strip()
            if path and os.path.isdir(path):
                sources.append(path)

    # Auto-discover well-known locations
    home = os.path.expanduser("~")
    well_known = [
        os.path.join(home, "antigravity-awesome-skills"),
        os.path.join(home, ".agent", "skills"),
    ]
    for path in well_known:
        if os.path.isdir(path) and path not in sources:
            sources.append(path)

    return sources


# ── Lifespan ──


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    database_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/nexus")

    state = AppState(base_dir=base_dir)

    logger.info("Starting Nexus v2...")

    # Security: initialize allowed directories
    init_allowed_dirs(base_dir)

    # Encryption
    init_encryption(base_dir)

    # Database engine + connection pool
    os.makedirs(os.path.join(base_dir, "data"), exist_ok=True)
    init_engine(database_url)
    session_factory = get_session_factory()
    logger.info("Database engine initialized")

    # Config Manager
    state.cfg = ConfigManager(session_factory, base_dir)
    await state.cfg.connect()

    env_path = os.path.join(base_dir, ".env")
    await state.cfg.migrate_from_env(env_path)
    await state.cfg.seed_defaults()

    # Subscribe model reconnection
    state.cfg.subscribe(
        MODEL_KEYS,
        lambda k, old, new: asyncio.ensure_future(_on_model_settings_changed(k, old, new, state)),
    )

    # Ensure directories
    os.makedirs(state.cfg.skills_dir, exist_ok=True)
    os.makedirs(state.cfg.data_dir, exist_ok=True)
    os.makedirs(state.cfg.docs_dir, exist_ok=True)

    # Database
    state.db = Database(session_factory)
    await state.db.ensure_summary_table()
    await state.db.ensure_work_items_table()
    logger.info("Database connected")

    # Work Registry (unified work item tracking)
    from core.work_registry import work_registry
    from websocket_manager import websocket_manager

    work_registry.init(state.db, websocket_manager)

    # Auth system
    secret_path = os.path.join(base_dir, ".nexus_secret")
    with open(secret_path, "rb") as f:
        nexus_secret = f.read().strip()
    state.jwt_manager = JWTManager(session_factory, nexus_secret, state.cfg.jwt_access_ttl, state.cfg.jwt_refresh_ttl)
    state.oauth_manager = OAuthManager(state.cfg)
    state.user_manager = UserManager(session_factory)
    state.ip_security = IPSecurity(session_factory)
    await state.ip_security.load_blocked_ips()
    state.audit_log = AuthAuditLog(session_factory)
    logger.info(f"Auth system initialized (enabled={state.cfg.auth_enabled})")

    # Model clients
    ollama = OllamaClient(state.cfg.ollama_base_url, state.cfg.ollama_model)
    claude = ClaudeClient(state.cfg.anthropic_api_key, state.cfg.claude_model) if state.cfg.has_anthropic else None

    # Claude Code CLI client (subprocess-based, with MCP tools)
    mcp_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp", "mcp_config.json")
    claude_code = None
    if state.cfg.get_bool("CLAUDE_CODE_ENABLED", False):
        claude_code_cli = state.cfg.get("CLAUDE_CODE_CLI_PATH", "/opt/homebrew/bin/claude")
        claude_code_model = state.cfg.get("CLAUDE_CODE_MODEL", "sonnet")
        claude_code = ClaudeCodeClient(
            cli_path=claude_code_cli,
            model=claude_code_model,
            mcp_config_path=mcp_config_path,
            timeout=300,
        )
        logger.info(f"Claude Code client configured (cli={claude_code_cli}, model={claude_code_model})")

    state.model_router = ModelRouter(ollama, claude, claude_code, state.cfg.complexity_threshold)
    await state.model_router.check_availability()

    # Skills
    state.skills_engine = SkillsEngine(state.cfg.skills_dir, state.db, config_manager=state.cfg)
    await state.skills_engine.load_all()

    # Skill Catalog (external skill sources — anti-gravity, etc.)
    from skills.catalog import SkillCatalog

    catalog_sources = _discover_catalog_sources(state.cfg)
    state.skill_catalog = SkillCatalog(
        sources=catalog_sources,
        installed_dir=state.cfg.skills_dir,
    )
    if catalog_sources:
        count = state.skill_catalog.load_index()
        logger.info(f"Skill catalog: {count} skills from {len(catalog_sources)} source(s)")
    else:
        logger.info("Skill catalog: no external sources found")

    # Task queue
    state.task_queue = TaskQueue(state.db, state.cfg.max_research_tasks)
    state.task_queue.register_handler("research", lambda p: _handle_research_task(p, state))
    state.task_queue.register_handler("ingest", lambda p: _handle_ingest_task(p, state))

    # Register periodic tasks and start scheduler
    state.task_queue.register_periodic(
        name="self_improvement",
        task_type="research",
        interval_seconds=24 * 60 * 60,  # Every 24 hours
        payload={"topic": "self-improvement review", "auto": True},
        enabled=False,  # Enable via admin when ready
    )
    state.task_queue.start_scheduler()

    # Plugins
    state.plugin_manager = PluginManager(state.cfg, state.db, state.model_router)
    await state.plugin_manager.discover_and_load()

    # Inject catalog into catalog plugin (after plugin discovery)
    catalog_plugin = state.plugin_manager.plugins.get("catalog")
    if catalog_plugin and hasattr(catalog_plugin, "set_catalog"):
        catalog_plugin.set_catalog(state.skill_catalog, state.skills_engine)

    # Headless browser renderer (Playwright — lazy init on first use)
    try:
        from core.headless import HeadlessRenderer
        state.headless_renderer = HeadlessRenderer()
        # Inject into Brave plugin for auto-fallback on JS-heavy sites
        brave_plugin = state.plugin_manager.plugins.get("brave")
        if brave_plugin and hasattr(brave_plugin, "set_headless"):
            brave_plugin.set_headless(state.headless_renderer)
            logger.info("Headless renderer available for web_fetch fallback")
        else:
            logger.info("Headless renderer initialized (no Brave plugin to inject into)")
    except ImportError:
        state.headless_renderer = None
        logger.info("Headless renderer: Playwright not installed (optional)")

    # Tool executor (Phase 6)
    try:
        from core.tool_executor import ToolExecutor

        state.tool_executor = ToolExecutor(state.plugin_manager, state.skills_engine)
    except ImportError:
        state.tool_executor = None

    # CORS origins
    _allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080")
    state.allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]

    # Admin API
    from admin import init as admin_init

    admin_init(
        state.cfg,
        state.plugin_manager,
        state.model_router,
        state.db,
        state.task_queue,
        state.skills_engine,
        jwt_manager=state.jwt_manager,
        user_manager=state.user_manager,
        ip_security=state.ip_security,
        audit_log=state.audit_log,
        skill_catalog=state.skill_catalog,
        work_registry=work_registry,
    )

    # Telegram (optional)
    if state.cfg.has_telegram:
        try:
            from channels.telegram import TelegramChannel
            from core.message_processor import get_status, process_message

            async def tg_handler(user_id: str, text: str, conv_id: str = None) -> str:
                return await process_message(
                    user_id,
                    text,
                    cfg=state.cfg,
                    db=state.db,
                    skills_engine=state.skills_engine,
                    model_router=state.model_router,
                    task_queue=state.task_queue,
                    plugin_manager=state.plugin_manager,
                    skill_catalog=getattr(state, "skill_catalog", None),
                    conv_id=conv_id,
                    passive_memory=getattr(state, "passive_memory", None),
                )

            state.telegram_channel = TelegramChannel(
                state.cfg.telegram_bot_token,
                state.db,
                tg_handler,
                agent_name=state.cfg.agent_name,
            )
            await state.telegram_channel.start(
                status_fn=lambda: get_status(
                    state.model_router,
                    state.plugin_manager,
                    state.task_queue,
                    state.skills_engine,
                )
            )
            logger.info("Telegram bot started")
        except Exception as e:
            logger.warning(f"Telegram failed to start: {e}")

    # Passive Memory Extractor — auto-learns from conversations
    try:
        from core.passive_memory import PassiveMemoryExtractor
        state.passive_memory = PassiveMemoryExtractor(state.db)
        logger.info("Passive memory extractor initialized")
    except Exception as e:
        state.passive_memory = None
        logger.warning(f"Passive memory failed to initialize: {e}")

    # Reminder Manager — scheduled user reminders
    try:
        from core.reminders import ReminderManager

        async def _on_reminder_fire(reminder):
            """Deliver a reminder to all connected WebSocket clients."""
            from websocket_manager import websocket_manager
            msg = {
                "type": "system",
                "content": f"⏰ **Reminder:** {reminder.message}",
            }
            # Send to all connected clients (broadcast)
            for ws_id in list(websocket_manager._connections.keys()):
                try:
                    await websocket_manager.send_to_client(ws_id, msg)
                except Exception:
                    pass
            logger.info(f"Reminder delivered: {reminder.id} — {reminder.message}")

        state.reminder_manager = ReminderManager(on_fire=_on_reminder_fire)
        state.reminder_manager.start()
        logger.info("Reminder manager started")
    except Exception as e:
        state.reminder_manager = None
        logger.warning(f"Reminder manager failed to initialize: {e}")

    # Expose state on the app
    app.state.nexus = state

    logger.info(f"Nexus v2 ready at http://{state.cfg.host}:{state.cfg.port}")
    yield

    # ── Shutdown ──
    logger.info("Shutting down...")
    if getattr(state, "headless_renderer", None):
        await state.headless_renderer.close()
    if getattr(state, "reminder_manager", None):
        state.reminder_manager.stop()
    if getattr(state, "task_queue", None):
        state.task_queue.stop_scheduler()
    if state.plugin_manager:
        await state.plugin_manager.shutdown_all()
    if state.telegram_channel:
        await state.telegram_channel.stop()
    await dispose_engine()


# ── App Factory ──


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Nexus", lifespan=lifespan)

    # Import and include routers
    from admin import router as admin_router
    from routers import api as api_router_mod
    from routers import frontend as frontend_router_mod
    from routers import ws as ws_router_mod

    # Initialize frontend with base_dir
    load_dotenv()
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_router_mod.init(base_dir)

    app.include_router(admin_router)
    app.include_router(api_router_mod.router)
    app.include_router(ws_router_mod.router)
    app.include_router(frontend_router_mod.router)

    # Register exception handlers
    register_exception_handlers(app)

    # Middleware (order: outermost first in add_middleware calls,
    # but Starlette processes them in reverse — last added is outermost)
    _allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080")
    allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]

    app.add_middleware(AuthMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AuditMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app
