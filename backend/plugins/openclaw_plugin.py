"""OpenClaw plugin — bridge status, sovereign commands, and service monitoring."""

import logging

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.openclaw")


class OpenClawPlugin(NexusPlugin):
    name = "openclaw"
    description = "OpenClaw integration — bridge status, sovereign commands, service health"
    version = "1.0.0"

    async def setup(self):
        # These refs are set by app.py lifespan after integration init
        self._bridge_ref = None
        self._sovereign_ref = None
        self._monitor_ref = None
        logger.info("OpenClaw plugin ready")
        return True

    def register_tools(self):
        self.add_tool(
            "openclaw_status",
            "Get OpenClaw bridge connection status",
            {},
            self._bridge_status,
        )
        self.add_tool(
            "openclaw_send_command",
            "Send a command through the OpenClaw bridge",
            {"command": "Command to send (e.g. /status)"},
            self._send_command,
        )
        self.add_tool(
            "sovereign_execute",
            "Execute a sovereign command (e.g. SYS:STATUS, BLD:APP)",
            {"command": "Sovereign command string", "context": "Optional context"},
            self._sovereign_execute,
        )
        self.add_tool(
            "sovereign_list",
            "List available sovereign commands",
            {},
            self._sovereign_list,
        )

    def register_commands(self):
        self.add_command("openclaw", "OpenClaw bridge: /openclaw status|connect", self._cmd_openclaw)
        self.add_command("sovereign", "Sovereign command: /sovereign <CMD:ACTION> [args]", self._cmd_sovereign)
        self.add_command("services", "Platform service health: /services", self._cmd_services)

    # ── Tool Handlers ──

    async def _bridge_status(self, params: dict) -> str:
        bridge = self._bridge_ref
        if not bridge:
            return "OpenClaw bridge not configured. Set OPENCLAW_ENABLED=true and OPENCLAW_GATEWAY_URL in .env."

        status = bridge.get_status()
        connected = "Connected" if status["connected"] else "Disconnected"
        return (
            f"**OpenClaw Bridge: {connected}**\n"
            f"Gateway: {status.get('gateway_url', 'N/A')}\n"
            f"Events: {status.get('events_received', 0)} received, {status.get('events_sent', 0)} sent\n"
            f"Tasks routed: {status.get('tasks_routed', 0)}\n"
            f"Pending messages: {status.get('pending_messages', 0)}\n"
            f"Active tasks: {status.get('active_tasks', 0)}"
        )

    async def _send_command(self, params: dict) -> str:
        bridge = self._bridge_ref
        if not bridge:
            return "OpenClaw bridge not available."

        command = params.get("command", "")
        if not command:
            return "Error: command is required"

        from integrations.openclaw_bridge import EventType
        await bridge.send_event(EventType.COMMAND_RESULT, {
            "command": command,
            "source": "nexus-plugin",
        })
        return f"Command sent to OpenClaw: {command}"

    async def _sovereign_execute(self, params: dict) -> str:
        sovereign = self._sovereign_ref
        if not sovereign:
            return "Sovereign-core client not configured. Set SOVEREIGN_CORE_URL in .env."

        command = params.get("command", "").strip()
        context = params.get("context", "")
        if not command:
            return "Error: command is required (e.g. SYS:STATUS, BLD:APP)"

        result = await sovereign.execute(command, context)
        if "error" in result:
            return f"Sovereign error: {result['error']}"

        content = result.get("content", "No response")
        tier = result.get("tier", "?")
        model = result.get("model", "?")
        duration = result.get("duration_ms", 0)
        return f"**[{tier}] {command}** (via {model}, {duration:.0f}ms)\n\n{content}"

    async def _sovereign_list(self, params: dict) -> str:
        sovereign = self._sovereign_ref
        if not sovereign:
            return "Sovereign-core client not configured."

        result = await sovereign.list_commands()
        if "error" in result:
            return f"Error: {result['error']}"

        commands = result.get("commands", [])
        if not commands:
            return "No sovereign commands available."

        lines = ["**Sovereign Commands:**"]
        for cmd in commands:
            if isinstance(cmd, dict):
                lines.append(f"- **{cmd.get('prefix', '?')}:{cmd.get('action', '?')}** — {cmd.get('description', '')}")
            else:
                lines.append(f"- {cmd}")
        return "\n".join(lines)

    # ── Slash Commands ──

    async def _cmd_openclaw(self, args: str) -> str:
        sub = args.strip().lower()
        if sub == "status" or not sub:
            return await self._bridge_status({})
        return "Usage: `/openclaw status`"

    async def _cmd_sovereign(self, args: str) -> str:
        if not args.strip():
            return (
                "**Sovereign Commands:**\n"
                "- `/sovereign SYS:STATUS` — system status\n"
                "- `/sovereign BLD:APP <description>` — build PRD\n"
                "- `/sovereign ANZ:CODE <code>` — analyze code\n"
                "- `/sovereign QRY:SEARCH <query>` — query search"
            )
        parts = args.strip().split(None, 1)
        command = parts[0]
        context = parts[1] if len(parts) > 1 else ""
        return await self._sovereign_execute({"command": command, "context": context})

    async def _cmd_services(self, args: str) -> str:
        monitor = self._monitor_ref
        if not monitor:
            return "Service monitor not available."
        return monitor.get_summary()
