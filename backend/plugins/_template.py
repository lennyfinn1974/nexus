"""Template for creating a new Nexus plugin.

How to create a plugin:
1. Copy this file and rename it (e.g. my_plugin.py)
2. Keep it in the backend/plugins/ directory
3. Rename the class and update name/description/version
4. Implement setup() to check dependencies
5. Add tools in register_tools()
6. Add slash commands in register_commands()
7. Restart Nexus — your plugin is auto-discovered

Tips:
- Your plugin gets access to self.config, self.db, and self.router
- self.router lets you call the AI from within your plugin
- Add any required env vars to .env and read them with os.getenv()
- Return False from setup() to gracefully disable the plugin
"""

import logging

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.template")


class TemplatePlugin(NexusPlugin):
    name = "template"
    description = "A template plugin — copy and modify this"
    version = "0.1.0"

    async def setup(self):
        """Check dependencies and authenticate.
        Return False to disable the plugin."""
        # Example: check for required env var
        # self.api_key = os.getenv("MY_SERVICE_API_KEY", "")
        # if not self.api_key:
        #     logger.info("  MY_SERVICE_API_KEY not set — plugin disabled")
        #     return False

        # Disable this template by default
        return False

    async def shutdown(self):
        """Clean up resources."""
        pass

    def register_tools(self):
        """Register tools the AI can use."""
        self.add_tool(
            "template_hello",  # unique tool name
            "Says hello — a demo tool",  # description for the AI
            {"name": "Name to greet"},  # parameter descriptions
            self._hello,  # async handler function
        )

    def register_commands(self):
        """Register slash commands for the user."""
        self.add_command(
            "template",  # command name (becomes /template)
            "Template plugin demo command",  # description
            self._handle_command,  # async handler
        )

    # ── Your tool implementations ──

    async def _hello(self, params):
        name = params.get("name", "World")
        return f"Hello, {name}! This is a demo tool."

    async def _handle_command(self, args):
        return "👋 This is the template plugin. Copy and modify me!"
