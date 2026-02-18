"""Sovereign Plugin - Build procedures, workspace search, and memory persistence.

Provides:
- BLD: commands — real build/dev procedures (BLD:APP, BLD:DEV, BLD:TEST)
- ANZ: commands — analysis procedures
- SYS: commands — system status
- Workspace search and persistent memory
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.sovereign")


class SovereignPlugin(NexusPlugin):
    name = "sovereign"
    description = "Sovereign AI integration - master commands, workspace search, persistent memory"
    version = "1.0.0"

    def __init__(self, config, db, router):
        super().__init__(config, db, router)
        self._available = False
        self._sovereign = None
        self._workspace_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "sovereign"
        )
        self._active_procedure = None
        self._session_manager = None
        self._cc_session_ids: list[str] = []  # Active Claude Code sessions for BLD:APP

    def set_session_manager(self, manager):
        """Inject the Claude session manager (called from app.py post-setup)."""
        self._session_manager = manager

    async def setup(self):
        """Try to import sovereign module from workspace.

        Sovereign-core uses bare imports like ``from storage import SovereignStorage``
        which collide with Nexus's own ``backend/storage`` package.  To work around
        this, we pre-register sovereign's subpackages in ``sys.modules`` so they
        resolve before Nexus's modules.
        """
        try:
            if not os.path.isdir(self._workspace_path):
                logger.warning(f"⚠️  Sovereign workspace not found at {self._workspace_path}")
                self._available = False
                return True

            import importlib.util

            # Sovereign uses bare imports (``from storage import ...``) that collide
            # with Nexus's own packages.  We temporarily put sovereign-core/ first on
            # sys.path, import the package, then restore the path.
            old_path = sys.path[:]
            saved_modules = {}

            # Names that sovereign's __init__.py imports with bare ``from X import ...``
            # AND that clash with Nexus modules:
            clash_names = ["storage"]

            try:
                # Temporarily hide Nexus's conflicting modules
                for name in clash_names:
                    if name in sys.modules:
                        saved_modules[name] = sys.modules.pop(name)

                # Put sovereign-core first so its subpackages win path resolution
                sys.path.insert(0, self._workspace_path)

                # Also register 'sovereign' as the sovereign.py file so
                # ``from sovereign import Sovereign`` works
                sov_py = os.path.join(self._workspace_path, "sovereign.py")
                if os.path.isfile(sov_py):
                    sov_spec = importlib.util.spec_from_file_location("sovereign", sov_py)
                    if sov_spec and sov_spec.loader:
                        sov_mod = importlib.util.module_from_spec(sov_spec)
                        sys.modules["sovereign"] = sov_mod
                        sov_spec.loader.exec_module(sov_mod)

                # Now import the __init__.py which does bare imports
                spec = importlib.util.spec_from_file_location(
                    "sovereign_pkg",
                    os.path.join(self._workspace_path, "__init__.py"),
                    submodule_search_locations=[self._workspace_path],
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    self._sovereign = mod
                    self._available = True
                    logger.info(f"✅ Sovereign-Core loaded from {self._workspace_path}")
                else:
                    logger.warning("⚠️  Could not create module spec for sovereign-core")
                    self._available = False
            except Exception as e:
                logger.warning(f"⚠️  Sovereign module import failed: {e}")
                self._available = False
            finally:
                # Restore sys.path and any modules we displaced
                sys.path = old_path
                for name, mod in saved_modules.items():
                    sys.modules[name] = mod

        except Exception as e:
            logger.error(f"❌ Failed to setup Sovereign plugin: {e}")
            self._available = False

        return True  # Plugin loads even if sovereign is unavailable

    def register_tools(self):
        """Register Sovereign AI tools."""
        self.add_tool(
            "sovereign_execute",
            "Execute build/dev procedures: BLD:APP (full dev env + Claude Code), BLD:BUILD (conductor multi-agent build), BLD:DEV (servers), BLD:TEST, BLD:STOP, ANZ:CODE, SYS:STATUS",
            {"command": "Procedure command (e.g., 'BLD:APP', 'BLD:BUILD <task>', 'BLD:DEV', 'SYS:STATUS', 'BLD:STOP')"},
            self._execute_command,
            category="workspace",
        )

        self.add_tool(
            "conductor_build",
            "Start a conductor-orchestrated multi-agent build: plan → research → build → review → test. Reactive loops on review failure (max 3 cycles).",
            {
                "task": "What to build — be specific (e.g., 'Add REST API endpoints for user management with auth and tests')",
                "builder_model": "Optional: model for builder agent (default: claude_code)",
                "reviewer_model": "Optional: model for reviewer agent (default: claude_code)",
                "auto_test": "Optional: run tests after build (default: true)",
            },
            self._conductor_build,
            category="workspace",
        )

        self.add_tool(
            "sovereign_search",
            "Search the Sovereign workspace for files, code patterns, or documentation. Returns ranked results.",
            {
                "query": "Search query (keywords, file patterns, or code snippets)",
                "limit": "Max results to return (default: 10)",
            },
            self._search_workspace,
            category="workspace",
        )

        self.add_tool(
            "sovereign_status",
            "Get current Sovereign system status including active processes, memory usage, and workspace state.",
            {},
            self._get_status,
            category="workspace",
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
            category="workspace",
        )

        self.add_tool(
            "sovereign_memory_load",
            "Load persistent memory from Sovereign knowledge base by key.",
            {"key": "Memory key to retrieve"},
            self._load_memory,
            category="workspace",
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
        """Execute a Sovereign master command (BLD:, ANZ:, SYS:).

        BLD:APP [project_dir]  — Full dev environment: Claude Code agent + tmux sessions
        BLD:DEV [project_dir]  — Dev server only (tmux sessions, no model switch)
        BLD:TEST [project_dir] — Run test suite
        ANZ:CODE [path]        — Analyze codebase
        SYS:STATUS             — System/procedure status
        SYS:STOP               — Tear down running procedures
        """
        command = params.get("command", "").strip()
        if not command:
            return "Error: No command provided."

        try:
            if ":" not in command:
                return self._get_command_help()

            parts = command.split(None, 1)
            cmd = parts[0].upper()
            args = parts[1] if len(parts) > 1 else ""

            # ── BLD: Build/Development Procedures ──
            if cmd == "BLD:APP":
                return await self._bld_app(args)
            elif cmd == "BLD:BUILD":
                return await self._bld_build(args)
            elif cmd == "BLD:DEV":
                return await self._bld_dev(args)
            elif cmd == "BLD:TEST":
                return await self._bld_test(args)

            # ── ANZ: Analysis Procedures ──
            elif cmd == "BLD:STOP" or cmd == "SYS:STOP":
                return await self._procedure_stop()
            elif cmd.startswith("ANZ:"):
                return await self._anz_code(args, cmd)

            # ── SYS: System Procedures ──
            elif cmd == "SYS:STATUS":
                return await self._sys_status()

            else:
                return self._get_command_help()

        except Exception as e:
            logger.exception(f"Error executing command '{command}'")
            return f"❌ Error executing '{command}': {e}"

    def _get_command_help(self):
        return """📋 **Sovereign Commands**

