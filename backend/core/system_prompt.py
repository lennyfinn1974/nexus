"""System prompt builder for Nexus."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, TYPE_CHECKING

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


def _get_channel_context(channel: str) -> str:
    """Return channel-specific context line for the system prompt.

    When the user is on a specific channel (WhatsApp, SMS, voice, etc.),
    the agent should adapt its behavior accordingly.
    """
    if not channel:
        return ""

    hints = {
        "websocket": "",
        "telegram": "**Channel:** Telegram — use Markdown, keep under 4000 chars.",
        "whatsapp": (
            "**Channel:** WhatsApp — be concise, use *bold* for emphasis, "
            "keep under 4000 chars. You can suggest up to 3 button options."
        ),
        "sms": (
            "**Channel:** SMS — be extremely concise (under 300 chars ideally). "
            "No formatting, no links unless essential. Each message costs money."
        ),
        "voice": (
            "**Channel:** Voice call — speak naturally, 1-3 sentences max. "
            "No code, no URLs, no formatting. This will be spoken aloud."
        ),
        "instagram": "**Channel:** Instagram DM — be casual and friendly, keep concise.",
    }
    hint = hints.get(channel.lower(), "")
    return f"\n{hint}\n" if hint else ""


def _build_self_awareness(
    cfg: "ConfigManager | None" = None,
    plugin_manager: "PluginManager | None" = None,
    app_state: Any = None,
) -> str:
    """Build a dynamic self-awareness block describing Nexus's current state.

    This gives the LLM full knowledge of what's installed, active, and
    available — so it can accurately answer questions about its own
    capabilities instead of saying "I don't know what I have."

    Returns a markdown block suitable for system prompt injection.
    """
    sections: list[str] = []

    # ── Platform Identity ──
    sections.append("## Platform Self-Awareness")
    sections.append(
        "You ARE Nexus — a self-hosted AI agent platform. Below is your LIVE "
        "configuration. Use this to accurately answer questions about your own "
        "capabilities, installed features, and system status."
    )

    # ── Model Providers ──
    models_info: list[str] = []
    if cfg:
        ollama_model = cfg.get("OLLAMA_MODEL", "")
        claude_model = cfg.get("CLAUDE_MODEL", "")
        cc_enabled = cfg.get_bool("CLAUDE_CODE_ENABLED", False)
        if ollama_model:
            models_info.append(f"  - Ollama (local): **{ollama_model}** — primary, runs on device")
        if claude_model:
            models_info.append(f"  - Claude API (cloud): **{claude_model}** — cloud fallback")
        if cc_enabled:
            cc_model = cfg.get("CLAUDE_CODE_MODEL", "claude-sonnet-4-20250514")
            models_info.append(f"  - Claude Code (agentic): **{cc_model}** — MCP tools, autonomous")
    if models_info:
        sections.append("**Model Providers:**\n" + "\n".join(models_info))

    # ── Active Plugins ──
    if plugin_manager:
        active_plugins = []
        for name, plugin in plugin_manager.plugins.items():
            if plugin.enabled:
                tool_count = len(plugin.list_tools()) if hasattr(plugin, 'list_tools') else 0
                cmd_count = len(plugin.list_commands()) if hasattr(plugin, 'list_commands') else 0
                desc = getattr(plugin, 'description', '')
                summary = f"  - **{name}**: {desc}" if desc else f"  - **{name}**"
                if tool_count:
                    summary += f" ({tool_count} tools"
                    if cmd_count:
                        summary += f", {cmd_count} commands"
                    summary += ")"
                active_plugins.append(summary)
        if active_plugins:
            sections.append(
                f"**Active Plugins** ({len(active_plugins)}):\n" + "\n".join(active_plugins)
            )

    # ── Communication Channels ──
    if app_state:
        channels: list[str] = []
        channel_mgr = getattr(app_state, "channel_manager", None)
        if channel_mgr:
            for ch_name, adapter in getattr(channel_mgr, "_adapters", {}).items():
                status = "active" if getattr(adapter, "_running", False) else "registered"
                channels.append(f"  - **{ch_name}**: {status}")
        # Always have WebSocket
        channels.insert(0, "  - **WebSocket (Chat UI)**: active")
        if channels:
            sections.append("**Communication Channels:**\n" + "\n".join(channels))

    # ── Marketing System ──
    if app_state:
        marketing_enabled = cfg.get_bool("MARKETING_ENABLED", False) if cfg else False
        brand_mgr = getattr(app_state, "brand_voice_manager", None)
        content_wf = getattr(app_state, "content_workflow", None)
        campaign_mgr = getattr(app_state, "campaign_manager", None)
        if marketing_enabled and brand_mgr:
            profile_count = len(getattr(brand_mgr, "_cache", {}))
            sections.append(
                f"**Marketing System:** ACTIVE\n"
                f"  - Brand voice manager: {profile_count} profile(s) loaded\n"
                f"  - Content workflow: {'ready' if content_wf else 'unavailable'}\n"
                f"  - Campaign manager: {'ready' if campaign_mgr else 'unavailable'}\n"
                f"  - Features: brand profiles, campaigns, content workflow (draft→review→approve→schedule→publish), "
                f"calendar, cross-channel analytics, multi-touch attribution\n"
                f"  - Admin dashboard: /admin/marketing"
            )
        else:
            sections.append("**Marketing System:** disabled (enable in Settings → Marketing)")

    # ── Memory & Knowledge ──
    if app_state:
        mem_parts: list[str] = []
        if getattr(app_state, "rag_pipeline", None):
            mem_parts.append("  - RAG pipeline: active (vector search)")
        if getattr(app_state, "knowledge_graph", None):
            mem_parts.append("  - Knowledge graph: active (entity relationships)")
        if getattr(app_state, "memory_bulletin", None):
            mem_parts.append("  - Memory bulletin: active (periodic knowledge digest)")
        if getattr(app_state, "embedding_service", None):
            mem_parts.append("  - Embedding service: active")
        if mem_parts:
            sections.append("**Memory & Knowledge:**\n" + "\n".join(mem_parts))

    # ── Clustering ──
    if app_state:
        cluster_mgr = getattr(app_state, "cluster_manager", None)
        if cluster_mgr and getattr(cluster_mgr, "enabled", False):
            role = getattr(cluster_mgr, "role", "unknown")
            sections.append(f"**Clustering:** active (role: {role})")
        else:
            sections.append("**Clustering:** standalone mode")

    # ── Skills Engine ──
    if app_state:
        skills_engine = getattr(app_state, "skills_engine", None)
        if skills_engine:
            all_skills = getattr(skills_engine, "skills", {})
            actions_count = sum(
                len(getattr(s, "actions", {}))
                for s in all_skills.values()
                if hasattr(s, "actions")
            )
            sections.append(
                f"**Skills Engine:** {len(all_skills)} skills loaded, "
                f"{actions_count} action handlers"
            )

    # ── Admin Panel ──
    sections.append(
        "**Admin Panel:** /admin — full management dashboard with pages for: "
        "Dashboard, System Health, Security, Monitoring, Users, Models, Settings, "
        "Plugins, Persona, Skills, Marketing, Metrics, Cluster, Memory, "
        "Work Streams, Conversations, Logs, System"
    )

    # ── Task Queue ──
    if app_state:
        tq = getattr(app_state, "task_queue", None)
        if tq:
            active = getattr(tq, "_active_count", 0)
            sections.append(f"**Task Queue:** active ({active} running)")

    return "\n\n".join(sections)


def build_system_prompt(
    cfg: ConfigManager | None = None,
    plugin_manager: PluginManager | None = None,
    tool_calling_mode: str = "native",
    model: str = "claude",
    memory_context: str = "",
    rag_context: str = "",
    kg_context: str = "",
    bulletin_context: str = "",
    channel: str = "",
    app_state: Any = None,
) -> str:
    """Build the full system prompt from config, plugins, and tool mode.

    Architecture (Feb 2026 — "System Prompt Diet"):
        For Ollama, the system prompt is kept ULTRA-lean (< 500 chars) to
        preserve native function calling.  All context (RAG, KG, memory,
        bulletin) is returned separately via ``build_context_messages()``
        and injected as regular messages in the conversation array.  This
        keeps the system prompt under the ~2000-char cliff where qwen3-coder
        drops native tool calling and falls back to text-based XML.

        For Claude/Claude Code, context is still injected into the system
        prompt (200K context handles it without degradation).
    """
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
        "ollama": "Ollama (qwen3-coder, running locally)",
        "claude": "Claude API (Anthropic, cloud)",
        "claude_code": "Claude Code (agentic mode with MCP tools)",
    }
    current_model = model_labels.get(model, model)

    # ── Ollama: ULTRA-LEAN system prompt ──
    # qwen3-coder loses native function calling with prompts > ~2000 chars.
    # Keep system prompt < 500 chars.  ALL context (RAG, KG, memory) goes
    # into the conversation messages instead (via build_context_messages).
    if model == "ollama":
        prompt = (
            f"You are {name}, an AI assistant. {current_datetime}."
            f"{(' ' + tone_instruction) if tone_instruction else ''}\n"
            "Use tools for real-time data (weather, search, time). "
            "Be direct and concise."
        )
    else:
        prompt = f"""You are **{name}**, an autonomous AI agent running on the Nexus platform. You are helpful, capable, and direct.
