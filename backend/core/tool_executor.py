"""Structured tool calling engine with safety features.

Replaces regex-based <tool_call> parsing. Adds:
- Idempotency keys for write tools (Phase E1)
- Read/write tool classification (Phase E2)
- Execution timeouts (Phase E3)
- Multi-tool transaction logging (Phase E4)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from schemas.tools import ToolCall, ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger("nexus.tools")

# ── Tool Classification (E2) ──────────────────────────────────────
# Pattern-based side_effects classification for tools that don't
# declare it explicitly. Tools containing these substrings are writes.
_WRITE_TOOL_PATTERNS = {
    "write", "create", "delete", "store", "save", "set", "send",
    "execute", "run", "open", "close", "move", "copy", "install",
    "notify", "navigate", "type", "press", "shortcut", "index",
    "forget", "screenshot", "new_window", "new_tab", "new_session",
    "session_start", "session_stop", "session_send", "multi_agent",
}

# Explicit overrides: tool names that ARE reads despite matching write patterns
_READ_OVERRIDES = {
    "list_running_apps", "list_skills", "list_dir", "list_actions",
    "session_list", "claude_session_list", "claude_session_read",
    "terminal_list_windows", "tmux_list_sessions",
    "skill_list_actions", "skill_get_knowledge",
    "doc_list_collections",
}

# Longer timeouts for known slow tools
_LONG_TIMEOUT_TOOLS = {
    "web_fetch_rendered": 60.0,
    "terminal_execute": 60.0,
    "tmux_send": 60.0,
    "claude_session_start": 120.0,
    "claude_session_send": 120.0,
    "claude_multi_agent": 300.0,
    "run_bash": 60.0,
    "run_python": 60.0,
    "sovereign_execute": 120.0,
    "skill_catalog_install": 60.0,
    "install_skill_from_github": 60.0,
}

DEFAULT_TIMEOUT = 30.0


def _has_side_effects(tool_name: str, tool_info: Any = None) -> bool:
    """Classify whether a tool has side effects (write/mutate).

    Priority: explicit ToolInfo.side_effects > name in READ_OVERRIDES > pattern match.
    """
    # Explicit declaration on ToolInfo takes priority
    if tool_info is not None and hasattr(tool_info, "side_effects"):
        return tool_info.side_effects

    # Explicit read overrides
    if tool_name in _READ_OVERRIDES:
        return False

    # Pattern match — any write substring in name = side effects
    name_lower = tool_name.lower()
    return any(pat in name_lower for pat in _WRITE_TOOL_PATTERNS)


def _get_timeout(tool_name: str, tool_info: Any = None) -> float:
    """Get execution timeout for a tool."""
    # Explicit declaration on ToolInfo
    if tool_info is not None and hasattr(tool_info, "timeout_seconds"):
        timeout = getattr(tool_info, "timeout_seconds", DEFAULT_TIMEOUT)
        if timeout != DEFAULT_TIMEOUT:
            return timeout

    return _LONG_TIMEOUT_TOOLS.get(tool_name, DEFAULT_TIMEOUT)


def _idempotency_key(tool_name: str, params: dict, turn_id: str = "") -> str:
    """Generate an idempotency key: SHA256(tool_name + params + turn_id)[:24]."""
    payload = json.dumps({"t": tool_name, "p": params, "tid": turn_id}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


# ── Transaction Logging (E4) ──────────────────────────────────────

class ToolTransaction:
    """Record a sequence of tool calls within a single turn for audit.

    Usage:
        async with tool_executor.transaction("turn-abc") as txn:
            r1 = await tool_executor.execute(tc1)
            txn.record(tc1, r1)
            r2 = await tool_executor.execute(tc2)
            txn.record(tc2, r2)
        # txn auto-logs summary on exit
    """

    def __init__(self, turn_id: str = ""):
        self.turn_id = turn_id
        self.steps: list[dict] = []
        self._start = time.time()

    def record(self, tool_call: ToolCall, result: ToolResult) -> None:
        """Record one step in the transaction."""
        self.steps.append({
            "tool": f"{tool_call.plugin}:{tool_call.name}",
            "params_preview": json.dumps(tool_call.parameters, default=str)[:200],
            "success": result.success,
            "error": result.error,
            "result_len": len(result.result or ""),
            "ts": time.time(),
        })

    def summary(self) -> dict:
        """Return transaction summary."""
        total_ms = int((time.time() - self._start) * 1000)
        successes = sum(1 for s in self.steps if s["success"])
        failures = sum(1 for s in self.steps if not s["success"])
        return {
            "turn_id": self.turn_id,
            "total_steps": len(self.steps),
            "successes": successes,
            "failures": failures,
            "total_ms": total_ms,
            "steps": self.steps,
        }


# ── Idempotency Cache (E1) ────────────────────────────────────────

class _IdempotencyCache:
    """In-memory idempotency cache with TTL (1 hour).

    Falls back to in-memory dict when Redis is unavailable.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, float]] = {}  # key → (result_json, expires_at)
        self._ttl = 3600.0  # 1 hour

    def get(self, key: str) -> str | None:
        """Get cached result if exists and not expired."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        result_json, expires_at = entry
        if time.time() > expires_at:
            del self._cache[key]
            return None
        return result_json

    def set(self, key: str, result: ToolResult) -> None:
        """Cache a result."""
        result_json = json.dumps({
            "tool_call_id": result.tool_call_id,
            "name": result.name,
            "result": result.result,
            "error": result.error,
            "success": result.success,
        })
        self._cache[key] = (result_json, time.time() + self._ttl)

    def cleanup(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.time()
        expired = [k for k, (_, exp) in self._cache.items() if now > exp]
        for k in expired:
            del self._cache[k]
        return len(expired)


# Global cache instance
_idempotency_cache = _IdempotencyCache()


# ── Main Executor ──────────────────────────────────────────────────

class ToolExecutor:
    """Unified tool calling engine for both plugin tools and skill actions."""

    def __init__(self, plugin_manager: Any, skills_engine: Any):
        self.plugin_manager = plugin_manager
        self.skills_engine = skills_engine

    def get_tool_definitions(self) -> list[ToolDefinition]:
        """Collect all tool definitions from plugins + skill actions."""
        definitions: list[ToolDefinition] = []

        # Plugin tools
        for plugin_name, plugin in self.plugin_manager.plugins.items():
            for tool in plugin.tools:
                params = []
                for pname, pdesc in tool.parameters.items():
                    params.append(
                        ToolParameter(
                            name=pname,
                            type="string",
                            description=str(pdesc),
                            required=True,
                        )
                    )
                definitions.append(
                    ToolDefinition(
                        name=tool.name,
                        plugin=plugin_name,
                        description=tool.description,
                        parameters=params,
                        category=getattr(tool, "category", "general"),
                    )
                )

        # Skill actions — assign category based on skill domain
        _DOMAIN_TO_CATEGORY = {
            # Web / search
            "search": "web",
            "web": "web",
            "browser": "web",
            "research": "web",
            "utilities": "web",  # weather, etc.
            # System / macOS / productivity
            "system": "system",
            "macos": "system",
            "productivity": "system",  # calendar, reminders, notes, things
            "communication": "system",
            "ai": "system",  # ollama manager
            # Files
            "files": "files",
            # Code / development
            "code": "code",
            "development": "code",
            # Memory
            "memory": "memory",
            # Knowledge / docs
            "knowledge": "knowledge",
            "docs": "knowledge",
            # Workspace
            "workspace": "workspace",
            "project": "workspace",
            # Fallback
            "general": "general",
            "uncategorized": "general",
        }
        for skill in self.skills_engine.skills.values():
            if not skill.is_configured(self.skills_engine.config) if self.skills_engine.config else False:
                continue
            skill_category = _DOMAIN_TO_CATEGORY.get(skill.domain, "general")
            for action in skill.actions:
                params = []
                for pname, pdesc in action.parameters.items():
                    params.append(
                        ToolParameter(
                            name=pname,
                            type="string",
                            description=str(pdesc),
                            required=True,
                        )
                    )
                definitions.append(
                    ToolDefinition(
                        name=action.name,
                        plugin=f"skill_{skill.id}",
                        description=action.description,
                        parameters=params,
                        category=skill_category,
                    )
                )

        return definitions

    def to_anthropic_tools(self) -> list[dict]:
        """Convert all tool definitions to Anthropic API format."""
        return [d.to_anthropic_format() for d in self.get_tool_definitions()]

    def to_ollama_tools(
        self,
        message: str | None = None,
        boost_skill_ids: list[str] | None = None,
    ) -> list[dict]:
        """Convert tool definitions to Ollama/OpenAI format.

        When *message* is provided, uses intelligent filtering to return
        only the 10-15 most relevant tools (for Ollama).
        Without *message*, returns all tools (Claude compatibility).

        *boost_skill_ids* forces inclusion of tool definitions from those
        skills even if ToolSelector would otherwise filter them out.
        This ensures @skill-name invocations always have their actions available.
        """
        all_defs = self.get_tool_definitions()

        if message:
            from core.tool_selector import ToolSelector

            selector = ToolSelector(all_defs)
            defs = selector.select_tools(message, max_tools=15)

            # Boost: ensure @skill actions are included
            if boost_skill_ids:
                selected_names = {d.name for d in defs}
                for defn in all_defs:
                    if defn.name not in selected_names:
                        # Check if this definition belongs to a boosted skill
                        for sid in boost_skill_ids:
                            if defn.plugin == f"skill_{sid}":
                                defs.append(defn)
                                selected_names.add(defn.name)
                                logger.info(
                                    f"Boosted @skill action into tool set: {defn.name}"
                                )
                                break
        else:
            defs = all_defs
        return [d.to_ollama_format() for d in defs]

    # ── Core Execution (E1 idempotency + E3 timeout) ──────────────

    async def execute(self, tool_call: ToolCall, turn_id: str = "") -> ToolResult:
        """Execute a single tool call with idempotency, timeout, and security checks."""
        tool_name = tool_call.name

        # Skill actions
        if tool_call.plugin.startswith("skill_"):
            return await self._execute_with_timeout(
                self._execute_skill, tool_call,
                timeout=_get_timeout(tool_name),
            )

        # Plugin tools
        plugin = self.plugin_manager.plugins.get(tool_call.plugin)
        if not plugin:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_name,
                error=f"Plugin '{tool_call.plugin}' not found",
                success=False,
            )

        # Security hook
        allowed = await self.plugin_manager.validate_tool_call(plugin, tool_name, tool_call.parameters)
        if not allowed:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_name,
                error="Tool call blocked by security policy",
                success=False,
            )

        # Find tool info
        tool_info = next((t for t in plugin.tools if t.name == tool_name), None)
        if not tool_info or not tool_info.handler:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_name,
                error=f"Tool '{tool_name}' has no handler",
                success=False,
            )

        # E1: Idempotency check for write tools
        is_write = _has_side_effects(tool_name, tool_info)
        if is_write and turn_id:
            idem_key = _idempotency_key(tool_name, tool_call.parameters, turn_id)
            cached = _idempotency_cache.get(idem_key)
            if cached is not None:
                data = json.loads(cached)
                logger.info(f"Idempotency cache hit: {tool_name} key={idem_key[:12]}")
                from core.metrics import get_metrics
                get_metrics().record_count("idempotency_hits")
                return ToolResult(**data)
        else:
            idem_key = None

        # E3: Execute with timeout
        result = await self._execute_with_timeout(
            self._execute_plugin, tool_call, plugin, tool_info,
            timeout=_get_timeout(tool_name, tool_info),
        )

        # E1: Cache result for write tools
        if idem_key and result.success:
            _idempotency_cache.set(idem_key, result)

        return result

    async def _execute_skill(self, tool_call: ToolCall) -> ToolResult:
        """Execute a skill action."""
        try:
            result = await self.skills_engine.execute_action(tool_call.name, tool_call.parameters)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=result,
                success=True,
            )
        except Exception as e:
            logger.error(f"Skill action {tool_call.name} failed: {e}")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error=str(e),
                success=False,
            )

    async def _execute_plugin(self, tool_call: ToolCall, plugin: Any, tool_info: Any) -> ToolResult:
        """Execute a plugin tool handler."""
        try:
            result = await tool_info.handler(tool_call.parameters)
            await self.plugin_manager.audit_tool_call(plugin, tool_call.name, tool_call.parameters, result)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=str(result),
                success=True,
            )
        except Exception as e:
            logger.error(f"Tool {tool_call.name} failed: {e}")
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                error=str(e),
                success=False,
            )

    async def _execute_with_timeout(
        self, handler, *args, timeout: float = DEFAULT_TIMEOUT
    ) -> ToolResult:
        """Wrap tool execution with asyncio timeout (E3)."""
        try:
            return await asyncio.wait_for(handler(*args), timeout=timeout)
        except asyncio.TimeoutError:
            # Extract tool_call from args
            tool_call = args[0] if args else None
            tool_name = tool_call.name if tool_call else "unknown"
            logger.warning(f"Tool {tool_name} timed out after {timeout}s")
            return ToolResult(
                tool_call_id=tool_call.id if tool_call else "",
                name=tool_name,
                error=f"Tool execution timed out after {timeout:.0f}s",
                success=False,
            )

    # ── Transaction Context Manager (E4) ──────────────────────────

    @asynccontextmanager
    async def transaction(self, turn_id: str = ""):
        """Context manager for tracking multi-tool transactions."""
        txn = ToolTransaction(turn_id=turn_id)
        try:
            yield txn
        finally:
            summary = txn.summary()
            if summary["total_steps"] > 0:
                logger.info(
                    f"tool_transaction turn={turn_id} "
                    f"steps={summary['total_steps']} "
                    f"ok={summary['successes']} "
                    f"fail={summary['failures']} "
                    f"total_ms={summary['total_ms']}"
                )

    # ── Batch Execution ───────────────────────────────────────────

    async def execute_batch(self, tool_calls: list[ToolCall], turn_id: str = "") -> list[ToolResult]:
        """Execute multiple tool calls sequentially with transaction logging."""
        async with self.transaction(turn_id) as txn:
            results = []
            for tc in tool_calls:
                result = await self.execute(tc, turn_id=turn_id)
                txn.record(tc, result)
                results.append(result)
            return results

    # ── Classification Query ──────────────────────────────────────

    def is_write_tool(self, tool_name: str) -> bool:
        """Check if a tool has side effects (useful for retry decisions)."""
        # Check ToolInfo first
        for plugin in self.plugin_manager.plugins.values():
            for tool in plugin.tools:
                if tool.name == tool_name:
                    return _has_side_effects(tool_name, tool)
        return _has_side_effects(tool_name)

    # ── Parsing ───────────────────────────────────────────────────

    @staticmethod
    def parse_anthropic_tool_call(block: dict) -> ToolCall:
        """Parse an Anthropic API tool_use content block into a ToolCall."""
        full_name = block.get("name", "")
        # Format: plugin__tool_name
        if "__" in full_name:
            plugin, name = full_name.split("__", 1)
        else:
            plugin = "unknown"
            name = full_name

        return ToolCall(
            id=block.get("id", ""),
            name=name,
            plugin=plugin,
            parameters=block.get("input", {}),
        )

    @staticmethod
    def parse_ollama_tool_call(tool_call: dict) -> ToolCall:
        """Parse an Ollama/OpenAI tool call into a ToolCall."""
        func = tool_call.get("function", {})
        full_name = func.get("name", "")
        if "__" in full_name:
            plugin, name = full_name.split("__", 1)
        else:
            plugin = "unknown"
            name = full_name

        args = func.get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}

        return ToolCall(
            id=tool_call.get("id", ""),
            name=name,
            plugin=plugin,
            parameters=args,
        )

    def format_results_for_anthropic(self, results: list[ToolResult]) -> list[dict]:
        """Format tool results as Anthropic tool_result content blocks."""
        blocks = []
        for r in results:
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": r.tool_call_id,
                    "content": r.result if r.success else f"Error: {r.error}",
                }
            )
        return blocks

    def format_results_for_ollama(self, results: list[ToolResult]) -> list[dict]:
        """Format tool results as Ollama/OpenAI tool messages."""
        messages = []
        for r in results:
            messages.append(
                {
                    "role": "tool",
                    "content": r.result if r.success else f"Error: {r.error}",
                    "tool_call_id": r.tool_call_id,
                }
            )
        return messages
