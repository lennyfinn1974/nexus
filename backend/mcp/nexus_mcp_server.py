#!/usr/bin/env python3
"""Nexus MCP Server — Exposes Nexus tools to Claude Code via stdio.

This is a standalone MCP (Model Context Protocol) server that communicates
over stdio using JSON-RPC 2.0.  Claude Code connects to it via the
``--mcp-config`` flag and gains access to all Nexus plugin tools and
skill actions.

Protocol: MCP over stdio (JSON-RPC 2.0, newline-delimited)
Python: 3.9+ compatible (no ``mcp`` SDK required)

Usage:
    python3 nexus_mcp_server.py [--nexus-url http://localhost:8080]

Claude Code MCP config:
    {
      "mcpServers": {
        "nexus": {
          "command": "python3",
          "args": ["/path/to/nexus_mcp_server.py"],
          "env": {"NEXUS_URL": "http://localhost:8080"}
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

# HTTP client for calling back to Nexus API
try:
    import httpx
except ImportError:
    # Fallback for environments without httpx
    import urllib.request
    import urllib.error
    httpx = None

# ── Logging (to stderr so it doesn't interfere with stdio protocol) ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [nexus-mcp] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("nexus.mcp.server")

# ── Configuration ──
NEXUS_URL = os.environ.get("NEXUS_URL", "http://localhost:8080")
MCP_SERVER_NAME = "nexus"
MCP_SERVER_VERSION = "1.0.0"


class NexusMCPServer:
    """MCP server that bridges Claude Code ↔ Nexus tools."""

    def __init__(self, nexus_url: str = NEXUS_URL):
        self.nexus_url = nexus_url.rstrip("/")
        self._tools_cache: list[dict] | None = None
        self._client: Any = None

    async def _get_client(self):
        if self._client is None:
            if httpx:
                self._client = httpx.AsyncClient(
                    base_url=self.nexus_url,
                    timeout=120.0,
                )
        return self._client

    # ── Tool Discovery ──────────────────────────────────────────

    async def _fetch_tools(self) -> list[dict]:
        """Fetch available tools from the Nexus API."""
        if self._tools_cache is not None:
            return self._tools_cache

        try:
            client = await self._get_client()
            if client:
                resp = await client.get("/api/tools")
                if resp.status_code == 200:
                    self._tools_cache = resp.json().get("tools", [])
                    logger.info(f"Loaded {len(self._tools_cache)} tools from Nexus")
                    return self._tools_cache
        except Exception as e:
            logger.warning(f"Failed to fetch tools from Nexus API: {e}")

        # Fallback: return a set of commonly-used core tools
        self._tools_cache = self._get_fallback_tools()
        return self._tools_cache

    def _get_fallback_tools(self) -> list[dict]:
        """Provide a minimal tool set when Nexus API is unreachable."""
        return [
            {
                "name": "nexus_execute",
                "description": (
                    "Execute any Nexus tool or skill action by name. "
                    "Use this when you need to call a specific Nexus capability. "
                    "Available tools include: web search, memory store/search, "
                    "file operations, terminal commands, macOS automation, "
                    "calendar, reminders, notes, and 700+ installable skills."
                ),
                "parameters": {
                    "tool_name": "The full tool name (e.g. 'brave__google_search', 'mem0__memory_store', or a skill action name)",
                    "params": "JSON string of parameters to pass to the tool",
                },
            },
            {
                "name": "nexus_search",
                "description": "Search the web using Nexus's configured search provider (Google/Brave).",
                "parameters": {
                    "query": "Search query string",
                },
            },
            {
                "name": "nexus_memory_store",
                "description": "Store information in Nexus's long-term memory (Mem0).",
                "parameters": {
                    "content": "The information to remember",
                },
            },
            {
                "name": "nexus_memory_search",
                "description": "Search Nexus's long-term memory for relevant information.",
                "parameters": {
                    "query": "What to search for in memory",
                },
            },
            {
                "name": "nexus_skill_execute",
                "description": (
                    "Execute an installed skill action. Use nexus_skill_list to see available actions first."
                ),
                "parameters": {
                    "action_name": "The skill action name (e.g. 'google_search', 'list_events')",
                    "params": "JSON string of action parameters",
                },
            },
            {
                "name": "nexus_skill_list",
                "description": "List all available skill actions across installed Nexus skills.",
                "parameters": {},
            },
        ]

    # ── Tool Execution ──────────────────────────────────────────

    async def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool by calling the Nexus API."""
        try:
            client = await self._get_client()
            if not client:
                return self._execute_tool_fallback(tool_name, arguments)

            resp = await client.post(
                "/api/mcp/execute",
                json={
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
                timeout=120.0,
            )

            if resp.status_code == 200:
                result = resp.json()
                return result.get("result", json.dumps(result))
            else:
                return f"Error: Nexus returned status {resp.status_code}: {resp.text}"

        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return f"Error executing tool '{tool_name}': {e}"

    def _execute_tool_fallback(self, tool_name: str, arguments: dict) -> str:
        """Fallback execution using urllib when httpx isn't available."""
        try:
            url = f"{self.nexus_url}/api/mcp/execute"
            data = json.dumps({"tool_name": tool_name, "arguments": arguments}).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
                return result.get("result", json.dumps(result))
        except Exception as e:
            return f"Error: {e}"

    # ── MCP Protocol Handlers ───────────────────────────────────

    async def handle_initialize(self, params: dict) -> dict:
        """Handle the initialize request from Claude Code."""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": MCP_SERVER_NAME,
                "version": MCP_SERVER_VERSION,
            },
        }

    async def handle_tools_list(self, params: dict) -> dict:
        """Handle tools/list — return available Nexus tools in MCP format."""
        raw_tools = await self._fetch_tools()
        mcp_tools = []

        for tool in raw_tools:
            # Convert Nexus tool format to MCP tool format
            properties = {}
            required = []

            params_def = tool.get("parameters", {})
            if isinstance(params_def, dict):
                for pname, pdesc in params_def.items():
                    properties[pname] = {
                        "type": "string",
                        "description": str(pdesc),
                    }
                    required.append(pname)

            mcp_tools.append({
                "name": tool.get("name", "unknown"),
                "description": tool.get("description", ""),
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            })

        return {"tools": mcp_tools}

    async def handle_tools_call(self, params: dict) -> dict:
        """Handle tools/call — execute a Nexus tool."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        logger.info(f"Executing tool: {tool_name} with args: {list(arguments.keys())}")
        result = await self._execute_tool(tool_name, arguments)

        return {
            "content": [
                {
                    "type": "text",
                    "text": str(result),
                }
            ],
        }

    async def handle_request(self, request: dict) -> dict | None:
        """Route a JSON-RPC request to the appropriate handler."""
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

        handlers = {
            "initialize": self.handle_initialize,
            "tools/list": self.handle_tools_list,
            "tools/call": self.handle_tools_call,
        }

        handler = handlers.get(method)
        if handler:
            try:
                result = await handler(params)
                if request_id is not None:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": result,
                    }
            except Exception as e:
                logger.error(f"Handler error for {method}: {e}")
                if request_id is not None:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32603,
                            "message": str(e),
                        },
                    }
        elif method == "notifications/initialized":
            # Notification — no response needed
            logger.info("MCP client initialized")
            return None
        elif method == "ping":
            if request_id is not None:
                return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        else:
            logger.warning(f"Unknown method: {method}")
            if request_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }

        return None

    # ── stdio Event Loop ────────────────────────────────────────

    async def run(self):
        """Main event loop — read JSON-RPC from stdin, write to stdout."""
        logger.info(f"Nexus MCP server starting (connecting to {self.nexus_url})")

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break  # EOF

                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    request = json.loads(line_str)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {line_str[:100]}")
                    continue

                response = await self.handle_request(request)
                if response is not None:
                    response_str = json.dumps(response)
                    sys.stdout.write(response_str + "\n")
                    sys.stdout.flush()

            except Exception as e:
                logger.error(f"Server loop error: {e}")
                continue

        logger.info("MCP server shutting down")
        if self._client:
            await self._client.aclose()


async def main():
    nexus_url = NEXUS_URL
    # Allow override via command line
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg == "--nexus-url" and i < len(sys.argv) - 1:
                nexus_url = sys.argv[i + 1]
            elif arg.startswith("--nexus-url="):
                nexus_url = arg.split("=", 1)[1]

    server = NexusMCPServer(nexus_url)
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
