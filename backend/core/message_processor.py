"""Core message processing logic — slash commands and non-WebSocket chat."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any

from core.security import validate_path
from core.system_prompt import build_system_prompt
from skills.ingest import scan_directory

if TYPE_CHECKING:
    from core.tool_executor import ToolExecutor

logger = logging.getLogger("nexus.processor")

# Regex for legacy skill action extraction
SKILL_ACTION_PATTERN = re.compile(r"<skill_action>(\w+)\((.*?)\)</skill_action>", re.DOTALL)

# Per-user model overrides (Telegram / API path — no session state like WebSocket)
# Maps user_id → forced model name (e.g. "ollama", "claude", None for auto)
_user_model_overrides: dict[str, str | None] = {}


async def process_skill_actions(ai_response: str, skills_engine: Any) -> list[dict]:
    """Extract and execute skill action calls from AI response text."""
    matches = SKILL_ACTION_PATTERN.findall(ai_response)
    if not matches:
        return []

    results = []
    for action_name, params_str in matches:
        params: dict[str, str] = {}
        for part in re.split(r",\s*(?=\w+=)", params_str):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.strip()] = v.strip().strip("\"'")

        result = await skills_engine.execute_action(action_name, params)
        results.append({"tool": action_name, "result": result})

    return results


async def process_message(
    user_id: str,
    text: str,
    *,
    cfg: Any,
    db: Any,
    skills_engine: Any,
    model_router: Any,
    task_queue: Any,
    plugin_manager: Any,
    tool_executor: ToolExecutor | None = None,
    force_model: str | None = None,
    skill_catalog: Any | None = None,
    conv_id: str | None = None,
    passive_memory: Any = None,
) -> str:
    """Handle a single message — slash commands or AI chat. Returns response text."""
    text = text.strip()

    # ── Slash commands ──
    if text.startswith("/learn "):
        topic = text[7:].strip()
        if topic:
            task = await task_queue.submit("research", {"topic": topic})
            return f"Research task queued: **{topic}**\nTask ID: `{task['id']}`"
        return "Please specify a topic: `/learn <topic>`"

    if text == "/docs":
        files = scan_directory(cfg.docs_dir)
        if not files:
            return f"No documents found in `{cfg.docs_dir}`\n\nPlace files there then use `/ingest <filename>` or `/ingest all`."
        lines = [f"**Documents in** `{cfg.docs_dir}`\n"]
        for f in files:
            lines.append(f"- `{f['relative_path']}` ({f['extension']}, {f['size'] / 1024:.0f}KB)")
        lines.append("\nUse `/ingest <filename>` to learn from a file, or `/ingest all`.")
        return "\n".join(lines)

    if text.startswith("/ingest"):
        arg = text[7:].strip()
        files = scan_directory(cfg.docs_dir)
        if not files:
            return f"No documents found in `{cfg.docs_dir}`."
        if arg == "all":
            queued = []
            for f in files:
                try:
                    validate_path(f["path"])
                except (ValueError, Exception):
                    continue
                task = await task_queue.submit("ingest", {"path": f["path"], "name": f["name"]})
                queued.append(f["name"])
            return f"Queued {len(queued)} documents for ingestion."
        if arg:
            match = next((f for f in files if arg.lower() in f["name"].lower()), None)
            if match:
                try:
                    validate_path(match["path"])
                except (ValueError, Exception):
                    return f"Blocked: path for '{match['name']}' is outside allowed directories."
                task = await task_queue.submit("ingest", {"path": match["path"], "name": match["name"]})
                return f"Ingesting **{match['name']}**... Task ID: `{task['id']}`"
            return f"File not found matching '{arg}'. Use `/docs` to see available files."
        return "Usage: `/ingest <filename>` or `/ingest all`"

    if text == "/skills":
        skills = await skills_engine.list_skills()
        if not skills:
            return "No skills learned yet. Use `/learn <topic>` to start."
        lines = ["**Learned Skills:**\n"]
        for s in skills:
            lines.append(f"- **{s['name']}** ({s['domain']}) -- used {s.get('usage_count', 0)} times")
        return "\n".join(lines)

    if text.startswith("/catalog"):
        return await _handle_catalog_command(text, skill_catalog, skills_engine)

    if text == "/tasks":
        tasks = await task_queue.list_tasks()
        if not tasks:
            return "No tasks in queue."
        emoji = {"pending": "~", "running": ">", "completed": "+", "failed": "x", "cancelled": "-"}
        lines = ["**Tasks:**\n"]
        for t in tasks:
            lines.append(f"[{emoji.get(t['status'], '?')}] `{t['id']}` -- {t['type']} ({t['status']})")
        return "\n".join(lines)

    # ── Quick model shortcuts (same as WebSocket path) ──
    _QUICK_MODEL_CMDS = {
        "/local": "ollama", "/kimi": "ollama",
        "/cloud": "claude", "/api": "claude",
        "/code": "claude_code", "/agent": "claude_code",
        "/auto": None,
    }
    text_cmd = text.lower().split()[0] if text else ""
    if text_cmd in _QUICK_MODEL_CMDS:
        force = _QUICK_MODEL_CMDS[text_cmd]
        _user_model_overrides[user_id] = force
        labels = {
            "ollama": "Ollama (local)", "claude": "Claude API",
            "claude_code": "Claude Code (agentic)", None: "auto (local-first)",
        }
        return f"⚡ Model → **{labels[force]}**"

    if text.startswith("/model "):
        choice = text[7:].strip().lower()
        _MODEL_ALIASES = {
            "claude": "claude", "cloud": "claude", "api": "claude",
            "local": "ollama", "ollama": "ollama", "kimi": "ollama",
            "code": "claude_code", "claude_code": "claude_code",
            "agent": "claude_code", "agentic": "claude_code",
            "auto": None,
        }
        if choice in _MODEL_ALIASES:
            force = _MODEL_ALIASES[choice]
            _user_model_overrides[user_id] = force
            labels = {
                "ollama": "Ollama (local)", "claude": "Claude API",
                "claude_code": "Claude Code (agentic)", None: "auto (local-first)",
            }
            return f"⚡ Model → **{labels[force]}**"
        return "Use `/model local`, `/model claude`, `/model code`, or `/model auto`"

    if text == "/status":
        return await get_status(model_router, plugin_manager, task_queue, skills_engine)

    if text == "/plugins":
        if not plugin_manager.plugins:
            return "No plugins loaded."
        lines = ["**Loaded Plugins:**\n"]
        for name, info in plugin_manager.status.items():
            lines.append(f"**{name}** v{info['version']} -- {info['tools']} tools, {info['commands']} commands")
        if plugin_manager.list_commands():
            lines.append("\n**Plugin Commands:**")
            for cmd in plugin_manager.list_commands():
                lines.append(f"- `{cmd['command']}` ({cmd['plugin']}) -- {cmd['description']}")
        return "\n".join(lines)

    if text == "/workstreams":
        from core.work_registry import work_registry
        items = work_registry.get_all_active()
        if not items:
            return "No active work streams."
        status_emoji = {"pending": "\u23f3", "running": "\u25b6\ufe0f", "completed": "\u2705", "failed": "\u274c", "cancelled": "\u26d4"}
        kind_emoji = {
            "agent": "\U0001f916", "sub_agent": "\U0001f500", "orchestration": "\U0001f310",
            "plan": "\U0001f4cb", "plan_step": "\u2611\ufe0f", "task": "\u2699\ufe0f", "reminder": "\U0001f514",
        }
        lines = ["**Active Work Streams:**\n"]
        counts = {"pending": 0, "running": 0}
        for item in items:
            s = item.get("status", "pending")
            if s in counts:
                counts[s] += 1
            se = status_emoji.get(s, "?")
            ke = kind_emoji.get(item.get("kind", ""), "\U0001f4e6")
            title = item.get("title", item.get("id", "?"))[:60]
            model_tag = f" `{item['model']}`" if item.get("model") else ""
            lines.append(f"{se} {ke} **{title}**{model_tag}")
        lines.append(f"\n__{counts['running']} running, {counts['pending']} pending__")
        return "\n".join(lines)

    # /multi — sub-agent orchestration (Telegram/API path)
    if text.startswith("/multi"):
        return await _handle_multi_non_ws(
            text, cfg=cfg, db=db, model_router=model_router, conv_id=conv_id,
            plugin_manager=plugin_manager, tool_executor=tool_executor,
            skills_engine=skills_engine,
        )

    # Plugin commands
    if text.startswith("/"):
        cmd_parts = text[1:].split(None, 1)
        cmd_name = cmd_parts[0].lower()
        cmd_args = cmd_parts[1] if len(cmd_parts) > 1 else ""
        plugin_response = await plugin_manager.handle_command(cmd_name, cmd_args)
        if plugin_response is not None:
            return plugin_response

    # ── AI chat (non-WebSocket path: Telegram, API) ──
    # Use native tool calling (same as WebSocket path) to avoid raw XML leaking
    from core.context_manager import build_conversation_context
    from core.message_formatter import MessageFormatter
    from core.tool_executor import ToolExecutor

    # Build tool definitions if we have plugins
    tool_executor = ToolExecutor(plugin_manager, skills_engine) if plugin_manager else None
    has_tools = bool(tool_executor and plugin_manager.all_tools)

    # Determine model and tool mode — apply per-user override from /local /cloud etc.
    effective_force = force_model or _user_model_overrides.get(user_id)
    model_name = model_router.select_model(text, effective_force)
    use_native_tools = has_tools and model_name in ("claude", "ollama", "claude_code")
    tool_mode = "native" if use_native_tools else "legacy"

    # Retrieve passive memory for system prompt
    memory_context = ""
    if passive_memory:
        try:
            memory_context = await passive_memory.get_context_for_prompt(limit=5)
        except Exception:
            pass

    skill_context = await skills_engine.build_skill_directory(text)
    system = build_system_prompt(cfg, plugin_manager, tool_calling_mode=tool_mode,
                                  model=model_name, memory_context=memory_context)
    if skill_context:
        system += f"\n\n{skill_context}"

    # Conversation tracking — use provided conv_id or create a new one
    if conv_id:
        conv = await db.get_conversation(conv_id)
        if not conv:
            conv_id = None
    if not conv_id:
        conv_id = f"conv-{uuid.uuid4().hex[:8]}"
        await db.create_conversation(conv_id, title=text[:50])

    messages = await build_conversation_context(
        db=db,
        conv_id=conv_id,
        new_user_message=text,
        model_router=model_router,
        system_prompt=system,
    )

    # ── Sub-agent orchestration check (non-WebSocket path: Telegram, API) ──
    orch_result = await _maybe_orchestrate_non_ws(
        text, messages, cfg, model_router, db, conv_id,
        plugin_manager=plugin_manager, tool_executor=tool_executor,
        skills_engine=skills_engine,
    )
    if orch_result is not None:
        await db.add_message(conv_id, "user", text)
        await db.add_message(conv_id, "assistant", orch_result, model_used="multi-agent")
        return orch_result

    # Build API tool definitions for primary and fallback models
    tools_for_api = None
    fallback_tools = None
    if use_native_tools and tool_executor:
        if model_name == "claude":
            tools_for_api = tool_executor.to_anthropic_tools()
            fallback_tools = tool_executor.to_ollama_tools(message=text)
        else:
            tools_for_api = tool_executor.to_ollama_tools(message=text)
            fallback_tools = tool_executor.to_anthropic_tools()

    result = await model_router.chat(
        messages, system=system, force_model=force_model,
        tools=tools_for_api, fallback_tools=fallback_tools,
    )
    # Lock model for tool loop — prevent re-routing mid-conversation
    # (tool results inflate complexity score, causing model switches that
    # produce format mismatches like Ollama tool messages sent to Claude)
    active_model = result.get("routed_to", model_name)

    # ── Native tool loop (up to 5 rounds) ──
    MAX_TOOL_ROUNDS = 5
    for round_num in range(MAX_TOOL_ROUNDS):
        native_tool_calls = result.get("tool_calls", [])
        if not native_tool_calls:
            break

        # Execute tools
        tool_results = []
        for tc in native_tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", tc.get("name", ""))
            tool_input = func.get("arguments", tc.get("input", {}))
            tool_id = tc.get("id", f"tg_{round_num}")

            if isinstance(tool_input, str):
                import json as _json
                try:
                    tool_input = _json.loads(tool_input)
                except Exception:
                    tool_input = {}

            try:
                parsed = tool_executor.parse_ollama_tool_call(tc) if model_name == "ollama" else \
                         tool_executor.parse_anthropic_tool_call({"id": tool_id, "name": tool_name, "input": tool_input})
                res = await tool_executor.execute(parsed)
                if res.success:
                    tool_results.append({"tool": tool_name, "result": res.result, "tool_use_id": tool_id})
                else:
                    tool_results.append({"tool": tool_name, "error": res.error, "tool_use_id": tool_id})
            except Exception as exc:
                logger.error(f"Telegram tool {tool_name} failed: {exc}")
                tool_results.append({"tool": tool_name, "error": str(exc), "tool_use_id": tool_id})

        if not tool_results:
            break

        # Build follow-up messages for next round
        response_text = result.get("content", "")
        # Convert tool_calls to the format MessageFormatter expects
        formatted_tcs = []
        for tc in native_tool_calls:
            func = tc.get("function", {})
            args = func.get("arguments", {})
            if isinstance(args, str):
                import json as _json
                try:
                    args = _json.loads(args)
                except Exception:
                    args = {}
            formatted_tcs.append({
                "id": tc.get("id", ""),
                "name": func.get("name", tc.get("name", "")),
                "input": args,
            })

        if model_name == "claude":
            followup = MessageFormatter.format_anthropic(response_text, formatted_tcs, tool_results)
        elif model_name == "ollama":
            followup = MessageFormatter.format_ollama(response_text, formatted_tcs, tool_results)
        else:
            followup = MessageFormatter.format_legacy(response_text, tool_results, round_num)

        messages.extend(followup)

        # On last round, suppress tools to force a text answer
        next_tools = tools_for_api if round_num < MAX_TOOL_ROUNDS - 2 else None
        next_fb_tools = fallback_tools if next_tools else None
        # Force same model throughout the tool loop to prevent format mismatches
        result = await model_router.chat(
            messages, system=system, force_model=active_model,
            tools=next_tools, fallback_tools=next_fb_tools,
        )

    # ── Safety net: strip any remaining <tool_call> tags from response ──
    content = result.get("content", "")
    content = re.sub(r"</?tool_call[^>]*>", "", content)
    content = re.sub(r"<tool_call>[^<]*</tool_call>", "", content)
    content = content.strip()

    # Ensure we have some content
    if not content:
        content = "I processed your request but have no additional text to share."

    await db.add_message(conv_id, "user", text)
    await db.add_message(
        conv_id,
        "assistant",
        content,
        model_used=result.get("model", "unknown"),
        tokens_in=result.get("tokens_in", 0),
        tokens_out=result.get("tokens_out", 0),
    )
    return content


async def _handle_multi_non_ws(
    text: str,
    *,
    cfg: Any,
    db: Any,
    model_router: Any,
    conv_id: str | None = None,
    plugin_manager: Any = None,
    tool_executor: Any = None,
    skills_engine: Any = None,
) -> str:
    """Handle /multi command in non-WebSocket path (Telegram, API)."""
    from core.sub_agent import OrchestrationStrategy, SubAgentOrchestrator

    arg = text[6:].strip()  # strip "/multi"
    if not arg:
        return (
            "**Sub-Agent Commands:**\n"
            "• `/multi research <q1> | <q2> | ...` — Parallel research\n"
            "• `/multi review <task>` — Build + Review\n"
            "• `/multi code-review <task>` — Claude Code build + review\n"
            "• `/multi verify <claim>` — Independent verification"
        )

    if not cfg or not cfg.get_bool("SUB_AGENT_ENABLED", True):
        return "Sub-agent system is disabled."

    parts = arg.split(None, 1)
    sub_cmd = parts[0].lower()
    payload = parts[1] if len(parts) > 1 else ""

    if not payload:
        return f"Usage: `/multi {sub_cmd} <text>`"

    # Ensure conversation
    if not conv_id:
        conv_id = f"conv-{uuid.uuid4().hex[:8]}"
        await db.create_conversation(conv_id, title=payload[:50])

    from core.context_manager import build_conversation_context

    messages = await build_conversation_context(
        db=db,
        conv_id=conv_id,
        new_user_message=payload,
        model_router=model_router,
        system_prompt="",
    )

    # Build orchestration
    if sub_cmd == "research":
        queries = [q.strip() for q in payload.split("|") if q.strip()]
        if len(queries) < 2:
            queries = [q.strip() for q in payload.split(" and ") if q.strip() and len(q.strip()) > 10]
        if len(queries) < 2:
            queries = [payload]
        orchestration = OrchestrationStrategy.parallel_research(queries, cfg)
    elif sub_cmd == "review":
        orchestration = OrchestrationStrategy.build_review(payload, cfg=cfg)
    elif sub_cmd in ("code-review", "codereview"):
        orchestration = OrchestrationStrategy.build_review_code(payload, cfg=cfg)
    elif sub_cmd == "verify":
        orchestration = OrchestrationStrategy.verify(payload, cfg=cfg)
    else:
        return f"Unknown sub-command: `{sub_cmd}`. Use: `research`, `review`, `code-review`, `verify`"

    # Build a state shim with real dependencies
    class _StateShim:
        pass

    state = _StateShim()
    state.model_router = model_router
    state.cfg = cfg
    state.db = db
    state.plugin_manager = plugin_manager
    state.tool_executor = tool_executor
    state.skills_engine = skills_engine
    state.claude_code_client = None

    parent_abort = asyncio.Event()
    orchestrator = SubAgentOrchestrator(
        state=state,
        ws_id=None,
        conv_id=conv_id,
        parent_abort=parent_abort,
        messages=messages,
        cfg=cfg,
    )

    try:
        result = await orchestrator.execute(orchestration)
        await db.add_message(conv_id, "user", text)
        await db.add_message(conv_id, "assistant", result, model_used="multi-agent")
        return result
    except Exception as exc:
        logger.error(f"Non-WS /multi command failed: {exc}")
        return f"Sub-agent orchestration failed: {exc}"


async def _maybe_orchestrate_non_ws(
    text: str,
    messages: list[dict],
    cfg: Any,
    model_router: Any,
    db: Any,
    conv_id: str,
    plugin_manager: Any = None,
    tool_executor: Any = None,
    skills_engine: Any = None,
) -> str | None:
    """Check if this Telegram/API request should use sub-agent orchestration.

    Returns the synthesised result string, or None to fall through to normal path.
    Non-streaming: sub-agents run to completion, results merged, single response returned.
    """
    # Master switch
    if not cfg or not cfg.get_bool("SUB_AGENT_ENABLED", True):
        return None

    text_lower = text.lower()

    # Simple keyword-based detection (same logic as AgentRunner._should_orchestrate)
    _BUILD_REVIEW = re.compile(
        r"\b(write|create|build|implement|code|draft)\b.*\b(then|and)\b.*\b(review|check|critique|verify)\b",
        re.IGNORECASE,
    )
    _ORCH_KEYWORDS = re.compile(
        r"\b(sub.?agents?|in parallel|second opinion|verify this|double.?check|"
        r"review my|critique|research these|compare these|fact.?check)\b",
        re.IGNORECASE,
    )

    strategy = None

    if _BUILD_REVIEW.search(text):
        strategy = "build_review"
    elif _ORCH_KEYWORDS.search(text):
        if any(kw in text_lower for kw in ["verify", "fact-check", "double-check"]):
            strategy = "verify"
        elif any(kw in text_lower for kw in ["research these", "compare these", "in parallel"]):
            strategy = "parallel_research"
        elif any(kw in text_lower for kw in ["review my", "critique", "second opinion"]):
            strategy = "build_review"
        else:
            strategy = "parallel_research"
    elif cfg.get_bool("SUB_AGENT_AUTO_ENABLED", False) and text.count("?") >= 2 and len(text) > 80:
        strategy = "parallel_research"

    if not strategy:
        return None

    # Build orchestration
    from core.sub_agent import OrchestrationStrategy, SubAgentOrchestrator

    # Need an app state object — build a shim with real dependencies
    class _StateShim:
        pass

    state = _StateShim()
    state.model_router = model_router
    state.cfg = cfg
    state.db = db
    state.plugin_manager = plugin_manager
    state.tool_executor = tool_executor
    state.skills_engine = skills_engine
    state.claude_code_client = None

    if strategy == "parallel_research":
        # Split queries
        clean = re.sub(r"^(research|compare|look up|search for)\s+(these|the following)?\s*:?\s*", "", text, flags=re.IGNORECASE)
        queries = [q.strip() for q in clean.split("|") if q.strip()]
        if len(queries) < 2:
            queries = [q.strip() for q in clean.split(" and ") if q.strip() and len(q.strip()) > 10]
        if len(queries) < 2:
            queries = [clean]
        orchestration = OrchestrationStrategy.parallel_research(queries, cfg)
    elif strategy == "build_review":
        orchestration = OrchestrationStrategy.build_review(text, cfg=cfg)
    elif strategy == "verify":
        orchestration = OrchestrationStrategy.verify(text, cfg=cfg)
    else:
        return None

    parent_abort = asyncio.Event()
    orchestrator = SubAgentOrchestrator(
        state=state,
        ws_id=None,  # No WebSocket — non-streaming mode
        conv_id=conv_id,
        parent_abort=parent_abort,
        messages=messages,
        cfg=cfg,
    )

    try:
        result = await orchestrator.execute(orchestration)
        logger.info(f"Telegram/API orchestration ({strategy}) completed for conv {conv_id}")
        return result
    except Exception as exc:
        logger.error(f"Telegram/API orchestration failed: {exc}")
        return None  # Fall through to normal path


async def _handle_catalog_command(
    text: str, skill_catalog: Any | None, skills_engine: Any,
) -> str:
    """Process /catalog subcommands."""
    if not skill_catalog or not skill_catalog.index:
        return "Skill catalog is not available. No external skill sources found."

    arg = text[8:].strip()  # Strip "/catalog"

    if not arg:
        total = len(skill_catalog.index)
        cats = skill_catalog.list_categories()
        installed = sum(1 for e in skill_catalog.index if e.get("installed"))
        lines = [
            f"**Skill Catalog** — {total} skills available ({installed} installed)\n",
            "**Commands:**",
            "- `/catalog search <query>` — Search for skills",
            "- `/catalog categories` — List skill categories",
            "- `/catalog info <skill-id>` — Show skill details",
            "- `/catalog install <skill-id>` — Install a skill",
            f"\n**Top categories:** {', '.join(c['category'] for c in cats[:5])}",
        ]
        return "\n".join(lines)

    if arg.startswith("search "):
        query = arg[7:].strip()
        if not query:
            return "Usage: `/catalog search <query>`"
        results = skill_catalog.search(query, limit=10)
        if not results:
            return f"No skills found matching '{query}'."
        lines = [f"**Found {len(results)} skill(s) matching '{query}':**\n"]
        for r in results:
            status = "installed" if r.get("installed") else "available"
            desc = r.get("description", "")[:80]
            lines.append(
                f"- **{r['id']}** [{r.get('category', 'general')}] ({status})\n"
                f"  {desc}{'...' if len(r.get('description', '')) > 80 else ''}"
            )
        lines.append("\nUse `/catalog install <skill-id>` to install a skill.")
        return "\n".join(lines)

    if arg == "categories":
        cats = skill_catalog.list_categories()
        if not cats:
            return "No categories found."
        lines = [f"**Skill Catalog Categories** ({len(skill_catalog.index)} total skills):\n"]
        for c in cats:
            lines.append(f"- **{c['category']}**: {c['count']} skills")
        lines.append("\nUse `/catalog search <query>` or filter by topic.")
        return "\n".join(lines)

    if arg.startswith("info "):
        skill_id = arg[5:].strip()
        if not skill_id:
            return "Usage: `/catalog info <skill-id>`"
        detail = skill_catalog.get_skill_detail(skill_id)
        if not detail:
            return f"Skill '{skill_id}' not found. Use `/catalog search` to find skills."
        status = "Installed" if detail.get("installed") else "Available"
        lines = [
            f"**{detail['name']}** ({status})\n",
            f"**ID:** `{detail['id']}`",
            f"**Category:** {detail.get('category', 'general')}",
            f"**Source:** {detail.get('source', 'unknown')}",
            f"**Size:** {detail.get('size_kb', 0)} KB",
        ]
        if detail.get("description"):
            lines.append(f"\n**Description:** {detail['description']}")
        if detail.get("preview"):
            preview = detail["preview"][:300]
            lines.append(f"\n**Preview:**\n{preview}{'...' if len(detail.get('preview', '')) > 300 else ''}")
        if detail.get("files"):
            lines.append(f"\n**Supporting files:** {', '.join(detail['files'])}")
        if not detail.get("installed"):
            lines.append(f"\nUse `/catalog install {detail['id']}` to install this skill.")
        return "\n".join(lines)

    if arg.startswith("install "):
        skill_id = arg[8:].strip()
        if not skill_id:
            return "Usage: `/catalog install <skill-id>`"
        entry = skill_catalog.get_by_id(skill_id)
        if not entry:
            return f"Skill '{skill_id}' not found. Use `/catalog search` to find skills."
        if entry.get("installed"):
            return f"Skill **{entry['name']}** is already installed."

        import os
        from skills.converter import convert_antigravity_skill
        from skills.engine import Skill

        try:
            dest_dir = os.path.join(skills_engine.skills_dir, skill_id)
            manifest = convert_antigravity_skill(
                source_dir=entry["source_path"],
                dest_dir=dest_dir,
                category=entry.get("category", "general"),
                skill_id=skill_id,
            )
            # Hot-load into skills engine
            skill = Skill(dest_dir, manifest)
            skills_engine._load_actions(skill)
            skills_engine.skills[skill_id] = skill

            # Persist to DB
            try:
                await skills_engine.db.save_skill(
                    skill_id,
                    manifest["name"],
                    manifest.get("description", ""),
                    manifest.get("domain", "general"),
                    os.path.join(dest_dir, "knowledge.md"),
                )
            except Exception as e:
                logger.warning(f"DB save for skill '{skill_id}' failed: {e}")

            # Refresh catalog installed status
            skill_catalog.refresh_installed()

            keywords = ", ".join(manifest.get("triggers", {}).get("keywords", [])[:8])
            return (
                f"Successfully installed skill: **{manifest['name']}**\n"
                f"- Domain: {manifest.get('domain', 'general')}\n"
                f"- Keywords: {keywords}\n\n"
                f"This skill is now active and will be used in future conversations "
                f"when relevant topics come up. You can also use `@{skill_id}` to "
                f"explicitly invoke it."
            )
        except Exception as e:
            logger.error(f"Failed to install skill '{skill_id}': {e}")
            return f"Failed to install skill '{skill_id}': {e}"

    return (
        "Unknown catalog command. Usage:\n"
        "- `/catalog` — Overview\n"
        "- `/catalog search <query>` — Search for skills\n"
        "- `/catalog categories` — List categories\n"
        "- `/catalog info <skill-id>` — Skill details\n"
        "- `/catalog install <skill-id>` — Install a skill"
    )


async def get_status(
    model_router: Any,
    plugin_manager: Any,
    task_queue: Any,
    skills_engine: Any,
) -> str:
    """Return a formatted status string."""
    status = model_router.status
    pc = len(plugin_manager.plugins)
    pt = len(plugin_manager.all_tools) if hasattr(plugin_manager, "all_tools") else 0
    return (
        f"Ollama: {'OK' if status['ollama_available'] else 'OFF'} ({status['ollama_model']})\n"
        f"Claude: {'OK' if status['claude_available'] else 'OFF'} ({status['claude_model']})\n"
        f"Plugins: {pc} loaded ({pt} tools)\n"
        f"Active tasks: {task_queue.active_count}\n"
        f"Skills learned: {len(await skills_engine.list_skills())}"
    )
