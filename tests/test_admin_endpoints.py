"""Tests for admin API data endpoints (with valid auth)."""



class TestAdminDataEndpoints:
    """Verify admin endpoints return correct data when authenticated."""

    async def test_get_settings(self, client, admin_headers):
        resp = await client.get("/api/admin/settings", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "settings" in data
        assert isinstance(data["settings"], list)
        assert len(data["settings"]) > 0
        # Check structure of a setting
        setting = data["settings"][0]
        assert "key" in setting
        assert "value" in setting
        assert "category" in setting

    async def test_get_models(self, client, admin_headers):
        resp = await client.get("/api/admin/models", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "ollama_available" in data
        assert "claude_available" in data
        assert "complexity_threshold" in data
        assert "ollama_model" in data
        assert "claude_model" in data

    async def test_get_plugins(self, client, admin_headers):
        resp = await client.get("/api/admin/plugins", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
        assert "available" in data

    async def test_get_logs(self, client, admin_headers):
        resp = await client.get("/api/admin/logs", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_system_info(self, client, admin_headers):
        resp = await client.get("/api/admin/system", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "python_version" in data
        assert "platform" in data
        assert "base_dir" in data
        assert "skills_dir" in data
        assert "docs_dir" in data

    async def test_get_usage(self, client, admin_headers):
        resp = await client.get("/api/admin/usage", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "daily" in data
        assert "totals" in data

    async def test_get_conversations(self, client, admin_headers, test_db):
        await test_db.create_conversation("conv-admin-list", title="Admin List Test")
        resp = await client.get("/api/admin/conversations", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(c["id"] == "conv-admin-list" for c in data)

    async def test_delete_conversation(self, client, admin_headers, test_db):
        await test_db.create_conversation("conv-admin-del", title="Admin Delete")
        resp = await client.delete("/api/admin/conversations/conv-admin-del", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "conv-admin-del"

    async def test_get_audit_log(self, client, admin_headers):
        resp = await client.get("/api/admin/audit", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_skills(self, client, admin_headers):
        resp = await client.get("/api/admin/skills", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_backups(self, client, admin_headers):
        resp = await client.get("/api/admin/backups", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_backup_returns_error(self, client, admin_headers):
        """Backup endpoint returns 400 because it's managed by Supabase."""
        resp = await client.post("/api/admin/backup", headers=admin_headers)
        assert resp.status_code == 400


class TestAdminSettingsUpdate:
    """Test settings update operations."""

    async def test_update_setting(self, client, admin_headers):
        resp = await client.post(
            "/api/admin/settings",
            json={"updates": {"AGENT_NAME": "TestAdmin"}},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert "AGENT_NAME" in data["updated"]

    async def test_update_unknown_key_ignored(self, client, admin_headers):
        resp = await client.post(
            "/api/admin/settings",
            json={"updates": {"COMPLETELY_UNKNOWN_KEY": "value"}},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    async def test_update_url_setting_ssrf_blocked(self, client, admin_headers):
        """Updating OLLAMA_BASE_URL with a private IP should be blocked."""
        resp = await client.post(
            "/api/admin/settings",
            json={"updates": {"OLLAMA_BASE_URL": "http://192.168.1.1:11434"}},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "blocked" in resp.json()["error"].lower()


class TestAdminConversationManagement:
    async def test_delete_all_conversations(self, client, admin_headers, test_db):
        await test_db.create_conversation("conv-delall-1", title="One")
        await test_db.create_conversation("conv-delall-2", title="Two")
        resp = await client.delete("/api/admin/conversations", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"] >= 2


class TestAdminUserManagement:
    async def test_list_users(self, client, admin_headers):
        resp = await client.get("/api/admin/users", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_whitelist(self, client, admin_headers):
        resp = await client.get("/api/admin/whitelist", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestAdminIPSecurity:
    async def test_list_blocked_ips(self, client, admin_headers):
        resp = await client.get("/api/admin/blocked-ips", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestAdminAuthAudit:
    async def test_get_auth_audit(self, client, admin_headers):
        resp = await client.get("/api/admin/auth-audit", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestAdminSessions:
    async def test_list_sessions(self, client, admin_headers):
        resp = await client.get("/api/admin/sessions/user-123", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestAdminSkills:
    async def test_delete_skill(self, client, admin_headers):
        resp = await client.delete("/api/admin/skills/skill-test", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "skill-test"

    async def test_get_skill_config_not_found(self, client, admin_headers):
        resp = await client.get("/api/admin/skills/nonexistent/config", headers=admin_headers)
        assert resp.status_code == 404

    async def test_skill_packs_empty(self, client, admin_headers):
        resp = await client.get("/api/admin/skills/packs", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestAdminSystemPrompt:
    async def test_get_system_prompt(self, client, admin_headers):
        resp = await client.get("/api/admin/system-prompt", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "base_prompt" in data
        assert "plugin_additions" in data
        assert "full_prompt" in data


class TestAdminSettingsTest:
    async def test_setting_test_unknown_key(self, client, admin_headers):
        resp = await client.post("/api/admin/settings/test/UNKNOWN_KEY", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "No test available" in data["error"]

    async def test_setting_test_anthropic_no_key(self, client, admin_headers):
        resp = await client.post("/api/admin/settings/test/ANTHROPIC_API_KEY", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    async def test_setting_test_github_no_token(self, client, admin_headers):
        resp = await client.post("/api/admin/settings/test/GITHUB_TOKEN", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


class TestAdminUserOperations:
    async def test_update_user_role(self, client, admin_headers):
        resp = await client.put(
            "/api/admin/users/user-123/role",
            json={"role": "admin"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["role"] == "admin"

    async def test_deactivate_user(self, client, admin_headers):
        resp = await client.put(
            "/api/admin/users/user-123/deactivate",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    async def test_activate_user(self, client, admin_headers):
        resp = await client.put(
            "/api/admin/users/user-123/activate",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["active"] is True


class TestAdminWhitelistOperations:
    async def test_add_to_whitelist(self, client, admin_headers):
        resp = await client.post(
            "/api/admin/whitelist",
            json={"email": "test@example.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "test@example.com"

    async def test_add_to_whitelist_empty_email(self, client, admin_headers):
        resp = await client.post(
            "/api/admin/whitelist",
            json={"email": ""},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    async def test_remove_from_whitelist(self, client, admin_headers):
        resp = await client.delete(
            "/api/admin/whitelist/test@example.com",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestAdminIPOperations:
    async def test_block_ip(self, client, admin_headers):
        resp = await client.post(
            "/api/admin/blocked-ips",
            json={"ip": "10.0.0.1", "reason": "test blocking"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ip"] == "10.0.0.1"

    async def test_block_ip_empty(self, client, admin_headers):
        resp = await client.post(
            "/api/admin/blocked-ips",
            json={"ip": ""},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    async def test_unblock_ip(self, client, admin_headers):
        resp = await client.delete(
            "/api/admin/blocked-ips/10.0.0.1",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestAdminSessionOperations:
    async def test_revoke_session(self, client, admin_headers):
        resp = await client.delete(
            "/api/admin/sessions/session-abc123",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
