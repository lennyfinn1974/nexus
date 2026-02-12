"""Tests for the MockDatabase and Database contract.

These tests verify the in-memory MockDatabase mirrors the real Database
behaviour, and can optionally test against real PostgreSQL.
"""

import pytest


class TestMockDatabase:
    """Test MockDatabase from conftest — verifies the test infrastructure."""

    @pytest.mark.asyncio
    async def test_create_conversation(self, mock_db):
        conv = await mock_db.create_conversation("test-1", title="Test Chat")
        assert conv["id"] == "test-1"
        assert conv["title"] == "Test Chat"
        assert "created_at" in conv

    @pytest.mark.asyncio
    async def test_list_conversations(self, mock_db):
        await mock_db.create_conversation("c1", title="First")
        await mock_db.create_conversation("c2", title="Second")
        convs = await mock_db.list_conversations()
        assert len(convs) == 2

    @pytest.mark.asyncio
    async def test_get_conversation(self, mock_db):
        await mock_db.create_conversation("c1", title="Hello")
        conv = await mock_db.get_conversation("c1")
        assert conv is not None
        assert conv["title"] == "Hello"

    @pytest.mark.asyncio
    async def test_get_nonexistent_conversation(self, mock_db):
        conv = await mock_db.get_conversation("nonexistent")
        assert conv is None

    @pytest.mark.asyncio
    async def test_add_and_get_messages(self, mock_db):
        await mock_db.create_conversation("c1")
        await mock_db.add_message("c1", "user", "Hello!")
        await mock_db.add_message("c1", "assistant", "Hi there!", model_used="claude")
        msgs = await mock_db.get_conversation_messages("c1")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["model_used"] == "claude"

    @pytest.mark.asyncio
    async def test_message_count(self, mock_db):
        await mock_db.create_conversation("c1")
        assert await mock_db.get_message_count("c1") == 0
        await mock_db.add_message("c1", "user", "msg1")
        await mock_db.add_message("c1", "user", "msg2")
        assert await mock_db.get_message_count("c1") == 2

    @pytest.mark.asyncio
    async def test_delete_conversation(self, mock_db):
        await mock_db.create_conversation("c1")
        await mock_db.add_message("c1", "user", "hello")
        await mock_db.delete_conversation("c1")
        assert await mock_db.get_conversation("c1") is None
        assert await mock_db.get_message_count("c1") == 0

    @pytest.mark.asyncio
    async def test_rename_conversation(self, mock_db):
        await mock_db.create_conversation("c1", title="Old Title")
        await mock_db.rename_conversation("c1", "New Title")
        conv = await mock_db.get_conversation("c1")
        assert conv["title"] == "New Title"

    @pytest.mark.asyncio
    async def test_conversation_summary(self, mock_db):
        await mock_db.create_conversation("c1")
        assert await mock_db.get_conversation_summary("c1") is None
        await mock_db.save_conversation_summary("c1", "This is a summary.", 10)
        summary = await mock_db.get_conversation_summary("c1")
        assert summary == "This is a summary."

    @pytest.mark.asyncio
    async def test_search_messages(self, mock_db):
        await mock_db.create_conversation("c1", title="Dev Chat")
        await mock_db.add_message("c1", "user", "How do I configure Ollama?")
        await mock_db.add_message("c1", "assistant", "You can use the settings page.")
        results = await mock_db.search_messages("ollama")
        assert len(results) == 1
        assert results[0]["conversation_title"] == "Dev Chat"

    @pytest.mark.asyncio
    async def test_search_messages_empty_query(self, mock_db):
        results = await mock_db.search_messages("")
        assert results == []
        results = await mock_db.search_messages("  ")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_messages_no_match(self, mock_db):
        await mock_db.create_conversation("c1")
        await mock_db.add_message("c1", "user", "Hello world")
        results = await mock_db.search_messages("nonexistent_term")
        assert results == []

    @pytest.mark.asyncio
    async def test_message_limit(self, mock_db):
        await mock_db.create_conversation("c1")
        for i in range(50):
            await mock_db.add_message("c1", "user", f"Message {i}")
        msgs = await mock_db.get_conversation_messages("c1", limit=10)
        assert len(msgs) == 10
        # Should be the last 10 messages
        assert msgs[0]["content"] == "Message 40"

    @pytest.mark.asyncio
    async def test_skills_crud(self, mock_db):
        await mock_db.save_skill("s1", "Test Skill", "A test", "testing", "/tmp/test.py")
        skills = await mock_db.list_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "Test Skill"
        await mock_db.delete_skill("s1")
        assert len(await mock_db.list_skills()) == 0

    @pytest.mark.asyncio
    async def test_execute_query(self, mock_db):
        result = await mock_db.execute_query("SELECT 1")
        assert result == [(1,)]
