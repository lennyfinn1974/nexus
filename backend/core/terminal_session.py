"""Persistent Terminal Session Manager — PTY-backed shell sessions.

Provides managed terminal sessions that persist across agent interactions.
Each session maintains its own shell process with working directory, env vars,
and scrollback history. ANSI codes are stripped for agent context but preserved
for the UI terminal viewer.

Architecture:
    - Each session is a subprocess shell (bash/zsh) with asyncio reader
    - Output captured to ring buffer (raw + stripped)
    - Events emitted to LocalEventBus for conductor/UI coordination
    - Integrates with tmux for visible layout alongside programmatic control

Usage:
    from core.terminal_session import terminal_session_manager

    # In app.py lifespan:
    terminal_session_manager.init(event_bus, ws_manager)

    # Create a session:
    session = await terminal_session_manager.create("builder-shell", cwd="/path/to/project")

    # Execute a command:
    output = await terminal_session_manager.execute(session.id, "npm run build")

    # Read recent output:
    lines = terminal_session_manager.read_output(session.id, last_n=50)

    # In app.py teardown:
    await terminal_session_manager.shutdown()
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("nexus.terminal_sessions")

# ANSI escape code pattern for stripping from agent context
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\[.*?[@-~]")

_MAX_SESSIONS = 10
_DEFAULT_SHELL = os.environ.get("SHELL", "/bin/bash")
_OUTPUT_BUFFER_SIZE = 1000  # lines
_COMMAND_TIMEOUT = 60  # seconds
_WS_THROTTLE_MS = 150


@dataclass
class TerminalSession:
    """A persistent shell session."""

    id: str
    name: str
    cwd: str
    status: str  # "running", "idle", "closed"
    shell: str = _DEFAULT_SHELL
    process: Optional[Any] = None  # asyncio.subprocess.Process
    reader_task: Optional[asyncio.Task] = None
    # Raw output with ANSI codes (for UI terminal viewer)
    raw_buffer: deque = field(default_factory=lambda: deque(maxlen=_OUTPUT_BUFFER_SIZE))
    # Stripped output (for agent context)
    clean_buffer: deque = field(default_factory=lambda: deque(maxlen=_OUTPUT_BUFFER_SIZE))
    # Command tracking
    last_command: str = ""
    last_exit_code: Optional[int] = None
    command_count: int = 0
    # Conductor association
    conductor_id: str = ""
    agent_id: str = ""  # Which agent owns this session
    # Timing
    created_at: float = field(default_factory=time.time)
    _last_ws_emit: float = 0.0
    # Command completion tracking
    _pending_commands: dict = field(default_factory=dict)  # marker -> Future

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "cwd": self.cwd,
            "status": self.status,
            "shell": self.shell,
            "last_command": self.last_command,
            "last_exit_code": self.last_exit_code,
            "command_count": self.command_count,
            "conductor_id": self.conductor_id,
            "agent_id": self.agent_id,
            "output_lines": len(self.clean_buffer),
            "created_at": self.created_at,
        }


class TerminalSessionManager:
    """Singleton managing persistent shell sessions."""

    def __init__(self):
        self._sessions: dict[str, TerminalSession] = {}
        self._event_bus: Any = None
        self._ws_manager: Any = None
        self._initialized = False

    def init(self, event_bus: Any = None, ws_manager: Any = None) -> None:
        """Initialize the session manager. Call once at startup."""
        self._event_bus = event_bus
        self._ws_manager = ws_manager
        self._initialized = True
        logger.info("Terminal session manager initialized")

    # ── Session Lifecycle ────────────────────────────────────────

    async def create(
        self,
        name: str,
        cwd: str = ".",
        shell: str = _DEFAULT_SHELL,
        conductor_id: str = "",
        agent_id: str = "",
        env: Optional[dict] = None,
    ) -> TerminalSession:
        """Create and start a new persistent shell session.

        Args:
            name: Human-readable name (e.g., "builder-shell", "test-runner")
            cwd: Working directory for the shell
            shell: Shell binary (default: user's $SHELL)
            conductor_id: Conductor run this session belongs to
            agent_id: Agent that owns this session
            env: Extra environment variables to inject

        Returns:
            The created TerminalSession
        """
        if len(self._sessions) >= _MAX_SESSIONS:
            raise RuntimeError(f"Maximum {_MAX_SESSIONS} terminal sessions reached")

        session_id = f"term-{uuid.uuid4().hex[:8]}"
        cwd = os.path.expanduser(cwd)
        if not os.path.isdir(cwd):
            cwd = os.path.expanduser("~")

        session = TerminalSession(
            id=session_id,
            name=name,
            cwd=cwd,
            status="running",
            shell=shell,
            conductor_id=conductor_id,
            agent_id=agent_id,
        )

        # Build environment
        session_env = {**os.environ}
        if env:
            session_env.update(env)
        # Mark as Nexus-managed session
        session_env["NEXUS_SESSION_ID"] = session_id
        session_env["NEXUS_SESSION_NAME"] = name

        try:
            # Spawn interactive shell subprocess
            process = await asyncio.create_subprocess_exec(
                shell, "-i",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
                cwd=cwd,
                env=session_env,
            )
            session.process = process

            # Start output reader
            session.reader_task = asyncio.create_task(
                self._output_reader(session),
                name=f"term-reader-{session_id}",
            )

            self._sessions[session_id] = session

            # Emit event
            await self._emit_event("agent_spawned", {
                "conductor_id": conductor_id,
                "agent_id": agent_id,
                "session_name": name,
            })

            logger.info(
                "Terminal session %s (%s) started in %s (pid=%d)",
                session_id, name, cwd, process.pid,
            )
            return session

        except Exception as e:
            session.status = "closed"
            logger.error("Failed to create terminal session %s: %s", session_id, e)
            raise

    async def execute(
        self,
        session_id: str,
        command: str,
        timeout: int = _COMMAND_TIMEOUT,
        agent_id: str = "",
    ) -> str:
        """Execute a command in a session and return the output.

        Uses a unique marker to detect command completion. Returns the
        clean (ANSI-stripped) output between the command and the marker.

        Args:
            session_id: Session to execute in
            command: Shell command to run
            timeout: Max seconds to wait for completion
            agent_id: Which agent issued the command (for audit)

        Returns:
            Clean command output as a string
        """
        session = self._sessions.get(session_id)
        if not session or session.status != "running" or not session.process:
            raise RuntimeError(f"Session {session_id} not available")

        if not session.process.stdin or session.process.stdin.is_closing():
            raise RuntimeError(f"Session {session_id} stdin is closed")

        # Create a unique completion marker
        marker = f"__NEXUS_CMD_DONE_{uuid.uuid4().hex[:8]}__"
        done_future: asyncio.Future = asyncio.get_event_loop().create_future()
        session._pending_commands[marker] = done_future

        # Track the command
        session.last_command = command
        session.command_count += 1

        # Emit terminal_command event
        await self._emit_event("terminal_command", {
            "conductor_id": session.conductor_id,
            "session_name": session.name,
            "command": command,
            "agent_id": agent_id or session.agent_id,
        })

        # Record position in clean buffer before command
        pre_len = len(session.clean_buffer)

        try:
            # Send the command followed by the marker echo
            # The marker echo captures the exit code too
            full_cmd = f"{command}; echo \"{marker} $?\"\n"
            session.process.stdin.write(full_cmd.encode())
            await session.process.stdin.drain()

            # Wait for the marker to appear in output
            await asyncio.wait_for(done_future, timeout=timeout)

            # Extract exit code from marker line
            exit_code = session._pending_commands.pop(marker, None)
            if isinstance(exit_code, int):
                session.last_exit_code = exit_code

            # Collect output lines between pre_len and now, excluding marker
            output_lines = []
            all_lines = list(session.clean_buffer)
            for line in all_lines[pre_len:]:
                if marker in line:
                    continue
                output_lines.append(line)

            output = "\n".join(output_lines).strip()

            # Emit terminal_output event
            await self._emit_event("terminal_output", {
                "conductor_id": session.conductor_id,
                "session_name": session.name,
                "output": output[:2000],  # Truncate for events
                "exit_code": session.last_exit_code,
            })

            return output

        except asyncio.TimeoutError:
            session._pending_commands.pop(marker, None)
            logger.warning(
                "Command timed out in session %s after %ds: %s",
                session_id, timeout, command[:100],
            )
            # Return whatever output we got
            all_lines = list(session.clean_buffer)
            partial = "\n".join(all_lines[pre_len:]).strip()
            return f"{partial}\n\n[TIMEOUT after {timeout}s]"

    async def send_raw(self, session_id: str, text: str) -> bool:
        """Send raw text to a session's stdin (no marker tracking).

        Useful for interactive commands, Ctrl-C (\\x03), etc.
        """
        session = self._sessions.get(session_id)
        if not session or session.status != "running" or not session.process:
            return False

        if not session.process.stdin or session.process.stdin.is_closing():
            return False

        try:
            session.process.stdin.write(text.encode())
            await session.process.stdin.drain()
            return True
        except Exception as e:
            logger.warning("Failed to send to session %s: %s", session_id, e)
            return False

    def read_output(
        self,
        session_id: str,
        last_n: int = 50,
        raw: bool = False,
    ) -> str:
        """Read recent output from a session.

        Args:
            session_id: Session to read from
            last_n: Number of recent lines
            raw: If True, return raw output with ANSI codes (for UI viewer)

        Returns:
            Output text
        """
        session = self._sessions.get(session_id)
        if not session:
            return ""
        buffer = session.raw_buffer if raw else session.clean_buffer
        lines = list(buffer)[-last_n:]
        return "\n".join(lines)

    async def close(self, session_id: str) -> bool:
        """Close a terminal session."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        logger.info("Closing terminal session %s (%s)", session_id, session.name)

        if session.process and session.process.returncode is None:
            try:
                # Send exit command first
                if session.process.stdin and not session.process.stdin.is_closing():
                    session.process.stdin.write(b"exit\n")
                    await session.process.stdin.drain()
                    try:
                        await asyncio.wait_for(session.process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        session.process.terminate()
                        try:
                            await asyncio.wait_for(session.process.wait(), timeout=5)
                        except asyncio.TimeoutError:
                            session.process.kill()
                            await session.process.wait()
                else:
                    session.process.terminate()
                    await session.process.wait()
            except ProcessLookupError:
                pass

        # Cancel reader task
        if session.reader_task and not session.reader_task.done():
            session.reader_task.cancel()

        session.status = "closed"
        return True

    def get_session(self, session_id: str) -> Optional[TerminalSession]:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def get_by_name(self, name: str) -> Optional[TerminalSession]:
        """Get a session by name (first match)."""
        for s in self._sessions.values():
            if s.name == name and s.status == "running":
                return s
        return None

    def get_by_conductor(self, conductor_id: str) -> list[TerminalSession]:
        """Get all sessions belonging to a conductor run."""
        return [
            s for s in self._sessions.values()
            if s.conductor_id == conductor_id
        ]

    def list_sessions(self) -> list[dict]:
        """List all sessions."""
        return [s.to_dict() for s in self._sessions.values()]

    async def close_by_conductor(self, conductor_id: str) -> int:
        """Close all sessions belonging to a conductor run."""
        sessions = self.get_by_conductor(conductor_id)
        count = 0
        for session in sessions:
            if await self.close(session.id):
                count += 1
        return count

    async def shutdown(self) -> None:
        """Close all sessions. Called during app teardown."""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            try:
                await self.close(sid)
            except Exception as e:
                logger.warning("Error closing session %s during shutdown: %s", sid, e)
        logger.info("Terminal session manager shut down (%d sessions)", len(session_ids))

    # ── Internal ─────────────────────────────────────────────────

    async def _output_reader(self, session: TerminalSession) -> None:
        """Background task that reads subprocess stdout."""
        try:
            async for line in session.process.stdout:
                line_str = line.decode(errors="replace").rstrip("\n\r")

                # Store raw (with ANSI codes)
                session.raw_buffer.append(line_str)

                # Store clean (ANSI stripped)
                clean_line = _ANSI_PATTERN.sub("", line_str)
                session.clean_buffer.append(clean_line)

                # Check for completion markers
                for marker, future in list(session._pending_commands.items()):
                    if marker in clean_line:
                        # Extract exit code from marker line
                        # Format: __NEXUS_CMD_DONE_abc12345__ 0
                        parts = clean_line.split(marker)
                        exit_code = 0
                        if len(parts) > 1:
                            code_str = parts[1].strip()
                            try:
                                exit_code = int(code_str)
                            except (ValueError, IndexError):
                                pass
                        session.last_exit_code = exit_code
                        session._pending_commands[marker] = exit_code
                        if not future.done():
                            future.set_result(exit_code)
                        break

                # Emit to WebSocket (throttled)
                await self._throttled_ws_emit(session, clean_line)

        except asyncio.CancelledError:
            logger.debug("Reader cancelled for session %s", session.id)
        except Exception as e:
            logger.error("Reader error for session %s: %s", session.id, e)
        finally:
            if session.status == "running":
                session.status = "idle"

    async def _throttled_ws_emit(self, session: TerminalSession, line: str) -> None:
        """Emit terminal output to WebSocket, throttled."""
        if not self._ws_manager:
            return

        now = time.time() * 1000
        if now - session._last_ws_emit < _WS_THROTTLE_MS:
            return

        session._last_ws_emit = now
        try:
            await self._ws_manager.broadcast({
                "type": "terminal_output",
                "session_id": session.id,
                "session_name": session.name,
                "content": line,
                "conductor_id": session.conductor_id,
            })
        except Exception:
            pass

    async def _emit_event(self, event_type: str, data: dict) -> None:
        """Emit a typed event to the local event bus."""
        if not self._event_bus:
            return

        try:
            from core.event_bus import (
                TerminalCommandEvent,
                TerminalOutputEvent,
                AgentSpawnedEvent,
            )

            if event_type == "terminal_command":
                await self._event_bus.publish(TerminalCommandEvent(
                    conductor_id=data.get("conductor_id", ""),
                    session_name=data.get("session_name", ""),
                    command=data.get("command", ""),
                    agent_id=data.get("agent_id", ""),
                ))
            elif event_type == "terminal_output":
                await self._event_bus.publish(TerminalOutputEvent(
                    conductor_id=data.get("conductor_id", ""),
                    session_name=data.get("session_name", ""),
                    output=data.get("output", ""),
                    exit_code=data.get("exit_code"),
                ))
            elif event_type == "agent_spawned":
                await self._event_bus.publish(AgentSpawnedEvent(
                    conductor_id=data.get("conductor_id", ""),
                    agent_id=data.get("agent_id", ""),
                    role="terminal",
                    prompt_preview=f"Terminal session: {data.get('session_name', '')}",
                ))
        except Exception as e:
            logger.debug("Event emission failed: %s", e)


# ── Global singleton ────────────────────────────────────────────
terminal_session_manager = TerminalSessionManager()
