"""Tests for the public REST API endpoints.

Uses MockDatabase from conftest for unit testing without PostgreSQL.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSearchEndpoint:
    """Test the conversation search API endpoint."""

    @pytest.mark.asyncio
    async def test_search_with_results(self, mock_db):
        """Search returns matching messages."""
        await mock_db.create_conversation("c1", title="Dev Chat")
        await mock_db.add_message("c1", "user", "How to configure Ollama model?")
        await mock_db.add_message("c1", "assistant", "Use the settings page.")

        results = await mock_db.search_messages("ollama")
        assert len(results) == 1
        assert results[0]["conversation_title"] == "Dev Chat"
        assert "ollama" in results[0]["content"].lower()

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_empty(self, mock_db):
        results = await mock_db.search_messages("")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_no_matches(self, mock_db):
        await mock_db.create_conversation("c1")
        await mock_db.add_message("c1", "user", "Hello world")
        results = await mock_db.search_messages("nonexistent_xyz")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, mock_db):
        await mock_db.create_conversation("c1", title="Chat")
        await mock_db.add_message("c1", "user", "OLLAMA is great")
        results = await mock_db.search_messages("ollama")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, mock_db):
        await mock_db.create_conversation("c1", title="Chat")
        for i in range(30):
            await mock_db.add_message("c1", "user", f"Test message about python {i}")
        results = await mock_db.search_messages("python", limit=5)
        assert len(results) == 5


class TestExportEndpoint:
    """Test conversation export logic."""

    @pytest.mark.asyncio
    async def test_export_json_format(self, mock_db):
        """Export as JSON includes all conversation data."""
        await mock_db.create_conversation("c1", title="Test Chat")
        await mock_db.add_message("c1", "user", "Hello!")
        await mock_db.add_message("c1", "assistant", "Hi there!")

        conv = await mock_db.get_conversation("c1")
        messages = await mock_db.get_conversation_messages("c1", limit=9999)
        summary = await mock_db.get_conversation_summary("c1")

        export_data = {
            "conversation": conv,
            "summary": summary,
            "messages": messages,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        content = json.dumps(export_data, indent=2, default=str)
        data = json.loads(content)

        assert data["conversation"]["title"] == "Test Chat"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["summary"] is None

    @pytest.mark.asyncio
    async def test_export_markdown_format(self, mock_db):
        """Export as Markdown produces readable document."""
        await mock_db.create_conversation("c1", title="Dev Discussion")
        await mock_db.add_message("c1", "user", "What is Python?")
        await mock_db.add_message("c1", "assistant", "Python is a programming language.", model_used="claude")

        conv = await mock_db.get_conversation("c1")
        messages = await mock_db.get_conversation_messages("c1", limit=9999)

        lines = [f"# {conv.get('title', 'Untitled')}\n"]
        lines.append(f"**ID:** c1  ")
        lines.append("## Messages\n")
        for msg in messages:
            role = msg.get("role", "unknown").capitalize()
            model = msg.get("model_used", "")
            model_tag = f" *({model})*" if model else ""
            lines.append(f"### {role}{model_tag}")
            lines.append(f"{msg.get('content', '')}\n")
            lines.append("---\n")
        content = "\n".join(lines)

        assert "# Dev Discussion" in content
        assert "### User" in content
        assert "### Assistant *(claude)*" in content
        assert "What is Python?" in content

    @pytest.mark.asyncio
    async def test_export_with_summary(self, mock_db):
        """Export includes conversation summary when available."""
        await mock_db.create_conversation("c1", title="Long Chat")
        await mock_db.save_conversation_summary("c1", "This was a discussion about AI.", 20)
        summary = await mock_db.get_conversation_summary("c1")
        assert summary == "This was a discussion about AI."


class TestConversationCRUD:
    """Test basic conversation operations via MockDatabase."""

    @pytest.mark.asyncio
    async def test_create_and_list(self, mock_db):
        await mock_db.create_conversation("c1", title="Chat 1")
        await mock_db.create_conversation("c2", title="Chat 2")
        convs = await mock_db.list_conversations()
        assert len(convs) == 2

    @pytest.mark.asyncio
    async def test_delete_removes_messages(self, mock_db):
        await mock_db.create_conversation("c1")
        await mock_db.add_message("c1", "user", "hello")
        await mock_db.add_message("c1", "assistant", "hi")
        await mock_db.delete_conversation("c1")
        assert await mock_db.get_conversation("c1") is None
        msgs = await mock_db.get_conversation_messages("c1")
        assert len(msgs) == 0

    @pytest.mark.asyncio
    async def test_rename(self, mock_db):
        await mock_db.create_conversation("c1", title="Old")
        await mock_db.rename_conversation("c1", "New")
        conv = await mock_db.get_conversation("c1")
        assert conv["title"] == "New"
