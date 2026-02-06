"""Security tests -- auth bypass, SSRF, path traversal, injection."""

import os
import pytest
from unittest.mock import patch


class TestAdminAuthBypass:
    """Verify admin endpoints reject unauthorized access."""

    ADMIN_ENDPOINTS = [
        ("GET", "/api/admin/settings"),
        ("POST", "/api/admin/settings"),
        ("GET", "/api/admin/models"),
        ("GET", "/api/admin/plugins"),
        ("GET", "/api/admin/logs"),
        ("GET", "/api/admin/system"),
        ("GET", "/api/admin/usage"),
        ("GET", "/api/admin/conversations"),
        ("GET", "/api/admin/audit"),
        ("GET", "/api/admin/skills"),
    ]

    @pytest.mark.security
    @pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
    async def test_admin_requires_auth(self, client, method, path):
        """All admin endpoints must return 401/403 without credentials."""
        if method == "GET":
            resp = await client.get(path)
        else:
            resp = await client.post(path, json={})
        assert resp.status_code in (401, 403), f"{method} {path} returned {resp.status_code} without auth"

    @pytest.mark.security
    @pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
    async def test_admin_rejects_invalid_key(self, client, invalid_admin_headers, method, path):
        """Admin endpoints must reject wrong API keys."""
        if method == "GET":
            resp = await client.get(path, headers=invalid_admin_headers)
        else:
            resp = await client.post(path, json={}, headers=invalid_admin_headers)
        assert resp.status_code in (401, 403), f"{method} {path} accepted wrong key"

    @pytest.mark.security
    async def test_admin_settings_with_valid_key(self, client, admin_headers):
        """Admin settings endpoint works with correct key."""
        resp = await client.get("/api/admin/settings", headers=admin_headers)
        assert resp.status_code == 200

    @pytest.mark.security
    async def test_no_admin_key_configured(self, client):
        """When ADMIN_API_KEY is empty, admin endpoints should still reject."""
        with patch.dict(os.environ, {"ADMIN_API_KEY": ""}):
            resp = await client.get("/api/admin/settings")
            assert resp.status_code in (401, 403)


class TestPathTraversal:
    """Verify path traversal attacks are blocked."""

    @pytest.mark.security
    async def test_path_traversal_blocked(self):
        """validate_path should block directory traversal."""
        from core.security import validate_path, init_allowed_dirs
        from core.exceptions import PathAccessDeniedError

        init_allowed_dirs("/tmp/test-nexus")
        with pytest.raises(PathAccessDeniedError):
            validate_path("/etc/passwd")

    @pytest.mark.security
    async def test_path_traversal_dotdot(self, tmp_base_dir):
        """Dot-dot traversal should be caught."""
        from core.security import validate_path, init_allowed_dirs
        from core.exceptions import PathAccessDeniedError

        init_allowed_dirs(str(tmp_base_dir))
        with pytest.raises(PathAccessDeniedError):
            validate_path(str(tmp_base_dir / "data" / ".." / ".." / "etc" / "passwd"))

    @pytest.mark.security
    async def test_valid_path_allowed(self, tmp_base_dir):
        """Paths inside ALLOWED_DIRS should work."""
        from core.security import validate_path, init_allowed_dirs

        init_allowed_dirs(str(tmp_base_dir))
        data_dir = str(tmp_base_dir / "data")
        test_file = os.path.join(data_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test")
        result = validate_path(test_file)
        assert result == os.path.realpath(test_file)


class TestSSRFProtection:
    """Test SSRF protection in URL validation."""

    @pytest.mark.security
    async def test_ssrf_blocks_localhost(self):
        from admin import validate_url
        with pytest.raises(ValueError, match="blocked"):
            validate_url("http://localhost:8080/api")

    @pytest.mark.security
    async def test_ssrf_blocks_internal_ip(self):
        from admin import validate_url
        with pytest.raises(ValueError, match="blocked"):
            validate_url("http://127.0.0.1:8080/api")

    @pytest.mark.security
    async def test_ssrf_blocks_private_range(self):
        from admin import validate_url
        with pytest.raises(ValueError, match="blocked"):
            validate_url("http://192.168.1.1:8080")

    @pytest.mark.security
    async def test_ssrf_blocks_zero_address(self):
        from admin import validate_url
        with pytest.raises(ValueError, match="blocked"):
            validate_url("http://0.0.0.0:8080")

    @pytest.mark.security
    async def test_ssrf_blocks_non_http(self):
        from admin import validate_url
        with pytest.raises(ValueError, match="scheme"):
            validate_url("file:///etc/passwd")

    @pytest.mark.security
    async def test_ssrf_blocks_ftp(self):
        from admin import validate_url
        with pytest.raises(ValueError, match="scheme"):
            validate_url("ftp://evil.com/data")


class TestInputValidation:
    """Test that user inputs are properly validated."""

    @pytest.mark.security
    async def test_rename_rejects_empty_title(self, client, test_db):
        await test_db.create_conversation("conv-sec-rename", title="Original")
        resp = await client.put(
            "/api/conversations/conv-sec-rename",
            json={"title": "  "},
        )
        assert resp.status_code == 400

    @pytest.mark.security
    async def test_admin_settings_rejects_empty_updates(self, client, admin_headers):
        resp = await client.post(
            "/api/admin/settings",
            json={"updates": {}},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.security
    async def test_admin_settings_filters_masked_values(self, client, admin_headers):
        """Settings with '...' (masked) should be silently skipped."""
        resp = await client.post(
            "/api/admin/settings",
            json={"updates": {"ANTHROPIC_API_KEY": "sk-ant...masked...key"}},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
