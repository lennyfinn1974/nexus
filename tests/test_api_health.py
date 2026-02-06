"""Tests for the health check and additional API endpoints."""


class TestHealthEndpoint:
    async def test_health_check(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert "healthy" in data
        assert "checks" in data
        assert "database" in data["checks"]
        assert "models" in data["checks"]
        assert "plugins" in data["checks"]
        assert "filesystem" in data["checks"]

    async def test_health_check_database(self, client):
        resp = await client.get("/api/health")
        data = resp.json()
        db_check = data["checks"]["database"]
        assert db_check["status"] in ("healthy", "unhealthy")

    async def test_health_check_models(self, client):
        resp = await client.get("/api/health")
        data = resp.json()
        model_check = data["checks"]["models"]
        assert "claude" in model_check
        assert "ollama" in model_check


class TestSkillsEndpoints:
    async def test_delete_skill(self, client, mock_skills_engine):
        resp = await client.delete("/api/skills/skill-123")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "skill-123"
        mock_skills_engine.delete_skill.assert_awaited_once_with("skill-123")


class TestPartnersEndpoints:
    async def test_list_partners_no_registry(self, client):
        """When partner_registry is not set, return empty list."""
        resp = await client.get("/api/partners")
        assert resp.status_code == 200
        assert resp.json()["partners"] == []


class TestDocEndpoints:
    async def test_list_docs(self, client):
        resp = await client.get("/api/docs")
        assert resp.status_code == 200
        data = resp.json()
        assert "docs_dir" in data
        assert "files" in data
