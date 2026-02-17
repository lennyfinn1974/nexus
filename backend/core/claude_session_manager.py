"""Claude Code Interactive Session Manager.

Manages persistent Claude Code CLI sessions with bidirectional communication
via stdin/stdout pipes using --input-format stream-json / --output-format stream-json.

Usage:
    from core.claude_session_manager import claude_session_manager

    # In app.py lifespan:
    claude_session_manager.init(cli_path, mcp_config_path, ws_manager)

    # Create a session:
    session = await claude_session_manager.create_session(
        prompt="Build a REST API", directory="/path/to/project",
        name="api-build", ws_id="ws-abc123", conv_id="conv-xyz"
    )

    # Send follow-up:
    await claude_session_manager.send_message(session.id, "Add authentication")

    # In app.py teardown:
    await claude_session_manager.shutdown()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("nexus.claude_sessions")

_DEFAULT_CLI_PATH = "/opt/homebrew/bin/claude"
_MAX_CONCURRENT = 3
_KILL_TIMEOUT = 10  # seconds before SIGKILL
_WS_THROTTLE_MS = 100  # min ms between WebSocket emissions


@dataclass
class ClaudeSession:
    """A running Claude Code CLI session."""

    id: str
    name: str
    directory: str
    status: str  # "running", "completed", "failed"
    model: str
    process: Optional[Any] = None  # asyncio.subprocess.Process
    reader_task: Optional[Any] = None  # asyncio.Task
    output_buffer: deque = field(default_factory=lambda: deque(maxlen=500))
    full_output: str = ""
    tools_used: list = field(default_factory=list)
    cost_usd: float = 0.0
    duration_ms: int = 0
    ws_id: Optional[str] = None
    conv_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    _last_ws_emit: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "directory": self.directory,
            "status": self.status,
            "model": self.model,
            "tools_used": self.tools_used,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "output_lines": len(self.output_buffer),
            "created_at": self.created_at,
        }


class ClaudeSessionManager:
    """Singleton managing persistent Claude Code CLI sessions."""

    def __init__(self):
        self._sessions: dict[str, ClaudeSession] = {}
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._cli_path: str = _DEFAULT_CLI_PATH
        self._mcp_config_path: Optional[str] = None
        self._model: str = "sonnet"
        self._ws_manager: Any = None
        self._initialized = False

    def init(
        self,
        cli_path: str = _DEFAULT_CLI_PATH,
        mcp_config_path: Optional[str] = None,
        ws_manager: Any = None,
        model: str = "sonnet",
    ) -> None:
        """Initialize the session manager. Call once at startup."""
        self._cli_path = cli_path
        self._mcp_config_path = mcp_config_path
        self._ws_manager = ws_manager
        self._model = model
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        self._initialized = True
        logger.info(
            "Claude session manager initialized (cli=%s, mcp=%s, max=%d)",
            cli_path, mcp_config_path, _MAX_CONCURRENT,
        )

    async def create_session(
        self,
        prompt: str,
        directory: str = ".",
        name: str = "",
        ws_id: Optional[str] = None,
        conv_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ClaudeSession:
        """Create and start a new Claude Code session.

        Spawns a subprocess with bidirectional stream-json pipes,
        sends the initial prompt, and starts the output reader task.
        """
        if not self._initialized:
            raise RuntimeError("ClaudeSessionManager not initialized — call init() first")

        session_id = f"ccss-{uuid.uuid4().hex[:8]}"
        directory = os.path.expanduser(directory)
        if not os.path.isdir(directory):
            directory = os.path.expanduser("~")

        effective_model = model or self._model
        session_name = name or f"claude-{session_id[-6:]}"

        session = ClaudeSession(
            id=session_id,
            name=session_name,
            directory=directory,
            status="running",
            model=effective_model,
            ws_id=ws_id,
            conv_id=conv_id,
        )

        # Acquire semaphore (limits concurrent sessions)
        await self._semaphore.acquire()

        try:
            # Build subprocess command
            cmd = self._build_command(session_id, effective_model)

            logger.info(
                "Starting Claude session %s in %s (model=%s)",
                session_id, directory, effective_model,
            )

            # Spawn subprocess with stdin/stdout pipes
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=directory,
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
            )
            session.process = process

            # Send initial prompt via stdin (stream-json input format)
            initial_msg = {
                "type": "user_message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                },
            }
            process.stdin.write((json.dumps(initial_msg) + "\n").encode())
            await process.stdin.drain()

            # Start output reader task
            session.reader_task = asyncio.create_task(
                self._output_reader(session),
                name=f"cc-reader-{session_id}",
            )

            self._sessions[session_id] = session

            # Emit session start event
            await self._emit(session, "cc_session_start", {
                "session_id": session_id,
                "name": session_name,
                "directory": directory,
                "status": "running",
                "model": effective_model,
            })

            # Work registry (fire-and-forget)
            try:
                from core.work_registry import work_registry
                await work_registry.register(
                    session_id, "cc_session",
                    f"Claude Code: {session_name}",
                    "running",
                    conv_id=conv_id,
                    model="claude_code",
                )
            except Exception:
                pass

            logger.info("Claude session %s started (pid=%d)", session_id, process.pid)
            return session

        except Exception as e:
            self._semaphore.release()
            session.status = "failed"
            logger.error("Failed to start Claude session %s: %s", session_id, e)
            raise

    async def send_message(self, session_id: str, text: str) -> bool:
        """Send a follow-up message to a running session."""
        session = self._sessions.get(session_id)
        if not session or session.status != "running" or not session.process:
            return False

        if not session.process.stdin or session.process.stdin.is_closing():
            return False

        msg = {
            "type": "user_message",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            },
        }

        try:
            session.process.stdin.write((json.dumps(msg) + "\n").encode())
            await session.process.stdin.drain()
            logger.info("Sent follow-up to session %s (%d chars)", session_id, len(text))
            return True
        except Exception as e:
            logger.warning("Failed to send to session %s: %s", session_id, e)
            return False

    def read_output(self, session_id: str, last_n: int = 50) -> str:
        """Read recent output from a session's buffer."""
        session = self._sessions.get(session_id)
        if not session:
            return ""
        lines = list(session.output_buffer)[-last_n:]
        return "\n".join(lines)

    async def stop_session(self, session_id: str) -> bool:
        """Stop a running session. SIGTERM → timeout → SIGKILL."""
        session = self._sessions.get(session_id)
        if not session or not session.process:
            return False

        logger.info("Stopping session %s (pid=%s)", session_id, session.process.pid)

        try:
            session.process.terminate()
            try:
                await asyncio.wait_for(session.process.wait(), timeout=_KILL_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("Session %s didn't terminate, sending SIGKILL", session_id)
                session.process.kill()
                await session.process.wait()
        except ProcessLookupError:
            pass  # Already dead

        session.status = "completed" if session.status == "running" else session.status

        # Cancel reader task
        if session.reader_task and not session.reader_task.done():
            session.reader_task.cancel()

        self._semaphore.release()

        await self._emit(session, "cc_session_complete", {
            "session_id": session_id,
            "status": session.status,
            "cost_usd": session.cost_usd,
            "duration_ms": int((time.time() - session.created_at) * 1000),
        })

        # Work registry update
        try:
            from core.work_registry import work_registry
            await work_registry.update(session_id, session.status, {
                "cost_usd": session.cost_usd,
            })
        except Exception:
            pass

        return True

    def list_sessions(self) -> list[dict]:
        """List all sessions (active and recent)."""
        return [s.to_dict() for s in self._sessions.values()]

    def get_session(self, session_id: str) -> Optional[ClaudeSession]:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    async def shutdown(self) -> None:
        """Stop all sessions. Called during app teardown."""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            try:
                await self.stop_session(sid)
            except Exception as e:
                logger.warning("Error stopping session %s during shutdown: %s", sid, e)
        logger.info("Claude session manager shut down (%d sessions stopped)", len(session_ids))

    # ── Internal ─────────────────────────────────────────────────

    def _build_command(self, session_id: str, model: str) -> list[str]:
        """Build the Claude CLI subprocess command."""
        cmd = [
            self._cli_path,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--session-id", session_id,
            "--model", model,
            "--dangerously-skip-permissions",
        ]

        if self._mcp_config_path and os.path.exists(self._mcp_config_path):
            cmd.extend(["--mcp-config", self._mcp_config_path])

        return cmd

    async def _output_reader(self, session: ClaudeSession) -> None:
        """Background task that reads subprocess stdout and routes events."""
        last_text = ""

        try:
            async for line in session.process.stdout:
                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                except json.JSONDecodeError:
                    # Non-JSON output (debug messages, etc.)
                    session.output_buffer.append(line_str)
                    continue

                msg_type = data.get("type", "")

                if msg_type == "assistant":
                    # Extract text from content blocks
                    message = data.get("message", {})
                    content_blocks = message.get("content", [])

                    for block in content_blocks:
                        if not isinstance(block, dict):
                            continue

                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if text and text != last_text:
                                # Yield only the delta
                                if text.startswith(last_text):
                                    delta = text[len(last_text):]
                                else:
                                    delta = text
                                if delta:
                                    session.full_output += delta
                                    session.output_buffer.append(delta)
                                    await self._throttled_emit(
                                        session, "cc_session_output",
                                        {"session_id": session.id, "content": delta},
                                    )
                                last_text = text

                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            if tool_name not in session.tools_used:
                                session.tools_used.append(tool_name)
                            await self._emit(session, "cc_session_tool_use", {
                                "session_id": session.id,
                                "tool_name": tool_name,
                            })

                elif msg_type == "result":
                    # Final result — session complete
                    result_text = data.get("result", "")
                    if result_text and result_text != last_text:
                        delta = result_text[len(last_text):] if result_text.startswith(last_text) else result_text
                        if delta:
                            session.full_output += delta
                            session.output_buffer.append(delta)
                            await self._emit(session, "cc_session_output", {
                                "session_id": session.id,
                                "content": delta,
                            })

                    session.cost_usd = data.get("total_cost_usd", 0)
                    session.duration_ms = data.get("duration_ms", 0)
                    session.status = "completed"

                    await self._emit(session, "cc_session_complete", {
                        "session_id": session.id,
                        "status": "completed",
                        "cost_usd": session.cost_usd,
                        "duration_ms": session.duration_ms,
                    })

                    # Work registry
                    try:
                        from core.work_registry import work_registry
                        await work_registry.update(session.id, "completed", {
                            "cost_usd": session.cost_usd,
                            "duration_ms": session.duration_ms,
                        })
                    except Exception:
                        pass

                    logger.info(
                        "Session %s completed: $%.4f, %dms, %d tools",
                        session.id, session.cost_usd, session.duration_ms,
                        len(session.tools_used),
                    )

        except asyncio.CancelledError:
            logger.debug("Reader task cancelled for session %s", session.id)
        except Exception as e:
            logger.error("Reader error for session %s: %s", session.id, e)
            session.status = "failed"
            await self._emit(session, "cc_session_error", {
                "session_id": session.id,
                "content": str(e),
            })
        finally:
            # Wait for process to finish if still running
            if session.process and session.process.returncode is None:
                try:
                    await asyncio.wait_for(session.process.wait(), timeout=5)
                except (asyncio.TimeoutError, Exception):
                    pass

            if session.status == "running":
                session.status = "completed"
                session.duration_ms = int((time.time() - session.created_at) * 1000)

            self._semaphore.release()

    async def _emit(self, session: ClaudeSession, msg_type: str, data: dict) -> None:
        """Send a WebSocket message for this session."""
        if not self._ws_manager:
            return

        payload = {"type": msg_type, **data}

        if session.ws_id:
            # Send to specific client
            try:
                await self._ws_manager.send_to_client(session.ws_id, payload)
            except Exception:
                pass
        else:
            # Broadcast to all (for BLD:APP sessions)
            try:
                await self._ws_manager.broadcast(payload)
            except Exception:
                pass

    async def _throttled_emit(self, session: ClaudeSession, msg_type: str, data: dict) -> None:
        """Emit with throttle to avoid flooding WebSocket."""
        now = time.time() * 1000  # ms
        if now - session._last_ws_emit >= _WS_THROTTLE_MS:
            session._last_ws_emit = now
            await self._emit(session, msg_type, data)


# ── Global singleton ─────────────────────────────────────────────
claude_session_manager = ClaudeSessionManager()
