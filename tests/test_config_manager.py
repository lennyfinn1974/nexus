"""Tests for the database-backed ConfigManager."""

import os
from unittest.mock import AsyncMock


class TestConfigManagerBasics:
    async def test_seed_defaults(self, test_config):
        """All schema defaults should be populated."""
        assert test_config.get("HOST") == "127.0.0.1"
        assert test_config.get_int("PORT") == 8080
        assert test_config.get("PERSONA_TONE") == "balanced"

    async def test_get_set(self, test_config):
        await test_config.set("AGENT_NAME", "TestBot")
        assert test_config.agent_name == "TestBot"

    async def test_get_int(self, test_config):
        await test_config.set("PORT", "9090")
        assert test_config.get_int("PORT") == 9090

    async def test_get_int_invalid(self, test_config):
        await test_config.set("PORT", "not-a-number")
        assert test_config.get_int("PORT", 8080) == 8080

    async def test_get_bool(self, test_config):
        # get_bool isn't a schema setting, but we can test via raw cache
        test_config._cache["TEST_BOOL"] = "true"
        assert test_config.get_bool("TEST_BOOL") is True
        test_config._cache["TEST_BOOL"] = "false"
        assert test_config.get_bool("TEST_BOOL") is False

    async def test_set_many(self, test_config):
        changed = await test_config.set_many(
            {
                "AGENT_NAME": "BatchBot",
                "HOST": "0.0.0.0",
            }
        )
        assert "AGENT_NAME" in changed
        assert test_config.agent_name == "BatchBot"
        assert test_config.host == "0.0.0.0"

    async def test_set_many_ignores_unknown_keys(self, test_config):
        changed = await test_config.set_many({"UNKNOWN_KEY_XYZ": "value"})
        assert len(changed) == 0


class TestConfigProperties:
    async def test_convenience_properties(self, test_config):
        await test_config.set("CLAUDE_MODEL", "claude-test-model")
        assert test_config.claude_model == "claude-test-model"

        await test_config.set("OLLAMA_BASE_URL", "http://ollama:11434")
        assert test_config.ollama_base_url == "http://ollama:11434"

        await test_config.set("COMPLEXITY_THRESHOLD", "75")
        assert test_config.complexity_threshold == 75

    async def test_has_anthropic(self, test_config):
        await test_config.set("ANTHROPIC_API_KEY", "")
        assert test_config.has_anthropic is False

        await test_config.set("ANTHROPIC_API_KEY", "sk-ant-your-key-here")
        assert test_config.has_anthropic is False

        await test_config.set("ANTHROPIC_API_KEY", "sk-ant-real-key-123")
        assert test_config.has_anthropic is True

    async def test_dirs(self, test_config, tmp_base_dir):
        assert test_config.skills_dir == os.path.join(str(tmp_base_dir), "skills")
        assert test_config.data_dir == os.path.join(str(tmp_base_dir), "data")


class TestConfigSubscriptions:
    async def test_subscribe_fires_on_change(self, test_config):
        callback = AsyncMock()
        test_config.subscribe({"AGENT_NAME"}, callback)
        await test_config.set("AGENT_NAME", "SubscribeBot")
        callback.assert_awaited_once()
        args = callback.call_args[0]
        assert args[0] == "AGENT_NAME"
        assert args[2] == "SubscribeBot"

    async def test_subscribe_not_fired_for_other_keys(self, test_config):
        callback = AsyncMock()
        test_config.subscribe({"AGENT_NAME"}, callback)
        await test_config.set("HOST", "0.0.0.0")
        callback.assert_not_awaited()

    async def test_wildcard_subscription(self, test_config):
        callback = AsyncMock()
        test_config.subscribe({"*"}, callback)
        await test_config.set("HOST", "192.168.1.1")
        callback.assert_awaited_once()


class TestConfigAPI:
    async def test_get_all_for_api_masks_secrets(self, test_config):
        await test_config.set("ANTHROPIC_API_KEY", "sk-ant-secret-key")
        api_settings = test_config.get_all_for_api()
        api_key_setting = next(s for s in api_settings if s["key"] == "ANTHROPIC_API_KEY")
        assert api_key_setting["value"] == "***REDACTED***"
        assert api_key_setting["has_value"] is True

    async def test_get_all_for_api_shows_non_secret(self, test_config):
        await test_config.set("AGENT_NAME", "VisibleBot")
        api_settings = test_config.get_all_for_api()
        name_setting = next(s for s in api_settings if s["key"] == "AGENT_NAME")
        assert name_setting["value"] == "VisibleBot"
