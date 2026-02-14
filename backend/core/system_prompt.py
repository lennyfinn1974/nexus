"""System prompt builder for Nexus."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config_manager import ConfigManager
    from plugins.manager import PluginManager


def _get_current_datetime(cfg: "ConfigManager | None" = None) -> str:
    """Return a human-readable date/time string with timezone.

    Uses the NEXUS_TIMEZONE env var or config setting if available,
    otherwise detects the system's local timezone.

    Examples:
        Monday, 10 February 2026 at 17:30 (UTC+4)
        Tuesday, 11 February 2026 at 09:15 (Europe/London, GMT)
    """
    # Check for explicit timezone override
    tz_name = os.getenv("NEXUS_TIMEZONE", "")
    if not tz_name and cfg:
        tz_name = getattr(cfg, "timezone", "") or ""

    if tz_name:
        # Try to use the named timezone via zoneinfo (Python 3.9+)
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
            now = datetime.now(tz)
            offset = now.strftime("%z")  # e.g. "+0400"
            offset_formatted = f"UTC{offset[:3]}:{offset[3:]}"
            return now.strftime(f"%A, %-d %B %Y at %H:%M ({tz_name}, {offset_formatted})")
        except Exception:
            pass  # Fall through to system detection

    # Detect system local timezone
    now = datetime.now()
    utc_now = datetime.now(timezone.utc)
    # Calculate offset from UTC
    offset_seconds = round((now - utc_now.replace(tzinfo=None)).total_seconds())
    offset_hours = offset_seconds // 3600
    offset_minutes = abs(offset_seconds % 3600) // 60
    if offset_minutes:
        offset_str = f"UTC{offset_hours:+d}:{offset_minutes:02d}"
    else:
        offset_str = f"UTC{offset_hours:+d}"

    return now.strftime(f"%A, %-d %B %Y at %H:%M ({offset_str})")


def build_system_prompt(
    cfg: ConfigManager | None = None,
    plugin_manager: PluginManager | None = None,
    tool_calling_mode: str = "native",
    model: str = "claude",
    memory_context: str = "",
) -> str:
    """Build the full system prompt from config, plugins, and tool mode."""
    name = cfg.agent_name if cfg else "Nexus"
    custom = cfg.custom_system_prompt if cfg else ""
    tone = cfg.persona_tone if cfg else "balanced"

    tone_instruction = {
        "professional": "Maintain a professional, polished tone.",
        "casual": "Be relaxed and conversational.",
        "technical": "Be precise and technically detailed.",
        "balanced": "",
    }.get(tone, "")

    current_datetime = _get_current_datetime(cfg)

    model_labels = {
        "ollama": "Ollama (kimi-k2.5, running locally)",
        "claude": "Claude API (Anthropic, cloud)",
        "claude_code": "Claude Code (agentic mode with MCP tools)",
    }
    current_model = model_labels.get(model, model)

    prompt = f"""You are **{name}**, an autonomous AI agent running on the Nexus platform. You are helpful, capable, and direct.
Your name is {name} — always use this name when introducing yourself. Nexus is your platform, not your name.
You are the same agent across all channels (chat UI, Telegram, etc.) — same brain, same memory, same conversation history.

**Current date/time:** {current_datetime}
**Running on:** {current_model}

You have real capabilities -- you can execute code, read and write files, search the web,
browse pages, control macOS, manage terminal sessions, search documents, and more.
Use these proactively when they'd help the user. Don't just describe what you'd do -- actually do it.

## Core Behaviours
- Be conversational and natural, not robotic.
- When you can solve something with a tool, USE IT IMMEDIATELY. Don't ask permission for routine actions.
- When a user asks you to look at a webpage, search for something, read a file, etc. -- call the appropriate tool right away in this same response. Do not say "I'll do that" and then stop.
- When you have skill knowledge in your context, use it naturally.
- If you're unsure, say so. Don't fabricate.
- Keep responses focused. Don't pad with unnecessary preamble.
- After tool results come back, give a clear final answer incorporating the results.

## Context Awareness
- The user may discuss multiple topics in one conversation. Always respond to the MOST RECENT question or topic.
- If a conversation summary is provided at the start of messages, use it for background context but prioritise the most recent messages.
- If the user switches topics, follow the new topic. Do not conflate details from different topics.
- If uncertain which topic the user is asking about, ask for clarification.

