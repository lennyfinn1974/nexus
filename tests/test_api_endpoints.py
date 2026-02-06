"""Tests for REST API endpoints."""

import pytest


class TestPublicEndpoints:
    async def test_serve_ui(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "Nexus" in resp.text

    async def test_serve_admin(self, client):
        resp = await client.get("/admin")
        assert resp.status_code == 200
        assert "Admin" in resp.text

    async def test_api_status(self, client):
        resp = await client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert "tasks_active" in data
        assert "skills_count" in data
        assert "plugins" in data

    async def test_api_plugins(self, client):
        resp = await client.get("/api/plugins")
        assert resp.status_code == 200
        data = resp.json()
        assert "plugins" in data
        assert "commands" in data

    async def test_api_skills(self, client):
        resp = await client.get("/api/skills")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_api_tasks(self, client):
        resp = await client.get("/api/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestConversationEndpoints:
    async def test_create_conversation(self, client):
        resp = await client.post("/api/conversations", json={"title": "Test Conv"})
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["id"].startswith("conv-")

    async def test_list_conversations(self, client):
        await client.post("/api/conversations", json={"title": "Test"})
        resp = await client.get("/api/conversations")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_conversation_messages(self, client, test_db):
        await test_db.create_conversation("conv-api-1", title="API Test")
        await test_db.add_message("conv-api-1", "user", "Hello API")
        resp = await client.get("/api/conversations/conv-api-1/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert "conversation" in data
        assert "messages" in data
        assert len(data["messages"]) == 1

    async def test_get_conversation_messages_not_found(self, client):
        resp = await client.get("/api/conversations/nonexistent/messages")
        assert resp.status_code == 404

    async def test_rename_conversation(self, client, test_db):
        await test_db.create_conversation("conv-rename-api", title="Old")
        resp = await client.put(
            "/api/conversations/conv-rename-api",
            json={"title": "New Title"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    async def test_rename_conversation_empty_title(self, client, test_db):
        await test_db.create_conversation("conv-rename-empty", title="Old")
        resp = await client.put(
            "/api/conversations/conv-rename-empty",
            json={"title": "  "},
        )
        assert resp.status_code == 400

    async def test_delete_conversation(self, client, test_db):
        await test_db.create_conversation("conv-del-api", title="Delete Me")
        resp = await client.delete("/api/conversations/conv-del-api")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "conv-del-api"


class TestDocEndpoints:
    async def test_list_docs(self, client):
        resp = await client.get("/api/docs")
        assert resp.status_code == 200
        data = resp.json()
        assert "docs_dir" in data
        assert "files" in data