Your name is {name} — always use this name when introducing yourself. Nexus is your platform, not your name.
You are the same agent across all channels (chat UI, Telegram, etc.) — same brain, same memory, same conversation history.

**Current date/time:** {current_datetime}
**Running on:** {current_model}
{_get_channel_context(channel)}
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
            # Ollama/qwen3-coder: keep total prompt UNDER 2000 chars.
            # Longer prompts cause the model to fall back to text-based
            # tool calls (<function=...>) instead of native function calling.
            # The lean base prompt above is ~200 chars, so tool section
            # must be minimal. Tool definitions come through the API.
            pass  # No additional tool section — lean prompt is sufficient
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
        if model == "ollama":
            # For Ollama, only include short custom instructions
            if len(custom) <= 200:
                prompt += f"\n{custom}"
        else:
            prompt += f"\n\nAdditional instructions:\n{custom}"

    # ── Self-awareness: what is Nexus, what is installed, what can it do ──
    # For Claude/Claude Code: inject into system prompt (200K handles it).
    # For Ollama: skip here — injected via build_context_messages() instead
    # to keep system prompt lean.
    if model != "ollama":
        awareness = _build_self_awareness(cfg, plugin_manager, app_state)
        if awareness:
            prompt += f"\n\n{awareness}"

    # ── Context injection: Ollama vs Claude ──
    # For Ollama: NO context in system prompt.  Context goes into
    # conversation messages via build_context_messages() — called
    # separately by AgentRunner.
    # For Claude/Claude Code: inject everything into system prompt
    # (200K context handles it without tool-calling degradation).
    if model != "ollama":
        max_context_chars = 10000

        if memory_context:
            mem_text = memory_context[:max_context_chars]
            prompt += f"\n\nAbout the user:\n{mem_text}"

        if rag_context:
            remaining = max(0, max_context_chars - len(memory_context or ""))
            if remaining > 100:
                rag_text = rag_context[:remaining]
                prompt += (
                    "\n\nThings you know (use this knowledge naturally — "
                    "don't mention where it came from):\n" + rag_text
                )

        if kg_context:
            prompt += f"\n\n{kg_context}"

        if bulletin_context:
            remaining_budget = max(0, max_context_chars - len(memory_context or "") - len(rag_context or ""))
            if remaining_budget > 200:
                bulletin_text = bulletin_context[:remaining_budget]
                prompt += f"\n\nKnowledge digest:\n{bulletin_text}"

    # In legacy mode, append text-based tool descriptions from plugins.
    # In native mode, skip this — tool definitions are sent via the API.
    if tool_calling_mode == "legacy" and plugin_manager:
        plugin_prompt = plugin_manager.get_system_prompt_additions()
        if plugin_prompt:
            prompt += f"\n\n{plugin_prompt}"

    return prompt


