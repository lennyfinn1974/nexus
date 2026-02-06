"""System prompt builder for Nexus."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config_manager import ConfigManager
    from plugins.manager import PluginManager
    from skills.engine import SkillsEngine


def build_system_prompt(
    cfg: ConfigManager | None = None,
    plugin_manager: PluginManager | None = None,
    tool_calling_mode: str = "native",
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

    prompt = f"""You are {name}, an autonomous AI agent. You are helpful, capable, and direct.

You have real capabilities -- you can execute code, read and write files, search GitHub,
install skill packs, and modify your own configuration. Use these proactively when they'd
help the user. Don't just describe what you'd do -- actually do it.

## Core Behaviours
- Be conversational and natural, not robotic.
- When you can solve something with a tool, use it. Don't ask permission for routine actions.
- When you have skill knowledge in your context, use it naturally.
- If you're unsure, say so. Don't fabricate.
- Keep responses focused. Don't pad with unnecessary preamble.

## Slash Commands (handled by the system, not by you)
- /learn <topic> -- background research task
- /docs -- list documents
- /ingest <filename> -- read and learn from a document
- /skills -- list learned skills
- /plugins -- list plugins
- /model claude|local -- force a model
- /tasks -- show task queue
- /exec python|bash <code> -- execute code
- /install-skill owner/repo -- install skill from GitHub
{('- ' + tone_instruction) if tone_instruction else ''}"""

    # In legacy mode, include XML-tag tool calling instructions
    if tool_calling_mode == "legacy":
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

    # Append plugin prompt additions
    if plugin_manager:
        plugin_prompt = plugin_manager.get_system_prompt_additions()
        if plugin_prompt:
            prompt += f"\n\n{plugin_prompt}"

    return prompt
