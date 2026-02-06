"""Plugin manager — discovery, loading, command dispatch, and security hooks."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import re
from typing import Any

from .base import BasePlugin, NexusPlugin, ToolInfo
from .permissions import PermissionLevel

logger = logging.getLogger("nexus.plugins")


class PluginManager:
    """Discover, load, and manage Nexus plugins."""

    def __init__(self, config: Any, db: Any, router: Any):
        self.config = config
        self.db = db
        self.router = router
        self.plugins: dict[str, NexusPlugin] = {}

    # ── Discovery & Loading ──

    async def discover_and_load(self) -> None:
        """Scan plugins/ directory for *_plugin.py files, import and register."""
        self.plugins = {}
        plugins_dir = os.path.dirname(os.path.abspath(__file__))

        for filename in sorted(os.listdir(plugins_dir)):
            if not filename.endswith("_plugin.py"):
                continue

            module_name = filename[:-3]  # strip .py
            module_name.replace("_plugin", "")

            try:
                spec = importlib.util.spec_from_file_location(
                    f"plugins.{module_name}",
                    os.path.join(plugins_dir, filename),
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

                # Find the plugin class — look for subclass of NexusPlugin
                plugin_cls = None
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, NexusPlugin)
                        and attr is not NexusPlugin
                        and attr is not BasePlugin
                    ):
                        plugin_cls = attr
                        break

                if not plugin_cls:
                    logger.warning(f"No NexusPlugin subclass found in {filename}")
                    continue

                plugin = plugin_cls(self.config, self.db, self.router)
                await plugin.init()
                self.plugins[plugin.name] = plugin
                logger.info(
                    f"Loaded plugin: {plugin.name} v{plugin.version} "
                    f"({len(plugin.tools)} tools, {len(plugin.commands)} commands)"
                )

            except Exception as e:
                logger.error(f"Failed to load plugin from {filename}: {e}")

        # Also try entry-point discovery as fallback
        try:
            from plugins import discover_plugins

            for name, cls in discover_plugins().items():
                if name not in self.plugins:
                    plugin = cls(self.config, self.db, self.router)
                    await plugin.init()
                    self.plugins[name] = plugin
                    logger.info(f"Loaded plugin (entry-point): {name}")
        except Exception:
            pass  # Entry-points not available, that's fine

        logger.info(f"Plugin manager: {len(self.plugins)} plugins loaded")

    async def reload_plugin(self, name: str, config: Any, db: Any, router: Any) -> NexusPlugin:
        """Reload a single plugin by name."""
        if name in self.plugins:
            await self.plugins[name].shutdown()
            del self.plugins[name]

        plugins_dir = os.path.dirname(os.path.abspath(__file__))
        filename = f"{name}_plugin.py"
        filepath = os.path.join(plugins_dir, filename)

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Plugin file not found: {filename}")

        spec = importlib.util.spec_from_file_location(
            f"plugins.{name}_plugin",
            filepath,
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        plugin_cls = None
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, NexusPlugin)
                and attr is not NexusPlugin
                and attr is not BasePlugin
            ):
                plugin_cls = attr
                break

        if not plugin_cls:
            raise ValueError(f"No NexusPlugin subclass found in {filename}")

        plugin = plugin_cls(config, db, router)
        await plugin.init()
        self.plugins[plugin.name] = plugin
        return plugin

    async def reload_all(self, config: Any, db: Any, router: Any) -> None:
        """Shut down and reload all plugins."""
        await self.shutdown_all()
        self.config = config
        self.db = db
        self.router = router
        await self.discover_and_load()

    async def shutdown_all(self) -> None:
        """Shut down all loaded plugins."""
        for plugin in self.plugins.values():
            try:
                await plugin.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down plugin {plugin.name}: {e}")

    # ── Status & Metadata ──

    @property
    def status(self) -> dict:
        """Return consolidated status dict for all plugins."""
        result = {}
        for name, p in self.plugins.items():
            result[name] = {
                "version": p.version,
                "enabled": p.enabled,
                "tools": len(p.tools),
                "commands": len(p.commands),
            }
        return result

    @property
    def all_tools(self) -> list[ToolInfo]:
        """Return flat list of all tools across all plugins."""
        tools = []
        for p in self.plugins.values():
            tools.extend(p.tools)
        return tools

    def list_commands(self) -> list[dict]:
        """Return all slash commands across all plugins."""
        cmds = []
        for p in self.plugins.values():
            for name, info in p.commands.items():
                cmds.append(
                    {
                        "plugin": p.name,
                        "command": f"/{name}",
                        "description": info.get("description", ""),
                    }
                )
        return cmds

    # ── Command Dispatch ──

    async def handle_command(self, name: str, args: str) -> str | None:
        """Dispatch a slash-command to the owning plugin."""
        for p in self.plugins.values():
            if name in p.commands:
                handler = p.commands[name].get("handler")
                if handler:
                    return await handler(args)
        return None

    # ── Tool Call Processing (legacy regex) ──

    async def process_tool_calls(self, content: str) -> tuple[str, list]:
        """Detect <tool_call> tags and invoke the correct plugin tool.

        Returns (cleaned_content, list_of_results).
        """
        pattern = r"<tool_call>(\w+):(\w+)\((.*?)\)</tool_call>"
        results = []

        for match in re.finditer(pattern, content, re.DOTALL):
            plugin_name, tool_name, raw_params = match.groups()
            plugin = self.plugins.get(plugin_name)
            if not plugin:
                results.append({"tool": tool_name, "error": f"Plugin {plugin_name} not found"})
                continue

            # Parse parameters (key=value, comma separated)
            params: dict[str, str] = {}
            for pair in re.split(r",\s*(?=\w+=)", raw_params):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k.strip()] = v.strip().strip("\"'")

            # Security hook: check before execution
            allowed = await self.validate_tool_call(plugin, tool_name, params)
            if not allowed:
                results.append({"tool": tool_name, "error": "Tool call blocked by security policy"})
                continue

            try:
                # Find tool handler
                tool_info = next((t for t in plugin.tools if t.name == tool_name), None)
                if tool_info and tool_info.handler:
                    res = await tool_info.handler(params)
                else:
                    # Fallback to tool_<name> method
                    res = await getattr(plugin, f"tool_{tool_name}")(**params)
                results.append({"tool": tool_name, "result": res})

                # Audit hook
                await self.audit_tool_call(plugin, tool_name, params, res)
            except Exception as exc:
                results.append({"tool": tool_name, "error": str(exc)})

        # Remove tool_call tags from content
        cleaned = re.sub(pattern, "", content, flags=re.DOTALL).strip()
        return cleaned, results

    # ── Security Hooks ──

    async def validate_tool_call(self, plugin: NexusPlugin, tool_name: str, params: dict) -> bool:
        """Check permissions before executing a tool call."""
        # Let the plugin itself decide
        return await plugin.on_before_tool_call(tool_name, params)

    async def audit_tool_call(
        self,
        plugin: NexusPlugin,
        tool_name: str,
        params: dict,
        result: Any,
    ) -> None:
        """Log tool call to audit trail."""
        await plugin.on_after_tool_call(tool_name, params, result)
        logger.info(f"Tool call: {plugin.name}:{tool_name}")

    def get_tools_for_context(self, user_level: int = PermissionLevel.STANDARD) -> list:
        """Filter tools by permission level."""
        tools = []
        for p in self.plugins.values():
            if p.permission_level <= user_level:
                tools.extend(p.tools)
        return tools

    # ── System Prompt ──

    def get_system_prompt_additions(self) -> str:
        """Get system prompt additions from active plugins."""
        additions = []
        for name, plugin in self.plugins.items():
            if hasattr(plugin, "get_system_prompt_addition"):
                try:
                    addition = plugin.get_system_prompt_addition()
                    if addition:
                        additions.append(f"# Plugin: {name}\n{addition}")
                except Exception:
                    pass
        return "\n\n".join(additions)
