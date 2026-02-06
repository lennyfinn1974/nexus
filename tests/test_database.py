"""Tests for the SQLite database layer."""

import pytest


class TestConversations:
    async def test_create_conversation(self, test_db):
        conv = await test_db.create_conversation("conv-test1", title="Hello World")
        assert conv["id"] == "conv-test1"
        assert conv["title"] == "Hello World"

    async def test_list_conversations(self, test_db):
        await test_db.create_conversation("conv-a", title="First")
        await test_db.create_conversation("conv-b", title="Second")
        convs = await test_db.list_conversations()
        assert len(convs) >= 2
        titles = {c["title"] for c in convs}
        assert "First" in titles
        assert "Second" in titles

    async def test_get_conversation(self, test_db):
        await test_db.create_conversation("conv-get", title="Get Me")
        conv = await test_db.get_conversation("conv-get")
        assert conv is not None
        assert conv["title"] == "Get Me"

    async def test_get_conversation_not_found(self, test_db):
        conv = await test_db.get_conversation("nonexistent")
        assert conv is None

    async def test_rename_conversation(self, test_db):
        await test_db.create_conversation("conv-rename", title="Old Name")
        await test_db.rename_conversation("conv-rename", "New Name")
        conv = await test_db.get_conversation("conv-rename")
        assert conv["title"] == "New Name"

    async def test_delete_conversation(self, test_db):
        await test_db.create_conversation("conv-del", title="Delete Me")
        await test_db.add_message("conv-del", "user", "hello")
        await test_db.delete_conversation("conv-del")
        conv = await test_db.get_conversation("conv-del")
        assert conv is None
        messages = await test_db.get_conversation_messages("conv-del")
        assert len(messages) == 0


class TestMessages:
    async def test_add_and_get_messages(self, test_db):
        await test_db.create_conversation("conv-msg", title="Messages")
        await test_db.add_message("conv-msg", "user", "Hello!")
        await test_db.add_message("conv-msg", "assistant", "Hi there!", model_used="test-model")
        messages = await test_db.get_conversation_messages("conv-msg")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello!"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["model_used"] == "test-model"

    async def test_message_limit(self, test_db):
        await test_db.create_conversation("conv-limit", title="Limit Test")
        for i in range(10):
            await test_db.add_message("conv-limit", "user", f"Message {i}")
        messages = await test_db.get_conversation_messages("conv-limit", limit=5)
        assert len(messages) == 5

    async def test_message_token_tracking(self, test_db):
        await test_db.create_conversation("conv-tok", title="Tokens")
        msg = await test_db.add_message(
            "conv-tok", "assistant", "Response",
            model_used="claude-test", tokens_in=100, tokens_out=200,
        )
        assert msg["model_used"] == "claude-test"


class TestSkills:
    async def test_save_and_list_skills(self, test_db):
        await test_db.save_skill("sk-1", "Python Basics", "Learn Python", "programming", "/tmp/sk1.md")
        skills = await test_db.list_skills()
        assert len(skills) >= 1
        assert skills[0]["name"] == "Python Basics"

    async def test_find_skills_by_domain(self, test_db):
        await test_db.save_skill("sk-dom1", "JS Skill", "JavaScript", "programming", "/tmp/sk2.md")
        await test_db.save_skill("sk-dom2", "Cook Skill", "Cooking", "lifestyle", "/tmp/sk3.md")
        results = await test_db.find_skills_by_domain("programming")
        assert all("programming" in r["domain"] for r in results)

    async def test_increment_skill_usage(self, test_db):
        await test_db.save_skill("sk-use", "Usage Test", "Test", "test", "/tmp/sk4.md")
        await test_db.increment_skill_usage("sk-use")
        await test_db.increment_skill_usage("sk-use")
        skills = await test_db.list_skills()
        skill = next(s for s in skills if s["id"] == "sk-use")
        assert skill["usage_count"] == 2

    async def test_delete_skill(self, test_db):
        await test_db.save_skill("sk-del", "Delete Me", "Gone", "test", "/tmp/sk5.md")
        await test_db.delete_skill("sk-del")
        skills = await test_db.list_skills()
        assert not any(s["id"] == "sk-del" for s in skills)


class TestTasks:
    async def test_create_and_list_tasks(self, test_db):
        task = await test_db.create_task("task-1", "research", {"topic": "Python"})
        assert task["status"] == "pending"
        tasks = await test_db.list_tasks()
        assert len(tasks) >= 1

    async def test_update_task_status(self, test_db):
        await test_db.create_task("task-upd", "research")
        await test_db.update_task("task-upd", "running")
        await test_db.update_task("task-upd", "completed", result="Done!")
        tasks = await test_db.list_tasks(status="completed")
        task = next(t for t in tasks if t["id"] == "task-upd")
        assert task["result"] == "Done!"

    async def test_task_failure(self, test_db):
        await test_db.create_task("task-fail", "ingest")
        await test_db.update_task("task-fail", "failed", error="File not found")
        tasks = await test_db.list_tasks(status="failed")
        task = next(t for t in tasks if t["id"] == "task-fail")
        assert task["error"] == "File not found"
