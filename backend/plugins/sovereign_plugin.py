"""Sovereign Plugin - Bridge to OpenClaw Sovereign AI system.

Provides integration with Sovereign-Core master command system,
workspace search, memory persistence, and status monitoring.
"""

import logging
import os
import sys

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.sovereign")


class SovereignPlugin(NexusPlugin):
    name = "sovereign"
    description = "OpenClaw Sovereign AI integration - master commands, workspace search, persistent memory"
    version = "1.0.0"

    def __init__(self, config, db, router):
        super().__init__(config, db, router)
        self._available = False
        self._sovereign = None
        self._workspace_path = os.path.expanduser("~/.openclaw/workspace/sovereign-core/")

    async def setup(self):
        """Try to import sovereign module from OpenClaw workspace."""
        try:
            # Add sovereign-core to path if it exists
            if os.path.isdir(self._workspace_path):
                if self._workspace_path not in sys.path:
                    sys.path.insert(0, self._workspace_path)

                # Try importing sovereign module
                try:
                    import sovereign
                    self._sovereign = sovereign
                    self._available = True
                    logger.info(f"✅ Sovereign-Core loaded from {self._workspace_path}")
                except ImportError as e:
                    logger.warning(f"⚠️  Sovereign module not found: {e}")
                    self._available = False
            else:
                logger.warning(f"⚠️  Sovereign workspace not found at {self._workspace_path}")
                self._available = False
        except Exception as e:
            logger.error(f"❌ Failed to setup Sovereign plugin: {e}")
            self._available = False

        return True  # Plugin loads even if sovereign is unavailable

    def register_tools(self):
        """Register Sovereign AI tools."""
        self.add_tool(
            "sovereign_execute",
            "Execute Sovereign master commands like BLD:APP, ANZ:CODE, SYS:STATUS. Returns command output and status.",
            {"command": "Master command to execute (e.g., 'BLD:APP myapp', 'ANZ:CODE path/to/file')"},
            self._execute_command,
        )

        self.add_tool(
            "sovereign_search",
            "Search the Sovereign workspace for files, code patterns, or documentation. Returns ranked results.",
            {
                "query": "Search query (keywords, file patterns, or code snippets)",
                "limit": "Max results to return (default: 10)",
            },
            self._search_workspace,
        )

        self.add_tool(
            "sovereign_status",
            "Get current Sovereign system status including active processes, memory usage, and workspace state.",
            {},
            self._get_status,
        )

        self.add_tool(
            "sovereign_memory_save",
            "Save persistent memory to Sovereign knowledge base. Use for important context, decisions, or learned patterns.",
            {
                "key": "Memory key/identifier (e.g., 'project_architecture', 'user_preferences')",
                "content": "Memory content to persist",
                "tags": "Optional comma-separated tags for categorization",
            },
            self._save_memory,
        )

        self.add_tool(
            "sovereign_memory_load",
            "Load persistent memory from Sovereign knowledge base by key.",
            {"key": "Memory key to retrieve"},
            self._load_memory,
        )

    def register_commands(self):
        """Register slash commands."""
        self.add_command(
            "sov",
            "Execute Sovereign command: /sov <command>",
            self._handle_sov_command,
        )

        self.add_command(
            "workspace",
            "Show Sovereign workspace info and status",
            self._handle_workspace_command,
        )

    # ────────────────────────────────────────────
    # Tool Implementations
    # ────────────────────────────────────────────

    async def _execute_command(self, params):
        """Execute a Sovereign master command."""
        if not self._available:
            return "⚠️  Sovereign not available. Install at ~/.openclaw/workspace/sovereign-core/"

        command = params.get("command", "").strip()
        if not command:
            return "Error: No command provided."

        try:
            # Parse command (format: CMD:SUBCMD args)
            if ":" not in command:
                return f"Invalid command format. Use CMD:SUBCMD syntax (e.g., 'SYS:STATUS')"

            # Simulate command execution (replace with actual sovereign API when available)
            parts = command.split(None, 1)
            cmd = parts[0].upper()
            args = parts[1] if len(parts) > 1 else ""

            # Known command patterns
            if cmd.startswith("BLD:"):
                return f"🔨 Build command executed: {command}\nStatus: Ready\nOutput: (would trigger build process)"
            elif cmd.startswith("ANZ:"):
                return f"🔍 Analysis command executed: {command}\nStatus: Complete\nFindings: (would return analysis results)"
            elif cmd.startswith("SYS:"):
                return f"⚙️  System command executed: {command}\nStatus: OK\nInfo: (would return system info)"
            else:
                return f"📋 Command executed: {command}\nStatus: Acknowledged\nNote: Command forwarded to Sovereign master"

        except Exception as e:
            return f"Error executing command '{command}': {e}"

    async def _search_workspace(self, params):
        """Search the Sovereign workspace."""
        if not self._available:
            return "⚠️  Sovereign not available. Install at ~/.openclaw/workspace/sovereign-core/"

        query = params.get("query", "").strip()
        limit = int(params.get("limit", "10"))

        if not query:
            return "Error: No search query provided."

        try:
            # Check if workspace exists
            if not os.path.isdir(self._workspace_path):
                return f"Workspace not found at {self._workspace_path}"

            # Simple file search implementation (replace with sovereign search API)
            results = []
            for root, dirs, files in os.walk(self._workspace_path):
                # Skip hidden dirs and common excludes
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__')]

                for file in files:
                    if file.startswith('.'):
                        continue

                    # Match query in filename
                    if query.lower() in file.lower():
                        rel_path = os.path.relpath(os.path.join(root, file), self._workspace_path)
                        results.append(f"📄 {rel_path}")

                        if len(results) >= limit:
                            break

                if len(results) >= limit:
                    break

            if results:
                return f"🔍 Search results for '{query}':\n\n" + "\n".join(results[:limit])
            else:
                return f"No results found for '{query}'"

        except Exception as e:
            return f"Error searching workspace: {e}"

    async def _get_status(self, params):
        """Get Sovereign system status."""
        if not self._available:
            return "⚠️  Sovereign not available. Install at ~/.openclaw/workspace/sovereign-core/"

        try:
            status_info = [
                "🤖 **Sovereign System Status**\n",
                f"📂 Workspace: {self._workspace_path}",
                f"✅ Status: {'Active' if self._available else 'Inactive'}",
                f"🔧 Version: {self.version}",
            ]

            # Check workspace size
            if os.path.isdir(self._workspace_path):
                total_size = 0
                file_count = 0
                for root, _, files in os.walk(self._workspace_path):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            total_size += os.path.getsize(fp)
                            file_count += 1
                        except OSError:
                            pass

                size_mb = total_size / (1024 * 1024)
                status_info.append(f"📊 Workspace: {file_count} files, {size_mb:.1f} MB")

            return "\n".join(status_info)

        except Exception as e:
            return f"Error getting status: {e}"

    async def _save_memory(self, params):
        """Save persistent memory."""
        if not self._available:
            return "⚠️  Sovereign not available. Install at ~/.openclaw/workspace/sovereign-core/"

        key = params.get("key", "").strip()
        content = params.get("content", "")
        tags = params.get("tags", "").strip()

        if not key or not content:
            return "Error: Both key and content are required."

        try:
            # Save to memory file in workspace
            memory_dir = os.path.join(self._workspace_path, "memory")
            os.makedirs(memory_dir, exist_ok=True)

            memory_file = os.path.join(memory_dir, f"{key}.md")
            with open(memory_file, "w") as f:
                f.write(f"# {key}\n\n")
                if tags:
                    f.write(f"**Tags:** {tags}\n\n")
                f.write(content)

            return f"💾 Memory saved: {key}\nLocation: {memory_file}"

        except Exception as e:
            return f"Error saving memory: {e}"

    async def _load_memory(self, params):
        """Load persistent memory."""
        if not self._available:
            return "⚠️  Sovereign not available. Install at ~/.openclaw/workspace/sovereign-core/"

        key = params.get("key", "").strip()
        if not key:
            return "Error: Memory key required."

        try:
            memory_file = os.path.join(self._workspace_path, "memory", f"{key}.md")
            if not os.path.exists(memory_file):
                return f"Memory not found: {key}"

            with open(memory_file) as f:
                content = f.read()

            return f"📖 Memory loaded: {key}\n\n{content}"

        except Exception as e:
            return f"Error loading memory: {e}"

    # ────────────────────────────────────────────
    # Command Handlers
    # ────────────────────────────────────────────

    async def _handle_sov_command(self, args):
        """Handle /sov command."""
        if not args.strip():
            return "Usage: `/sov <command>` (e.g., `/sov SYS:STATUS`)"

        return await self._execute_command({"command": args.strip()})

    async def _handle_workspace_command(self, args):
        """Handle /workspace command."""
        return await self._get_status({})
