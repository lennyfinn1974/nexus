"""Claude Code CLI client — subprocess-based provider.

Spawns ``claude -p`` in headless mode with ``--output-format stream-json``
to get streaming responses.  When an MCP config is provided, Claude Code
gets access to Nexus's tools via the Model Context Protocol.

Key design decisions
--------------------
* Uses subprocess (not SDK) because ``claude-code-sdk`` doesn't exist on PyPI.
* The CLI is expected at ``/opt/homebrew/bin/claude`` (configurable).
* Each request is a fresh subprocess — no persistent session state.
* Streaming: we parse newline-delimited JSON from stdout line by line.
* Tool calls: Claude Code handles its own tool loop internally when MCP
  tools are configured.  We don't need to re-execute tools — the final
  ``result`` message contains the complete answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from collections.abc import AsyncGenerator
from typing import Any

logger = logging.getLogger("nexus.claude_code")

# Default path to the Claude CLI binary
_DEFAULT_CLI_PATH = "/opt/homebrew/bin/claude"

# Maximum time to wait for a response (seconds)
_DEFAULT_TIMEOUT = 300  # 5 minutes — Claude Code can do multi-step work


class ClaudeCodeClient:
    """Client that spawns Claude Code CLI as a subprocess.

    Claude Code runs its own agentic loop (with MCP tools if configured),
    so from Nexus's perspective each call is a single request → final answer.
    """

    def __init__(
        self,
        cli_path: str = _DEFAULT_CLI_PATH,
        model: str = "sonnet",
        mcp_config_path: str | None = None,
        system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ):
        self.cli_path = cli_path
        self.model = model
        self.mcp_config_path = mcp_config_path
        self.system_prompt = system_prompt
        self.allowed_tools = allowed_tools
        self.timeout = timeout

    async def is_available(self) -> bool:
        """Check if the Claude CLI is installed and responsive."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.cli_path, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            version = stdout.decode().strip() or stderr.decode().strip()
            if version:
                logger.info(f"Claude Code CLI available: {version}")
                return True
            logger.warning("Claude Code CLI returned empty output for --version")
            return False
        except FileNotFoundError:
            logger.warning(f"Claude Code CLI not found at {self.cli_path}")
            return False
        except asyncio.TimeoutError:
            logger.warning("Claude Code CLI --version timed out (15s)")
            # If the binary exists but is slow to respond, still consider it available
            import os
            if os.path.isfile(self.cli_path) and os.access(self.cli_path, os.X_OK):
                logger.info("Claude Code CLI binary exists, treating as available despite timeout")
                return True
            return False
        except Exception as e:
            logger.warning(f"Claude Code availability check failed: {e}")
            return False

    def _build_command(
        self,
        prompt: str,
        system: str | None = None,
        output_format: str = "stream-json",
        tools: list[dict] | None = None,
    ) -> list[str]:
        """Build the CLI command with all flags."""
        cmd = [
            self.cli_path,
            "-p", prompt,
            "--output-format", output_format,
            "--model", self.model,
        ]

        if output_format == "stream-json":
            cmd.append("--verbose")

        # System prompt
        effective_system = system or self.system_prompt
        if effective_system:
            cmd.extend(["--system-prompt", effective_system])

        # MCP configuration (gives Claude Code access to Nexus tools)
        if self.mcp_config_path and os.path.exists(self.mcp_config_path):
            cmd.extend(["--mcp-config", self.mcp_config_path])

        # Strip down built-in tools — we supply Nexus tools via MCP
        # Keep only essential built-in tools + MCP
        if self.allowed_tools:
            cmd.extend(["--allowedTools", ",".join(self.allowed_tools)])
        else:
            # Default: no built-in file tools, only MCP tools
            cmd.extend(["--tools", ""])

        # Skip permission checks for headless operation
        cmd.append("--dangerously-skip-permissions")

        # No session persistence for API-style calls
        cmd.append("--no-session-persistence")

        return cmd

    def _messages_to_prompt(self, messages: list[dict]) -> str:
        """Convert conversation messages to a single prompt string.

        Claude Code CLI takes a single prompt string, not a messages array.
        We flatten the conversation into a readable format.
        """
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Handle Anthropic-style content blocks
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif block.get("type") == "tool_result":
                            text_parts.append(f"[Tool Result: {block.get('content', '')}]")
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = "\n".join(text_parts)

            if role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
            elif role == "system":
                parts.append(f"[System: {content}]")
            elif role == "tool":
                parts.append(f"[Tool Result ({msg.get('tool_call_id', '')}): {content}]")

        return "\n\n".join(parts)

    async def chat(
        self,
        messages: list,
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """Send a request to Claude Code and get the complete response.

        Returns a dict matching the standard Nexus provider format.
        """
        prompt = self._messages_to_prompt(messages)
        cmd = self._build_command(prompt, system, output_format="json", tools=tools)

        logger.info(f"Claude Code: spawning subprocess ({len(prompt)} char prompt)")
        logger.debug(f"Claude Code command: {' '.join(cmd[:6])}...")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout,
            )

            if proc.returncode != 0:
                error_text = stderr.decode().strip() or "Unknown error"
                logger.error(f"Claude Code failed (exit {proc.returncode}): {error_text}")
                raise RuntimeError(f"Claude Code CLI error: {error_text}")

            # Parse JSON result
            output = stdout.decode().strip()
            if not output:
                raise RuntimeError("Claude Code returned empty output")

            data = json.loads(output)

            # The result message format:
            # {"type":"result","result":"...","total_cost_usd":...,"usage":{...}}
            result_text = data.get("result", "")
            usage = data.get("usage", {})
            model_usage = data.get("modelUsage", {})

            # Extract token counts from the first model in modelUsage
            tokens_in = usage.get("input_tokens", 0)
            tokens_out = usage.get("output_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)

            # Get the actual model used
            actual_model = "claude-code"
            if model_usage:
                actual_model = list(model_usage.keys())[0]

            return {
                "content": result_text,
                "model": actual_model,
                "tokens_in": tokens_in + cache_read,
                "tokens_out": tokens_out,
                "provider": "claude_code",
                "stop_reason": data.get("stop_reason"),
                "cost_usd": data.get("total_cost_usd", 0),
                "duration_ms": data.get("duration_ms", 0),
                "session_id": data.get("session_id", ""),
            }

        except asyncio.TimeoutError:
            raise TimeoutError(f"Claude Code timed out after {self.timeout}s")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Claude Code returned invalid JSON: {e}")

    async def chat_stream(
        self,
        messages: list,
        system: str | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[str | dict, None]:
        """Stream responses from Claude Code.

        Uses --output-format stream-json to get newline-delimited JSON.
        Yields text chunks as they arrive.

        Note: Claude Code handles its own tool loop internally. We don't
        yield tool_use dicts — instead we stream the text as it's generated
        and the final result includes all tool execution results.
        """
        prompt = self._messages_to_prompt(messages)
        cmd = self._build_command(prompt, system, output_format="stream-json", tools=tools)

        logger.info(f"Claude Code stream: spawning subprocess ({len(prompt)} char prompt)")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
            )

            last_text = ""

            async for line in proc.stdout:
                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                if msg_type == "assistant":
                    # Extract text content from assistant message
                    message = data.get("message", {})
                    content_blocks = message.get("content", [])
                    for block in content_blocks:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            # Only yield the NEW portion (incremental delta)
                            if text and text != last_text:
                                if text.startswith(last_text):
                                    delta = text[len(last_text):]
                                else:
                                    delta = text
                                if delta:
                                    yield delta
                                last_text = text

                elif msg_type == "result":
                    # Final result — yield any remaining text
                    result_text = data.get("result", "")
                    if result_text and result_text != last_text:
                        if result_text.startswith(last_text):
                            delta = result_text[len(last_text):]
                        else:
                            delta = result_text
                        if delta:
                            yield delta

                    # Log cost and performance
                    cost = data.get("total_cost_usd", 0)
                    duration = data.get("duration_ms", 0)
                    if cost or duration:
                        logger.info(
                            f"Claude Code: ${cost:.4f}, {duration}ms, "
                            f"{data.get('num_turns', 1)} turn(s)"
                        )

            # Wait for process to finish
            await asyncio.wait_for(proc.wait(), timeout=10)

            if proc.returncode != 0:
                stderr = await proc.stderr.read()
                error_text = stderr.decode().strip()
                if error_text:
                    yield f"\n\n[Claude Code error: {error_text}]"

        except asyncio.TimeoutError:
            yield "\n\n[Claude Code timed out]"
            try:
                proc.kill()
            except Exception:
                pass
        except Exception as e:
            yield f"\n\n[Claude Code error: {e}]"

    async def close(self) -> None:
        """No persistent connections to close."""
        pass