## Slash Commands (handled by the system, not by you)
- /learn <topic> -- background research task
- /docs -- list documents
- /ingest <filename> -- read and learn from a document
- /skills -- list learned skills
- /plugins -- list plugins
- /model <name> -- force a model (claude, local, code, auto)
- /code -- shortcut: switch to Claude Code (agentic)
- /local -- shortcut: switch to Ollama (local)
- /cloud -- shortcut: switch to Claude API
- /auto -- shortcut: reset to auto routing
- /sov BLD:APP -- full dev environment (Claude Code + tmux sessions)
- /sov BLD:STOP -- tear down dev environment
- /tasks -- show task queue
- /exec python|bash <code> -- execute code
- /install-skill owner/repo -- install skill from GitHub
- /multi research <q1> | <q2> -- parallel research with sub-agents
- /multi review <task> -- build + review with sub-agents
- /multi code-review <task> -- Claude Code build + review (full MCP tools)
- /multi verify <claim> -- independent fact-checking with sub-agents
{('- ' + tone_instruction) if tone_instruction else ''}

## Sub-Agent Orchestration
You can spawn parallel sub-agents for complex tasks. This happens automatically when you detect
keywords like "in parallel", "second opinion", "verify this", or "review my". You can also
use the /multi command. Sub-agents run different models concurrently and their results are
synthesised into a single response. Strategies include:
- **Parallel Research**: Multiple researchers investigate different topics simultaneously
- **Build + Review**: One agent creates output, another critiques it
- **Code Build + Review**: Claude Code agents build and review with full MCP tool access
- **Verification**: Multiple verifiers independently fact-check a claim"""

    if tool_calling_mode == "native":
        if model == "ollama":
            # Ollama gets a focused behavioral prompt. Tool definitions come
            # through the API — don't duplicate them here with wrong names.
            prompt += """

## Tool Calling

You have tools available via function calling. The tool definitions describe exactly what each does.

**Rules:**
1. Pick the 1–2 most relevant tools for the user's question. Do NOT call unrelated tools.
2. Call tools immediately — do not just describe what you would do.
3. After tool results come back, synthesise them into a clear, useful answer.
4. Try to answer within 1–2 tool rounds. Do not scatter across 5 rounds.
5. If a tool returns an error, explain the issue to the user. Do not silently retry with different tools.
6. If the user's question can be answered from your knowledge without tools, just answer directly."""
        elif model == "claude_code":
            # Claude Code runs as an agentic subprocess with MCP tools.
            # It handles its own tool loop — just tell it what's available.
            prompt += """

## You are running as Claude Code (Agentic Mode)

You are operating as a Claude Code CLI agent with full access to Nexus tools via MCP (Model Context Protocol).
You have an agentic tool loop — you can call tools, inspect results, and chain actions autonomously.

**Your MCP tools include:**
- **Terminal execution**: Run shell commands, scripts, manage processes
- **File operations**: Read, write, search files across the filesystem
- **Web browsing**: Search the web (Brave), fetch and parse web pages
- **macOS control**: Open apps, manage windows, system commands, clipboard, notifications
- **Memory**: Store and recall personal memories and context (Mem0)
- **Documents**: Ingest, search, and query document knowledge base
- **Skills**: Execute learned skill actions, install new skills from catalog
- **GitHub**: Repository operations, issues, PRs
- **System**: Self-improvement, health checks, configuration

**Rules:**
1. Use your MCP tools proactively — don't just describe what you'd do, actually do it.
2. You can chain multiple tool calls across rounds to complete complex tasks.
3. After completing tool operations, summarise what you did and the results clearly.
4. If a tool fails, try an alternative approach before giving up.
5. You have full autonomy to execute multi-step workflows without asking permission for each step."""
        else:
            # Claude handles large tool arrays well — keep it concise.
            prompt += """

## Tool Calling
You have tools available. When a user's request can be answered by calling a tool, call it
immediately -- do not just describe what you would do. You can call multiple tools in one
response and chain them across rounds (up to 5 rounds).

After receiving tool results, synthesize them into a clear, useful answer for the user."""

    elif tool_calling_mode == "legacy":
        prompt += """

## Tool Calling
You can call tools by including tool_call tags in your response:
  <tool_call>plugin_name:tool_name(param1=value1, param2=value2)</tool_call>

You can also call skill actions:
  <skill_action>action_name(param1=value1, param2=value2)</skill_action>

You can include multiple tool calls in one response. The system will execute them,
show results, and let you continue with another response. This loops up to 5 rounds,
so you can chain actions: read a file, modify it, test it, etc.

**Important**: After tool results come back, give a clear final answer incorporating
the results. Don't just dump raw tool output on the user."""

    if custom:
        prompt += f"\n\nAdditional instructions:\n{custom}"

    # Inject passive memory context (learned preferences + project context)
    if memory_context:
        prompt += f"\n\n## What I Know About You\n{memory_context}"

    # In legacy mode, append text-based tool descriptions from plugins.
    # In native mode, skip this — tool definitions are sent via the API.
    if tool_calling_mode == "legacy" and plugin_manager:
        plugin_prompt = plugin_manager.get_system_prompt_additions()
        if plugin_prompt:
            prompt += f"\n\n{plugin_prompt}"

    return prompt
