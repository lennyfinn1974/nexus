"""Shared fixtures for Nexus backend tests.

Provides:
- Async database session factory (real PostgreSQL)
- In-memory mock alternatives for unit tests
- FastAPI test client setup
- Common test data factories
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Async event loop ──


@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for all async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Mock Database ──


class MockDatabase:
    """In-memory mock of Database for unit tests that don't need PostgreSQL."""

    def __init__(self):
        self._conversations: dict[str, dict] = {}
        self._messages: dict[str, list[dict]] = {}
        self._summaries: dict[str, str] = {}
        self._skills: dict[str, dict] = {}
        self._tasks: list[dict] = []

    async def create_conversation(self, conv_id: str, title: str = "New Conversation") -> dict:
        now = datetime.now(timezone.utc).isoformat()
        conv = {"id": conv_id, "title": title, "created_at": now, "updated_at": now}
        self._conversations[conv_id] = conv
        self._messages[conv_id] = []
        return conv

    async def list_conversations(self, limit: int = 50) -> list[dict]:
        convs = list(self._conversations.values())
        return sorted(convs, key=lambda c: c["updated_at"], reverse=True)[:limit]

    async def get_conversation(self, conv_id: str) -> dict | None:
        return self._conversations.get(conv_id)

    async def get_conversation_messages(self, conv_id: str, limit: int = 100) -> list[dict]:
        msgs = self._messages.get(conv_id, [])
        return msgs[-limit:]

    async def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        model_used: str = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        msg_id = len(self._messages.get(conv_id, [])) + 1
        msg = {
            "id": msg_id,
            "conversation_id": conv_id,
            "role": role,
            "content": content,
            "model_used": model_used,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "created_at": now,
        }
        if conv_id not in self._messages:
            self._messages[conv_id] = []
        self._messages[conv_id].append(msg)
        if conv_id in self._conversations:
            self._conversations[conv_id]["updated_at"] = now
        return msg

    async def get_message_count(self, conv_id: str) -> int:
        return len(self._messages.get(conv_id, []))

    async def delete_conversation(self, conv_id: str):
        self._conversations.pop(conv_id, None)
        self._messages.pop(conv_id, None)
        self._summaries.pop(conv_id, None)

    async def rename_conversation(self, conv_id: str, title: str):
        if conv_id in self._conversations:
            self._conversations[conv_id]["title"] = title

    async def get_conversation_summary(self, conv_id: str) -> str | None:
        return self._summaries.get(conv_id)

    async def get_conversation_summary_detail(self, conv_id: str) -> dict | None:
        summary = self._summaries.get(conv_id)
        if summary is None:
            return None
        return {
            "summary_text": summary,
            "messages_covered": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def save_conversation_summary(self, conv_id: str, summary: str, messages_covered: int) -> None:
        self._summaries[conv_id] = summary

    async def search_messages(self, query: str, limit: int = 20) -> list[dict]:
        if not query or not query.strip():
            return []
        results = []
        q = query.lower()
        for conv_id, msgs in self._messages.items():
            for msg in msgs:
                if q in msg.get("content", "").lower():
                    conv = self._conversations.get(conv_id, {})
                    results.append({
                        "id": msg["id"],
                        "conversation_id": conv_id,
                        "role": msg["role"],
                        "content": msg["content"][:500],
                        "model_used": msg.get("model_used"),
                        "created_at": msg.get("created_at"),
                        "conversation_title": conv.get("title", "Untitled"),
                        "rank": 0.5,
                        "headline": msg["content"][:100],
                    })
        return results[:limit]

    async def execute_query(self, query: str) -> Any:
        return [(1,)]

    async def save_skill(self, skill_id: str, name: str, description: str, domain: str, file_path: str) -> dict:
        self._skills[skill_id] = {
            "id": skill_id, "name": name, "description": description,
            "domain": domain, "file_path": file_path,
        }
        return self._skills[skill_id]

    async def list_skills(self) -> list[dict]:
        return list(self._skills.values())

    async def delete_skill(self, skill_id: str):
        self._skills.pop(skill_id, None)

    async def list_tasks(self, status: str = None, limit: int = 50) -> list[dict]:
        return self._tasks[:limit]

    async def get_usage_stats(self) -> dict:
        return {"daily": [], "totals": []}


@pytest.fixture
def mock_db():
    """Return a fresh MockDatabase for each test."""
    return MockDatabase()


@pytest.fixture
def mock_model_router():
    """Return a mock ModelRouter."""
    router = MagicMock()
    router.status = {
        "claude_available": True,
        "ollama_available": True,
        "claude_code_available": False,
    }
    router.chat = AsyncMock(return_value="Test summary of the conversation.")
    return router


@pytest.fixture
def mock_app_state(mock_db, mock_model_router):
    """Return a mock AppState with all components."""
    state = MagicMock()
    state.db = mock_db
    state.model_router = mock_model_router
    state.cfg = MagicMock()
    state.cfg.docs_dir = "/tmp/nexus-test-docs"
    state.task_queue = MagicMock()
    state.task_queue.active_count = 0
    state.task_queue.list_tasks = AsyncMock(return_value=[])
    state.skills_engine = MagicMock()
    state.skills_engine.list_skills = AsyncMock(return_value=[])
    state.plugin_manager = MagicMock()
    state.plugin_manager.status = {}
    state.plugin_manager.plugins = {}
    state.plugin_manager.list_commands = MagicMock(return_value=[])
    state.tool_executor = None
    return state
