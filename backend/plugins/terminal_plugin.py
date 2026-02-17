"""Terminal Plugin — Terminal, tmux, and Claude Code control.

Provides tools for:
- Terminal.app control (list windows, read output, execute commands, new windows/tabs)
- tmux session management (list, send commands, capture output, new sessions)
- Claude Code integration (new sessions, send messages, read output, list sessions)

Terminal control via osascript targeting "Terminal".
tmux and Claude Code via subprocess commands.
"""

import asyncio
import json
import logging
import os
import re

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.terminal")

MAX_EXEC_TIME = 30  # seconds


class TerminalPlugin(NexusPlugin):
    name = "terminal"
    description = "Terminal, tmux, and Claude Code control — execute commands, manage sessions"
    version = "1.0.0"

    _session_manager = None  # Injected by app.py after plugin load

    def set_session_manager(self, manager):
        """Inject the Claude session manager (called from app.py post-setup)."""
        self._session_manager = manager

    async def setup(self):
        logger.info("  Terminal plugin ready")
        return True

    def register_tools(self):
        # ── Terminal.app Control ──
        self.add_tool(
            "terminal_list_windows",
            "List all Terminal.app windows with their tabs",
            {},
            self._terminal_list_windows,
            category="code",
        )
        self.add_tool(
            "terminal_read",
            "Read the output from a Terminal window (or current window if no ID specified)",
            {"window_id": "Optional: window ID to read from (1-based index)"},
            self._terminal_read,
            category="code",
        )
        self.add_tool(
            "terminal_execute",
            "Execute a command in a Terminal window",
            {
                "command": "Command to execute",
                "window_id": "Optional: window ID to execute in (defaults to current window)",
            },
            self._terminal_execute,
            category="code",
        )
        self.add_tool(
            "terminal_new_window",
            "Open a new Terminal window, optionally running a command",
            {"command": "Optional: command to run in the new window"},
            self._terminal_new_window,
            category="code",
        )
        self.add_tool(
            "terminal_new_tab",
            "Open a new Terminal tab in the current window, optionally running a command",
            {"command": "Optional: command to run in the new tab"},
            self._terminal_new_tab,
            category="code",
        )

        # ── tmux Control ──
        self.add_tool(
            "tmux_list_sessions",
            "List all tmux sessions with their windows",
            {},
            self._tmux_list_sessions,
            category="code",
        )
        self.add_tool(
            "tmux_send",
            "Send a command to a tmux session (types the command and presses Enter)",
            {"session": "Session name or index", "command": "Command to send"},
            self._tmux_send,
            category="code",
        )
        self.add_tool(
            "tmux_capture",
            "Capture the visible output from a tmux session/pane",
            {"session": "Session name or index"},
            self._tmux_capture,
            category="code",
        )
        self.add_tool(
            "tmux_new_session",
            "Create a new tmux session, optionally running a command",
            {"name": "Session name", "command": "Optional: command to run in the session"},
            self._tmux_new_session,
            category="code",
        )

        # ── Claude Code Interactive Sessions ──
        self.add_tool(
            "claude_session_start",
            "Start a new persistent Claude Code session with bidirectional communication",
            {
                "prompt": "Initial prompt for Claude Code",
                "directory": "Optional: working directory (default: home dir)",
                "name": "Optional: session name for reference",
            },
            self._claude_session_start,
            category="code",
        )
        self.add_tool(
            "claude_session_send",
            "Send a follow-up message to a running Claude Code session",
            {"session_id": "Session ID to send to", "message": "Message to send"},
            self._claude_session_send,
            category="code",
        )
        self.add_tool(
            "claude_session_read",
            "Read recent output from a Claude Code session",
            {"session_id": "Session ID to read from", "last_n": "Optional: number of recent lines (default: 50)"},
            self._claude_session_read,
            category="code",
        )
        self.add_tool(
            "claude_session_list",
            "List all Claude Code sessions (active and recent)",
            {},
            self._claude_session_list,
            category="code",
        )
        self.add_tool(
            "claude_session_stop",
            "Stop a running Claude Code session",
            {"session_id": "Session ID to stop"},
            self._claude_session_stop,
            category="code",
        )

    def register_commands(self):
        self.add_command("terminal", "Execute in Terminal: /terminal <command>", self._handle_terminal)
        self.add_command("tmux", "tmux control: /tmux <action> [args]", self._handle_tmux)
        self.add_command("claude-code", "Claude Code: /claude-code <prompt>", self._handle_claude_code)

    # ────────────────────────────────────────────
    # Terminal.app Control
    # ────────────────────────────────────────────

    async def _terminal_list_windows(self, params):
        script = '''
        tell application "Terminal"
            if (count of windows) = 0 then
                return "No Terminal windows open"
            end if

            set output to ""
            repeat with w from 1 to (count of windows)
                set windowName to name of window w
                set tabCount to count of tabs of window w
                set output to output & "Window " & w & ": " & windowName & " (" & tabCount & " tabs)\\n"
            end repeat
            return output
        end tell
        '''
        result = await self._run_osascript(script)
        return f"🖥️ **Terminal Windows:**\n{result}"

    async def _terminal_read(self, params):
        window_id = params.get("window_id", "").strip()

        if window_id:
            script = f'''
            tell application "Terminal"
                if (count of windows) >= {window_id} then
                    get contents of selected tab of window {window_id}
                else
                    return "Window {window_id} not found"
                end if
            end tell
            '''
        else:
            script = '''
            tell application "Terminal"
                if (count of windows) > 0 then
                    get contents of selected tab of front window
                else
                    return "No Terminal windows open"
                end if
            end tell
            '''

        result = await self._run_osascript(script)
        if len(result) > 5000:
            result = result[-5000:] + "\n\n... (truncated, showing last 5000 chars)"

        return f"Terminal output:\n```\n{result}\n```"

    async def _terminal_execute(self, params):
        command = params.get("command", "").strip()
        window_id = params.get("window_id", "").strip()

        if not command:
            return "Error: command is required"

        # Escape special characters for AppleScript
        command = command.replace("\\", "\\\\").replace('"', '\\"')

        if window_id:
            script = f'''
            tell application "Terminal"
                if (count of windows) >= {window_id} then
                    do script "{command}" in selected tab of window {window_id}
                    return "Command sent to window {window_id}"
                else
                    return "Window {window_id} not found"
                end if
            end tell
            '''
        else:
            script = f'''
            tell application "Terminal"
                if (count of windows) > 0 then
                    do script "{command}" in front window
                    return "Command sent"
                else
                    do script "{command}"
                    return "Command sent in new window"
                end if
            end tell
            '''

        result = await self._run_osascript(script)
        return f"✅ {result}"

    async def _terminal_new_window(self, params):
        command = params.get("command", "").strip()

        if command:
            command = command.replace("\\", "\\\\").replace('"', '\\"')
            script = f'''
            tell application "Terminal"
                do script "{command}"
                activate
            end tell
            '''
        else:
            script = '''
            tell application "Terminal"
                do script ""
                activate
            end tell
            '''

        await self._run_osascript(script)
        return "✅ Opened new Terminal window"

    async def _terminal_new_tab(self, params):
        command = params.get("command", "").strip()

        if command:
            command = command.replace("\\", "\\\\").replace('"', '\\"')
            script = f'''
            tell application "Terminal"
                tell front window
                    set newTab to do script "{command}" in (make new tab)
                end tell
                activate
            end tell
            '''
        else:
            script = '''
            tell application "Terminal"
                tell front window
                    set newTab to do script "" in (make new tab)
                end tell
                activate
            end tell
            '''

        await self._run_osascript(script)
        return "✅ Opened new Terminal tab"

    # ────────────────────────────────────────────
    # tmux Control
    # ────────────────────────────────────────────

    async def _tmux_list_sessions(self, params):
        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux",
                "list-sessions",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode != 0:
                err = stderr.decode().strip()
                if "no server running" in err.lower():
                    return "No tmux server running (no sessions active)"
                return f"Error: {err}"

            sessions = stdout.decode().strip()
            if not sessions:
                return "No tmux sessions found"

            return f"🔷 **tmux Sessions:**\n```\n{sessions}\n```"

        except FileNotFoundError:
            return "Error: tmux not installed. Install with: brew install tmux"
        except Exception as e:
            return f"Error: {e}"

    async def _tmux_send(self, params):
        session = params.get("session", "").strip()
        command = params.get("command", "").strip()

        if not session or not command:
            return "Error: both session and command are required"

        try:
            # Send keys to the tmux session
            proc = await asyncio.create_subprocess_exec(
                "tmux",
                "send-keys",
                "-t",
                session,
                command,
                "Enter",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode != 0:
                err = stderr.decode().strip()
                return f"Error sending to tmux: {err}"

            return f"✅ Command sent to tmux session '{session}'"

        except FileNotFoundError:
            return "Error: tmux not installed"
        except Exception as e:
            return f"Error: {e}"

    async def _tmux_capture(self, params):
        session = params.get("session", "").strip()

        if not session:
            return "Error: session is required"

        try:
            # Capture pane contents
            proc = await asyncio.create_subprocess_exec(
                "tmux",
                "capture-pane",
                "-t",
                session,
                "-p",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode != 0:
                err = stderr.decode().strip()
                return f"Error capturing tmux pane: {err}"

            output = stdout.decode().strip()
            if len(output) > 5000:
                output = output[-5000:] + "\n\n... (truncated, showing last 5000 chars)"

            return f"tmux session '{session}' output:\n```\n{output}\n```"

        except FileNotFoundError:
            return "Error: tmux not installed"
        except Exception as e:
            return f"Error: {e}"

    async def _tmux_new_session(self, params):
        name = params.get("name", "").strip()
        command = params.get("command", "").strip()

        if not name:
            return "Error: name is required"

        try:
            args = ["tmux", "new-session", "-d", "-s", name]
            if command:
                args.extend([command])

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode != 0:
                err = stderr.decode().strip()
                return f"Error creating tmux session: {err}"

            return f"✅ Created tmux session '{name}'"

        except FileNotFoundError:
            return "Error: tmux not installed"
        except Exception as e:
            return f"Error: {e}"

    # ────────────────────────────────────────────
    # Claude Code Interactive Sessions
    # ────────────────────────────────────────────

    async def _claude_session_start(self, params):
        prompt = params.get("prompt", "").strip()
        directory = params.get("directory", "~").strip()
        name = params.get("name", "").strip()

        if not prompt:
            return "Error: prompt is required"

        if not self._session_manager:
            return "Error: Claude session manager not available"

        try:
            session = await self._session_manager.create_session(
                prompt=prompt,
                directory=directory,
                name=name,
            )
            return (
                f"✅ Started Claude Code session `{session.id}` ({session.name})\n"
                f"Directory: {session.directory}\n"
                f"Model: {session.model}\n\n"
                f"Use `claude_session_read` with session_id=`{session.id}` to check output,\n"
                f"or `claude_session_send` to send follow-up messages."
            )
        except Exception as e:
            return f"Error starting session: {e}"

    async def _claude_session_send(self, params):
        session_id = params.get("session_id", "").strip()
        message = params.get("message", "").strip()

        if not session_id or not message:
            return "Error: both session_id and message are required"

        if not self._session_manager:
            return "Error: Claude session manager not available"

        ok = await self._session_manager.send_message(session_id, message)
        if ok:
            return f"✅ Sent follow-up to session `{session_id}` ({len(message)} chars)"
        return f"Error: session `{session_id}` not found or not running"

    async def _claude_session_read(self, params):
        session_id = params.get("session_id", "").strip()
        last_n = int(params.get("last_n", "50"))

        if not session_id:
            return "Error: session_id is required"

        if not self._session_manager:
            return "Error: Claude session manager not available"

        session = self._session_manager.get_session(session_id)
        if not session:
            return f"Error: session `{session_id}` not found"

        output = self._session_manager.read_output(session_id, last_n)
        status_icon = "🟢" if session.status == "running" else "✅" if session.status == "completed" else "❌"
        header = f"{status_icon} Session `{session_id}` ({session.name}) — {session.status}"
        if session.cost_usd > 0:
            header += f" — ${session.cost_usd:.4f}"

        if not output:
            return f"{header}\n\n(no output yet)"

        return f"{header}\n\n```\n{output}\n```"

    async def _claude_session_list(self, params):
        if not self._session_manager:
            return "Error: Claude session manager not available"

        sessions = self._session_manager.list_sessions()
        if not sessions:
            return "No Claude Code sessions found."

        lines = []
        for s in sessions:
            icon = "🟢" if s["status"] == "running" else "✅" if s["status"] == "completed" else "❌"
            lines.append(
                f"| `{s['id']}` | {icon} {s['status']} | {s['name']} | "
                f"{s['model']} | ${s.get('cost_usd', 0):.4f} | {len(s.get('tools_used', []))} tools |"
            )

        return (
            "🤖 **Claude Code Sessions:**\n\n"
            "| ID | Status | Name | Model | Cost | Tools |\n"
            "|----|--------|------|-------|------|-------|\n"
            + "\n".join(lines)
        )

    async def _claude_session_stop(self, params):
        session_id = params.get("session_id", "").strip()

        if not session_id:
            return "Error: session_id is required"

        if not self._session_manager:
            return "Error: Claude session manager not available"

        ok = await self._session_manager.stop_session(session_id)
        if ok:
            return f"✅ Session `{session_id}` stopped."
        return f"Error: session `{session_id}` not found"

    # ────────────────────────────────────────────
    # Command Handlers
    # ────────────────────────────────────────────

    async def _handle_terminal(self, args):
        command = args.strip()
        if not command:
            return "Usage: /terminal <command>"
        return await self._terminal_execute({"command": command})

    async def _handle_tmux(self, args):
        parts = args.strip().split(None, 1)
        if not parts:
            return "Usage: /tmux <list|send|capture|new> [args]"

        action = parts[0].lower()

        if action == "list":
            return await self._tmux_list_sessions({})
        elif action == "send":
            if len(parts) < 2:
                return "Usage: /tmux send <session> <command>"
            # Parse session and command
            args_parts = parts[1].split(None, 1)
            if len(args_parts) < 2:
                return "Usage: /tmux send <session> <command>"
            return await self._tmux_send({"session": args_parts[0], "command": args_parts[1]})
        elif action == "capture":
            if len(parts) < 2:
                return "Usage: /tmux capture <session>"
            return await self._tmux_capture({"session": parts[1]})
        elif action == "new":
            if len(parts) < 2:
                return "Usage: /tmux new <session_name> [command]"
            args_parts = parts[1].split(None, 1)
            name = args_parts[0]
            command = args_parts[1] if len(args_parts) > 1 else ""
            return await self._tmux_new_session({"name": name, "command": command})
        else:
            return f"Unknown action: {action}. Use: list, send, capture, new"

    async def _handle_claude_code(self, args):
        prompt = args.strip()
        if not prompt:
            return "Usage: /claude-code <prompt>"
        return await self._claude_session_start({"prompt": prompt})

    # ────────────────────────────────────────────
    # Helper
    # ────────────────────────────────────────────

    async def _run_osascript(self, script: str) -> str:
        """Execute AppleScript and return output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=MAX_EXEC_TIME)

            result = stdout.decode().strip()
            if stderr:
                err = stderr.decode().strip()
                if err and "execution error" in err.lower():
                    return f"Error: {err}"

            return result
        except asyncio.TimeoutError:
            return f"⏱ Timed out after {MAX_EXEC_TIME}s"
        except Exception as e:
            return f"Error: {e}"