**Build:**
  `BLD:APP [dir]`    — Full dev environment (Claude Code + tmux sessions)
  `BLD:BUILD <task>` — Conductor multi-agent build (plan→research→build→review→test)
  `BLD:DEV [dir]`    — Dev server only (tmux sessions, no model switch)
  `BLD:TEST [dir]`   — Run test suite in project
  `BLD:STOP`         — Tear down running procedures

**Analysis:**
  `ANZ:CODE [path]` — Analyse codebase structure

**System:**
  `SYS:STATUS` — Show running procedures & system state
  `SYS:STOP`   — Stop all procedures"""

    async def _run_shell(self, cmd: str, timeout: int = 15) -> str:
        """Run a shell command and return output."""
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode().strip()
            if proc.returncode != 0:
                err = stderr.decode().strip()
                return f"(exit {proc.returncode}) {err or output}"
            return output
        except asyncio.TimeoutError:
            return "(timed out)"
        except Exception as e:
            return f"(error: {e})"

    async def _tmux_session_exists(self, name: str) -> bool:
        """Check if a tmux session exists."""
        result = await self._run_shell(f"tmux has-session -t {name} 2>/dev/null && echo yes || echo no")
        return result.strip() == "yes"

    async def _tmux_create(self, name: str, command: str = "", cwd: str = "") -> str:
        """Create a tmux session."""
        cmd_parts = ["tmux", "new-session", "-d", "-s", name]
        if cwd:
            cmd_parts.extend(["-c", cwd])
        if command:
            cmd_parts.append(command)
        return await self._run_shell(" ".join(cmd_parts))

    async def _tmux_send_cmd(self, session: str, command: str) -> str:
        """Send a command to a tmux session."""
        # Escape single quotes in the command
        safe_cmd = command.replace("'", "'\\''")
        return await self._run_shell(f"tmux send-keys -t {session} '{safe_cmd}' Enter")

    async def _bld_app(self, args: str) -> str:
        """BLD:APP — Full dev environment with Claude Code and terminal sessions.

        Sets up:
        1. Switches model to Claude Code (agentic mode)
        2. Creates tmux sessions: nexus-server, nexus-dev, nexus-logs
        3. Starts server and dev processes
        4. All terminals controlled by Nexus regardless of model
        """
        project_dir = args.strip() or "/Users/lennyfinn/Nexus"
        backend_dir = os.path.join(project_dir, "backend")
        admin_dir = os.path.join(project_dir, "admin-ui")

        if not os.path.isdir(project_dir):
            return f"❌ Project directory not found: {project_dir}"

        lines = ["🔨 **BLD:APP — Starting Full Dev Environment**\n"]

        # Step 1: Switch model to Claude Code
        try:
            from routers.ws import websocket_manager
            # Set force_model for all active sessions
            for ws_id in list(websocket_manager.active_connections.keys()):
                websocket_manager.update_session_data(ws_id, {"force_model": "claude_code"})
                await websocket_manager.send_to_client(
                    ws_id, {"type": "system", "content": "⚡ BLD:APP — Model switched to Claude Code (agentic)"}
                )
            lines.append("✅ Model → Claude Code (agentic mode with MCP tools)")
        except Exception as e:
            lines.append(f"⚠️  Model switch: {e} (set manually with `/model code`)")

        # Step 2: Create tmux sessions
        sessions_created = []

        # Server session
        if not await self._tmux_session_exists("nexus-server"):
            await self._tmux_create("nexus-server", cwd=backend_dir)
            await self._tmux_send_cmd("nexus-server",
                f"source {project_dir}/venv/bin/activate && cd {backend_dir} && python3 -m uvicorn app:create_app --factory --host 0.0.0.0 --port 8080 --reload")
            sessions_created.append("nexus-server (uvicorn)")
        else:
            lines.append("ℹ️  nexus-server already running")

        # Dev session (frontend build/watch)
        if not await self._tmux_session_exists("nexus-dev"):
            if os.path.isdir(admin_dir):
                await self._tmux_create("nexus-dev", cwd=admin_dir)
                await self._tmux_send_cmd("nexus-dev", "npm run dev")
                sessions_created.append("nexus-dev (frontend)")
        else:
            lines.append("ℹ️  nexus-dev already running")

        # Logs/monitoring session
        if not await self._tmux_session_exists("nexus-logs"):
            await self._tmux_create("nexus-logs", cwd=backend_dir)
            log_file = os.path.join(backend_dir, "logs", "access.log")
            if os.path.exists(log_file):
                await self._tmux_send_cmd("nexus-logs", f"tail -f {log_file}")
            else:
                await self._tmux_send_cmd("nexus-logs", f"echo 'Waiting for logs...' && ls -la {backend_dir}/logs/ 2>/dev/null")
            sessions_created.append("nexus-logs (tail)")
        else:
            lines.append("ℹ️  nexus-logs already running")

        # Work session (Claude Code / general dev terminal)
        if not await self._tmux_session_exists("nexus-work"):
            await self._tmux_create("nexus-work", cwd=project_dir)
            sessions_created.append("nexus-work (dev terminal)")
        else:
            lines.append("ℹ️  nexus-work already running")

        if sessions_created:
            lines.append(f"✅ tmux sessions: {', '.join(sessions_created)}")

        # Step 3: Record active procedure
        self._active_procedure = {
            "type": "BLD:APP",
            "project_dir": project_dir,
            "started_at": datetime.now().isoformat(),
            "sessions": ["nexus-server", "nexus-dev", "nexus-logs", "nexus-work"],
        }

        # Step 4: Start managed Claude Code session(s)
        # Boris Cherny multi-agent pattern — starts a primary builder session.
        # Additional agent sessions can be spawned via /cc or claude_multi_agent tool.
        self._cc_session_ids = []
        if self._session_manager:
            try:
                session = await self._session_manager.create_session(
                    prompt=(
                        f"You are working on the Nexus project at {project_dir}. "
                        f"The dev environment is ready with tmux sessions: nexus-server (uvicorn), "
                        f"nexus-dev (frontend), nexus-logs (tail), nexus-work (general). "
                        f"You have full MCP access to all Nexus tools. Ready for instructions."
                    ),
                    directory=project_dir,
                    name="nexus-build",
                    role="builder",
                )
                self._cc_session_ids.append(session.id)
                lines.append(f"✅ Claude Code session: `{session.id}` (nexus-build, role=builder)")
                lines.append(f"   💡 Spawn more agents: `/cc <prompt>` or use `claude_multi_agent` tool (up to 5)")
            except Exception as e:
                lines.append(f"⚠️  Claude Code session: {e}")

        lines.append(f"\n📂 Project: `{project_dir}`")
        lines.append(f"🖥️  Terminals: `tmux attach -t nexus-server` (or -dev, -logs, -work)")
        lines.append(f"\n✅ **Dev environment ready.** Claude Code has full MCP access to all Nexus tools.")
        lines.append(f"   All terminal sessions are controllable via Nexus regardless of active model.")

        return "\n".join(lines)

    async def _bld_build(self, args: str) -> str:
        """BLD:BUILD <task> — Conductor-orchestrated multi-agent build.

        Uses the OrchestratorConductor to run a full build cycle:
        PLAN → RESEARCH → BUILD → REVIEW → FIX (if needed) → TEST

        The conductor manages:
        - Multiple Claude Code agents (builder, reviewer)
        - Reactive loops (review fails → fix → review again, max 3 cycles)
        - Git branch per build (merge on approval)
        - Full event streaming to WebSocket/KanBan
        """
        task = args.strip()
        if not task:
            return (
                "❌ BLD:BUILD requires a task description.\n"
                "Usage: `BLD:BUILD Add REST API endpoints for user management with auth and tests`"
            )

        lines = ["🔨 **BLD:BUILD — Conductor Multi-Agent Build**\n"]
        lines.append(f"📋 Task: {task[:200]}")

        try:
            from core.conductor import OrchestratorConductor, ConductorConfig

            # Get the app state (injected during plugin setup)
            state = getattr(self, '_app_state', None)
            if not state:
                # Try to get state from the router
                state = getattr(self.router, 'state', None) if self.router else None

            if not state:
                return "❌ App state not available. Ensure BLD:APP is running first."

            config = ConductorConfig()

            # Get ws_id for streaming (use the first connected WebSocket)
            ws_id = None
            try:
                from routers.ws import websocket_manager
                for wid in list(websocket_manager.connections.keys()):
                    ws_id = wid
                    break
            except Exception:
                pass

            conductor = OrchestratorConductor(
                task=task,
                state=state,
                ws_id=ws_id,
                config=config,
            )

            lines.append(f"🆔 Conductor: `{conductor.run.id}`")
            lines.append(f"🤖 Builder: {config.builder_model}")
            lines.append(f"👀 Reviewer: {config.reviewer_model}")
            lines.append(f"🔄 Max cycles: {config.max_build_cycles}")
            lines.append(f"📊 Min review score: {config.min_review_score}/10")
            lines.append("\n⏳ **Build starting...** (follow progress in KanBan or chat)")

            # Run the conductor (this blocks until complete)
            result = await conductor.run_orchestration()

            lines.append(f"\n{result}")
            return "\n".join(lines)

        except ImportError as e:
            return f"❌ Conductor not available: {e}"
        except Exception as e:
            logger.exception(f"BLD:BUILD error")
            return f"❌ Build failed: {e}"

    async def _conductor_build(self, params) -> str:
        """Tool handler for conductor_build — wraps BLD:BUILD for tool calling."""
        task = params.get("task", "").strip()
        if not task:
            return "Error: task description is required"

        # Build the args string with optional overrides
        builder_model = params.get("builder_model", "").strip()
        reviewer_model = params.get("reviewer_model", "").strip()
        auto_test = params.get("auto_test", "true").strip().lower()

        # For now, pass through to _bld_build
        # Future: parse model overrides and pass to ConductorConfig
        return await self._bld_build(task)

    async def _bld_dev(self, args: str) -> str:
        """BLD:DEV — Start dev servers without model switch."""
        project_dir = args.strip() or "/Users/lennyfinn/Nexus"
        backend_dir = os.path.join(project_dir, "backend")
        admin_dir = os.path.join(project_dir, "admin-ui")

        if not os.path.isdir(project_dir):
            return f"❌ Project directory not found: {project_dir}"

        lines = ["🔧 **BLD:DEV — Starting Dev Servers**\n"]

        if not await self._tmux_session_exists("nexus-server"):
            await self._tmux_create("nexus-server", cwd=backend_dir)
            await self._tmux_send_cmd("nexus-server",
                f"source {project_dir}/venv/bin/activate && cd {backend_dir} && python3 -m uvicorn app:create_app --factory --host 0.0.0.0 --port 8080 --reload")
            lines.append("✅ nexus-server started")
        else:
            lines.append("ℹ️  nexus-server already running")

        if os.path.isdir(admin_dir) and not await self._tmux_session_exists("nexus-dev"):
            await self._tmux_create("nexus-dev", cwd=admin_dir)
            await self._tmux_send_cmd("nexus-dev", "npm run dev")
            lines.append("✅ nexus-dev started")
        elif await self._tmux_session_exists("nexus-dev"):
            lines.append("ℹ️  nexus-dev already running")

        lines.append(f"\n📂 Project: `{project_dir}`")
        return "\n".join(lines)

    async def _bld_test(self, args: str) -> str:
        """BLD:TEST — Run test suite."""
        project_dir = args.strip() or "/Users/lennyfinn/Nexus"
        backend_dir = os.path.join(project_dir, "backend")

        if not os.path.isdir(backend_dir):
            return f"❌ Backend directory not found: {backend_dir}"

        lines = ["🧪 **BLD:TEST — Running Tests**\n"]

        if not await self._tmux_session_exists("nexus-test"):
            await self._tmux_create("nexus-test", cwd=backend_dir)
        await self._tmux_send_cmd("nexus-test",
            f"source {project_dir}/venv/bin/activate && cd {backend_dir} && python3 -m pytest tests/ -v 2>&1 | head -100")
        lines.append("✅ Tests running in tmux session `nexus-test`")
        lines.append("   View: `tmux attach -t nexus-test`")
        return "\n".join(lines)

    async def _procedure_stop(self) -> str:
        """Stop all procedure sessions."""
        lines = ["🛑 **Stopping Procedures**\n"]
        sessions = ["nexus-server", "nexus-dev", "nexus-logs", "nexus-work", "nexus-test"]

        stopped = []
        for session in sessions:
            if await self._tmux_session_exists(session):
                await self._run_shell(f"tmux kill-session -t {session}")
                stopped.append(session)

        if stopped:
            lines.append(f"✅ Stopped: {', '.join(stopped)}")
        else:
            lines.append("ℹ️  No procedure sessions running")

        # Stop all managed Claude Code sessions
        if self._cc_session_ids and self._session_manager:
            for cc_id in self._cc_session_ids:
                try:
                    await self._session_manager.stop_session(cc_id)
                    lines.append(f"✅ Claude Code session `{cc_id}` stopped")
                except Exception:
                    pass
            self._cc_session_ids = []

        # Also stop any remaining Claude sessions not tracked by BLD:APP
        if self._session_manager:
            remaining = await self._session_manager.stop_all_running()
            if remaining > 0:
                lines.append(f"✅ {remaining} additional Claude session(s) stopped")

        # Reset model to auto for all websocket sessions
        try:
            from routers.ws import websocket_manager
            for ws_id in list(websocket_manager.active_connections.keys()):
                websocket_manager.update_session_data(ws_id, {"force_model": None})
            lines.append("✅ Model reset to auto (local-first)")
        except Exception:
            pass

        self._active_procedure = None
        return "\n".join(lines)

    async def _anz_code(self, args: str, cmd: str) -> str:
        """ANZ: commands — analysis."""
        target = args.strip() or "/Users/lennyfinn/Nexus"

        if not os.path.isdir(target) and not os.path.isfile(target):
            return f"❌ Path not found: {target}"

        # Quick codebase stats
        if os.path.isdir(target):
            result = await self._run_shell(
                f"find {target} -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' | "
                f"grep -v node_modules | grep -v __pycache__ | grep -v venv | wc -l"
            )
            loc_result = await self._run_shell(
                f"find {target} -name '*.py' -o -name '*.ts' -o -name '*.tsx' | "
                f"grep -v node_modules | grep -v __pycache__ | grep -v venv | "
                f"xargs wc -l 2>/dev/null | tail -1"
            )
            return f"🔍 **{cmd} — Code Analysis**\n\n📂 Path: `{target}`\n📄 Source files: {result.strip()}\n📊 Lines: {loc_result.strip()}"
        else:
            result = await self._run_shell(f"wc -l {target}")
            return f"🔍 **{cmd}**\n\n📄 File: `{target}`\n📊 {result.strip()}"

    async def _sys_status(self) -> str:
        """SYS:STATUS — Show running procedures and system state."""
        lines = ["⚙️  **System Status**\n"]

        # Check tmux sessions
        tmux_output = await self._run_shell("tmux list-sessions 2>/dev/null || echo 'No tmux sessions'")
        lines.append(f"**tmux sessions:**\n```\n{tmux_output}\n```")

        # Active procedure
        proc = getattr(self, "_active_procedure", None)
        if proc:
            lines.append(f"\n**Active Procedure:** {proc['type']}")
            lines.append(f"  Project: {proc['project_dir']}")
            lines.append(f"  Started: {proc['started_at']}")
        else:
            lines.append("\n**Active Procedure:** None")

        # Claude Code sessions
        if self._session_manager:
            cc_sessions = self._session_manager.list_sessions()
            if cc_sessions:
                lines.append(f"\n**Claude Code Sessions ({len(cc_sessions)}):**")
                for s in cc_sessions:
                    icon = "🟢" if s["status"] == "running" else "✅" if s["status"] == "completed" else "❌"
                    role = f" [{s.get('role', '')}]" if s.get("role") else ""
                    lines.append(f"  {icon} `{s['id']}` {s['name']}{role} — {s['status']} (${s.get('cost_usd', 0):.4f})")
            else:
                lines.append("\n**Claude Code Sessions:** None")

        # Model status
        try:
            from routers.ws import websocket_manager
            for ws_id in list(websocket_manager.active_connections.keys()):
                session_data = websocket_manager.get_session_data(ws_id)
                force = session_data.get("force_model", "auto") if session_data else "auto"
                lines.append(f"\n**Model (ws {ws_id[:8]}):** {force or 'auto'}")
        except Exception:
            pass

        return "\n".join(lines)

    async def _search_workspace(self, params):
        """Search the Sovereign workspace."""
        if not self._available:
            return "⚠️  Sovereign not available. Workspace not found."

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
            return "⚠️  Sovereign not available. Workspace not found."

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
            return "⚠️  Sovereign not available. Workspace not found."

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
            return "⚠️  Sovereign not available. Workspace not found."

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
