"""Shared test fixtures for Nexus test suite."""

import asyncio
import os
import sys
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ── Event Loop ──


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Temporary directories ──


@pytest.fixture
def tmp_base_dir(tmp_path):
    """Create a temporary base directory mimicking the Nexus project layout."""
    (tmp_path / "data").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs_input").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "frontend").mkdir()

    # Minimal frontend files
    (tmp_path / "frontend" / "index.html").write_text("<h1>Nexus Test</h1>")
    (tmp_path / "frontend" / "admin.html").write_text("<h1>Admin Test</h1>")

    return tmp_path


@pytest.fixture
def tmp_db_path(tmp_base_dir):
    """Path for a temporary test database."""
    return str(tmp_base_dir / "data" / "nexus_test.db")


# ── Database Fixture ──


@pytest_asyncio.fixture
async def test_db(tmp_db_path):
    """Create a fresh test database."""
    from storage.database import Database

    db = Database(tmp_db_path)
    await db.connect()
    yield db
    await db.close()


# ── ConfigManager Fixture ──


@pytest_asyncio.fixture
async def test_config(tmp_db_path, tmp_base_dir):
    """Create a test ConfigManager with defaults seeded."""
    from config_manager import ConfigManager
    from storage.encryption import init as init_encryption

    init_encryption(str(tmp_base_dir))

    cfg = ConfigManager(tmp_db_path, str(tmp_base_dir))
    await cfg.connect()
    await cfg.seed_defaults()
    yield cfg
    await cfg.close()


# ── Mock Model Clients ──


@pytest.fixture
def mock_ollama_client():
    """Mock OllamaClient that returns canned responses."""
    client = MagicMock()
    client.model = "test-model"
    client.is_available = AsyncMock(return_value=True)
    client.chat = AsyncMock(return_value={
        "content": "Mock Ollama response",
        "model": "test-model",
        "tokens_in": 10,
        "tokens_out": 20,
    })

    async def mock_stream(messages, system=None):
        for chunk in ["Mock ", "streamed ", "response"]:
            yield chunk

    client.chat_stream = mock_stream
    return client


@pytest.fixture
def mock_claude_client():
    """Mock ClaudeClient that returns canned responses."""
    client = MagicMock()
    client.model = "claude-test"
    client.is_available = AsyncMock(return_value=True)
    client.chat = AsyncMock(return_value={
        "content": "Mock Claude response",
        "model": "claude-test",
        "tokens_in": 15,
        "tokens_out": 25,
    })

    async def mock_stream(messages, system=None):
        for chunk in ["Mock ", "Claude ", "stream"]:
            yield chunk

    client.chat_stream = mock_stream
    return client


@pytest.fixture
def mock_model_router(mock_ollama_client, mock_claude_client):
    """Create a ModelRouter with mocked clients."""
    from models.router import ModelRouter

    router = ModelRouter(mock_ollama_client, mock_claude_client, complexity_threshold=60)
    router._ollama_available = True
    router._claude_available = True
    return router


# ── Mock Plugin Manager ──


@pytest.fixture
def mock_plugin_manager():
    """Minimal mock PluginManager."""
    pm = MagicMock()
    pm.plugins = {}
    pm.all_tools = []
    pm.status = {}
    pm.get_system_prompt_additions = MagicMock(return_value="")
    pm.list_commands = MagicMock(return_value=[])
    pm.handle_command = AsyncMock(return_value=None)
    pm.process_tool_calls = AsyncMock(return_value=("", []))
    pm.discover_and_load = AsyncMock()
    pm.shutdown_all = AsyncMock()
    return pm


# ── Mock Skills Engine ──


@pytest.fixture
def mock_skills_engine():
    """Minimal mock SkillsEngine."""
    se = MagicMock()
    se.skills = {}
    se.load_all = AsyncMock()
    se.list_skills = AsyncMock(return_value=[])
    se.build_skill_context = AsyncMock(return_value="")
    se.get_research_prompt = MagicMock(return_value="Research: test")
    se.parse_research_output = MagicMock(return_value={
        "name": "Test Skill",
        "description": "A test skill",
        "domain": "testing",
        "content": "# Test\nTest content",
    })
    se.create_knowledge_skill = AsyncMock(return_value={
        "id": "skill-test123",
        "name": "Test Skill",
    })
    se.execute_action = AsyncMock(return_value="Action executed")
    se.delete_skill = AsyncMock()
    return se


# ── Mock Task Queue ──


@pytest.fixture
def mock_task_queue():
    """Minimal mock TaskQueue."""
    tq = MagicMock()
    tq.active_count = 0
    tq.submit = AsyncMock(return_value={"id": "task-test123", "type": "research", "status": "pending"})
    tq.list_tasks = AsyncMock(return_value=[])
    tq.register_handler = MagicMock()
    return tq


# ── FastAPI Test App ──


@pytest_asyncio.fixture
async def test_app(
    tmp_base_dir, tmp_db_path, test_db, test_config,
    mock_model_router, mock_plugin_manager, mock_skills_engine, mock_task_queue,
):
    """Create a FastAPI app with mocked state, bypassing lifespan."""
    env_patches = {
        "ADMIN_API_KEY": "test-admin-key-12345",
        "ALLOWED_ORIGINS": "http://testserver",
        "HOST": "127.0.0.1",
        "PORT": "8080",
    }

    with patch.dict(os.environ, env_patches, clear=False):
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware

        from admin import router as admin_router, init as admin_init
        from routers import api as api_router_mod
        from routers import frontend as frontend_router_mod
        from middleware import RateLimitMiddleware, AuditMiddleware, AuthMiddleware
        from middleware import register_exception_handlers
        from core.security import init_allowed_dirs

        # Initialize allowed dirs for path validation
        init_allowed_dirs(str(tmp_base_dir))

        # Build the app without lifespan (no .nexus_secret needed)
        app = FastAPI(title="Nexus Test")

        # Initialize frontend router
        frontend_router_mod.init(str(tmp_base_dir))

        app.include_router(admin_router)
        app.include_router(api_router_mod.router)
        app.include_router(frontend_router_mod.router)

        register_exception_handlers(app)

        # Middleware with generous rate limits for testing
        app.add_middleware(AuthMiddleware)
        app.add_middleware(RateLimitMiddleware, general_limit=10000, admin_limit=10000, auth_limit=10000)
        app.add_middleware(AuditMiddleware)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://testserver"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Build and attach AppState
        from app import AppState

        state = AppState(
            cfg=test_config,
            db=test_db,
            skills_engine=mock_skills_engine,
            model_router=mock_model_router,
            task_queue=mock_task_queue,
            plugin_manager=mock_plugin_manager,
            jwt_manager=MagicMock(),
            oauth_manager=MagicMock(),
            user_manager=MagicMock(),
            ip_security=MagicMock(),
            audit_log=MagicMock(),
            allowed_origins=["http://testserver"],
            base_dir=str(tmp_base_dir),
        )
        app.state.nexus = state

        # Initialize admin module
        admin_init(
            test_config, mock_plugin_manager, mock_model_router,
            test_db, mock_task_queue, mock_skills_engine,
        )

        yield app


@pytest_asyncio.fixture
async def client(test_app):
    """Async HTTP test client."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def admin_headers():
    """Headers with valid admin API key."""
    return {"Authorization": "Bearer test-admin-key-12345"}


@pytest.fixture
def invalid_admin_headers():
    """Headers with an invalid admin API key."""
    return {"Authorization": "Bearer wrong-key"}