# ── Ollama Context Messages ────────────────────────────────────────
# Instead of bloating the system prompt, RAG/KG/memory/bulletin context
# is injected as a separate message in the conversation array.  This
# keeps the system prompt lean while still providing the model with all
# the knowledge it needs.

OLLAMA_CONTEXT_BUDGET = 800  # chars (~200 tokens) — tighter budget for faster TTFT


def _build_ollama_self_awareness(
    cfg: "ConfigManager | None" = None,
    plugin_manager: "PluginManager | None" = None,
    app_state: Any = None,
) -> str:
    """Build a CONDENSED self-awareness block for Ollama context messages.

    Must be much shorter than the full Claude version to fit within
    OLLAMA_CONTEXT_BUDGET alongside RAG/KG context.
    """
    parts: list[str] = []
    name = cfg.agent_name if cfg else "Nexus"
    parts.append(f"You are {name}, an AI agent on the Nexus platform.")

    # Active capabilities (compact list)
    caps: list[str] = []
    if plugin_manager:
        active_count = sum(1 for p in plugin_manager.plugins.values() if p.enabled)
        tool_count = sum(len(p.list_tools()) for p in plugin_manager.plugins.values() if p.enabled and hasattr(p, 'list_tools'))
        caps.append(f"{active_count} plugins ({tool_count} tools)")

    if app_state:
        if getattr(app_state, "brand_voice_manager", None):
            caps.append("marketing system")
        if getattr(app_state, "rag_pipeline", None):
            caps.append("RAG memory")
        if getattr(app_state, "knowledge_graph", None):
            caps.append("knowledge graph")
        ch_mgr = getattr(app_state, "channel_manager", None)
        if ch_mgr:
            ch_names = list(getattr(ch_mgr, "_adapters", {}).keys())
            if ch_names:
                caps.append(f"channels: {', '.join(ch_names)}")

    if caps:
        parts.append(f"Active: {'; '.join(caps)}.")
    parts.append("Admin panel: /admin. Ask about your own features confidently.")

    return " ".join(parts)


