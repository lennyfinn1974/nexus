"""Core message processing logic — slash commands and non-WebSocket chat."""

from __future__ import annotations

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
SKILL_ACTION_PATTERN = re.compile(
    r'<skill_action>(\w+)\((.*?)\)</skill_action>', re.DOTALL
)


async def process_skill_actions(ai_response: str, skills_engine: Any) -> list[dict]:
    """Extract and execute skill action calls from AI response text."""
    matches = SKILL_ACTION_PATTERN.findall(ai_response)
    if not matches:
        return []

    results = []
    for action_name, params_str in matches:
        params: dict[str, str] = {}
        for part in re.split(r',\s*(?=\w+=)', params_str):
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

    if text == "/tasks":
        tasks = await task_queue.list_tasks()
        if not tasks:
            return "No tasks in queue."
        emoji = {"pending": "~", "running": ">", "completed": "+", "failed": "x", "cancelled": "-"}
        lines = ["**Tasks:**\n"]
        for t in tasks:
            lines.append(f"[{emoji.get(t['status'], '?')}] `{t['id']}` -- {t['type']} ({t['status']})")
        return "\n".join(lines)

    if text.startswith("/model "):
        choice = text[7:].strip().lower()
        if choice in ("claude", "local", "ollama"):
            return f"Next responses will use **{choice}** model."
        return "Use `/model claude` or `/model local`"

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

    # Plugin commands
    if text.startswith("/"):
        cmd_parts = text[1:].split(None, 1)
        cmd_name = cmd_parts[0].lower()
        cmd_args = cmd_parts[1] if len(cmd_parts) > 1 else ""
        plugin_response = await plugin_manager.handle_command(cmd_name, cmd_args)
        if plugin_response is not None:
            return plugin_response

    # ── AI chat (non-WebSocket path: Telegram, API) ──
    tool_mode = getattr(cfg, "tool_calling_mode", "legacy") if cfg else "legacy"
    skill_context = await skills_engine.build_skill_context(text)
    system = build_system_prompt(cfg, plugin_manager, tool_calling_mode=tool_mode)
    if skill_context:
        system += f"\n\n{skill_context}"

    # Conversation tracking
    if not hasattr(process_message, '_tg_convs'):
        process_message._tg_convs = {}
    conv_id = process_message._tg_convs.get(user_id)
    if conv_id:
        conv = await db.get_conversation(conv_id)
        if not conv:
            conv_id = None
    if not conv_id:
        conv_id = f"conv-{uuid.uuid4().hex[:8]}"
        await db.create_conversation(conv_id, title=text[:50])
        process_message._tg_convs[user_id] = conv_id

    history = await db.get_conversation_messages(conv_id, limit=20)
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": text})

    result = await model_router.chat(messages, system=system, force_model=force_model)

    # Process tool calls (legacy regex mode)
    cleaned_content, tool_results = await plugin_manager.process_tool_calls(result["content"])
    if tool_results:
        tool_feedback = "\n".join(
            f"Tool {tr['tool']}: {tr.get('result', tr.get('error', 'unknown'))}"
            for tr in tool_results
        )
        messages.append({"role": "assistant", "content": result["content"]})
        messages.append({"role": "user", "content": f"[Tool results]\n{tool_feedback}\n\nPlease incorporate these results into your response."})
        final_result = await model_router.chat(messages, system=system, force_model=force_model)
        result["content"] = final_result["content"]
    elif cleaned_content != result["content"]:
        result["content"] = cleaned_content

    await db.add_message(conv_id, "user", text)
    await db.add_message(
        conv_id, "assistant", result["content"],
        model_used=result.get("model", "unknown"),
        tokens_in=result.get("tokens_in", 0),
        tokens_out=result.get("tokens_out", 0),
    )
    return result["content"]


async def get_status(
    model_router: Any,
    plugin_manager: Any,
    task_queue: Any,
    skills_engine: Any,
) -> str:
    """Return a formatted status string."""
    status = model_router.status
    pc = len(plugin_manager.plugins)
    pt = len(plugin_manager.all_tools) if hasattr(plugin_manager, 'all_tools') else 0
    return (
        f"Ollama: {'OK' if status['ollama_available'] else 'OFF'} ({status['ollama_model']})\n"
        f"Claude: {'OK' if status['claude_available'] else 'OFF'} ({status['claude_model']})\n"
        f"Plugins: {pc} loaded ({pt} tools)\n"
        f"Active tasks: {task_queue.active_count}\n"
        f"Skills learned: {len(await skills_engine.list_skills())}"
    )