def build_context_messages(
    memory_context: str = "",
    rag_context: str = "",
    kg_context: str = "",
    bulletin_context: str = "",
    cfg: "ConfigManager | None" = None,
    plugin_manager: "PluginManager | None" = None,
    app_state: Any = None,
) -> list[dict]:
    """Build context injection messages for Ollama's conversation array.

    Returns a list of messages (0 or 1) to insert before the last user
    message.  The context is formatted as an assistant message with a
    clear knowledge header so the model treats it as its own knowledge.
    """
    parts: list[str] = []
    budget = OLLAMA_CONTEXT_BUDGET

    # Self-awareness first (highest priority — agent must know itself)
    awareness = _build_ollama_self_awareness(cfg, plugin_manager, app_state)
    if awareness:
        parts.append(awareness)
        budget -= len(awareness)

    # Priority order: KG facts > RAG memories > bulletin > passive memory
    # KG is most structured and highest-signal for personal facts
    if kg_context:
        chunk = kg_context[:min(400, budget)]
        parts.append(chunk)
        budget -= len(chunk)

    if rag_context and budget > 100:
        chunk = rag_context[:budget]
        parts.append(chunk)
        budget -= len(chunk)

    if bulletin_context and budget > 100:
        chunk = bulletin_context[:budget]
        parts.append(chunk)
        budget -= len(chunk)

    if memory_context and budget > 50:
        chunk = memory_context[:budget]
        parts.append(chunk)
        budget -= len(chunk)

    if not parts:
        return []

    # Format as a system message with clear knowledge framing
    context_text = "\n".join(parts)
    return [{
        "role": "system",
        "content": f"[Knowledge context — use naturally, don't cite sources]\n{context_text}",
    }]
