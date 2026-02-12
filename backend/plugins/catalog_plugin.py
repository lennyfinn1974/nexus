"""Skill Catalog Plugin — enables the agent to browse, search, and install skills.

This is the self-improvement engine: the agent can discover capabilities it
needs from the anti-gravity skills library (713+ skills) and install them
on-the-fly, making them available for future conversations.

Also provides meta-tools for mid-conversation skill invocation:
    - skill_execute: Run any installed skill action by name
    - skill_get_knowledge: Load a skill's knowledge into context
    - skill_list_actions: List all available skill actions

Tools:
    - skill_catalog_search: Search the catalog for skills by topic
    - skill_catalog_install: Install a skill from the catalog
    - skill_catalog_categories: List available skill categories
    - skill_execute: Execute an installed skill action dynamically
    - skill_get_knowledge: Load skill knowledge into current context
    - skill_list_actions: List all executable skill actions
"""

import asyncio
import logging
import os
import time
from typing import Any

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.catalog")


class CatalogPlugin(NexusPlugin):
    name = "catalog"
    description = "Search and install skills from external catalogs (anti-gravity, etc.)"
    version = "1.0.0"

    def __init__(self, config, db, router):
        super().__init__(config, db, router)
        self._catalog = None
        self._skills_engine = None

    async def setup(self) -> bool:
        """Initialize — catalog and skills engine are injected after plugin load."""
        # These get set by _post_setup() called from app.py
        return True

    def set_catalog(self, catalog, skills_engine):
        """Inject catalog and skills engine references (called after plugin load)."""
        self._catalog = catalog
        self._skills_engine = skills_engine
        if self._catalog and self._catalog.index:
            logger.info(f"Catalog plugin: {len(self._catalog.index)} skills available")
            self.enabled = True
        else:
            logger.warning("Catalog plugin: no catalog available, plugin disabled")
            self.enabled = False

    def register_tools(self) -> None:
        """Register skill catalog tools."""
        self.add_tool(
            "skill_catalog_search",
            "Search the skill catalog for available skills by topic or keyword. "
            "Returns matching skills that can be installed. Use this when you need "
            "a new capability, want to learn about a topic, or the user asks about "
            "available skills. There are 700+ skills covering development, security, "
            "AI/ML, architecture, DevOps, business, and more.",
            {
                "query": "Search terms to find skills (e.g. 'react best practices', 'rag', 'security audit')",
                "category": "(Optional) Filter by category (use skill_catalog_categories to see available categories)",
            },
            self._skill_catalog_search,
            category="skills",
        )

        self.add_tool(
            "skill_catalog_install",
            "Install a skill from the catalog into Nexus. After installation, "
            "the skill's knowledge becomes available in future conversations. "
            "Use the skill_id from search results.",
            {
                "skill_id": "ID of the skill to install (from search results)",
            },
            self._skill_catalog_install,
            category="skills",
        )

        self.add_tool(
            "skill_catalog_categories",
            "List all available skill categories in the catalog with counts. "
            "Use this to help the user discover what kinds of skills are available.",
            {},
            self._skill_catalog_categories,
            category="skills",
        )

        # ── Meta-tools for mid-conversation skill invocation ──

        self.add_tool(
            "skill_execute",
            "Execute an installed skill action by name. Use this to dynamically "
            "invoke any skill action mid-conversation, even if it wasn't in the "
            "initial tool set. First use skill_list_actions to see available actions. "
            "Example: action_name='google_search', params='{\"query\": \"AI news\"}'",
            {
                "action_name": "The name of the skill action to execute (e.g. 'google_search', 'list_events')",
                "params": "JSON string of parameters to pass to the action (e.g. '{\"query\": \"test\"}')",
            },
            self._skill_execute,
            category="skills",
        )

        self.add_tool(
            "skill_get_knowledge",
            "Load the knowledge content of an installed skill into context. "
            "Use this when you need a skill's methodology, guidelines, or reference "
            "material to help answer the user's question. Returns the skill's knowledge.md content.",
            {
                "skill_id": "ID of the installed skill (e.g. 'brainstorming', 'rag-engineer', 'docker-expert')",
            },
            self._skill_get_knowledge,
            category="skills",
        )

        self.add_tool(
            "skill_list_actions",
            "List all executable skill actions across all installed skills. "
            "Shows action names, descriptions, parameters, and which skill they belong to. "
            "Use this to discover what actions are available before calling skill_execute.",
            {},
            self._skill_list_actions,
            category="skills",
        )

    async def _skill_catalog_search(self, params: dict) -> str:
        """Search the skill catalog."""
        if not self._catalog:
            return "Skill catalog is not available."

        query = params.get("query", "")
        category = params.get("category", "")

        if not query and not category:
            return "Please provide a search query or category."

        results = self._catalog.search(query, category=category or None, limit=10)

        if not results:
            return f"No skills found matching '{query}'." + (
                f" in category '{category}'" if category else ""
            )

        lines = [f"**Found {len(results)} skill(s):**\n"]
        for r in results:
            status = "✓ installed" if r.get("installed") else "available"
            desc = r.get("description", "")[:100]
            lines.append(
                f"- **{r['id']}** [{r.get('category', 'general')}] ({status})\n"
                f"  {desc}{'...' if len(r.get('description', '')) > 100 else ''}"
            )

        lines.append(
            "\nTo install a skill: use `skill_catalog_install` with the skill ID."
        )
        return "\n".join(lines)

    async def _skill_catalog_install(self, params: dict) -> str:
        """Install a skill from the catalog."""
        if not self._catalog or not self._skills_engine:
            return "Skill catalog or skills engine is not available."

        skill_id = params.get("skill_id", "").strip()
        if not skill_id:
            return "Please provide a skill_id to install."

        entry = self._catalog.get_by_id(skill_id)
        if not entry:
            return f"Skill '{skill_id}' not found in catalog. Use skill_catalog_search to find available skills."

        if entry.get("installed"):
            return f"Skill '{skill_id}' is already installed and available."

        try:
            from skills.converter import convert_antigravity_skill
            from skills.engine import Skill

            dest_dir = os.path.join(self._skills_engine.skills_dir, skill_id)
            manifest = convert_antigravity_skill(
                source_dir=entry["source_path"],
                dest_dir=dest_dir,
                category=entry.get("category", "general"),
                skill_id=skill_id,
            )

            # Hot-load into the skills engine
            skill = Skill(dest_dir, manifest)
            self._skills_engine._load_actions(skill)
            self._skills_engine.skills[skill_id] = skill

            # Persist to DB
            try:
                await self._skills_engine.db.save_skill(
                    skill_id,
                    manifest["name"],
                    manifest.get("description", ""),
                    manifest.get("domain", "general"),
                    os.path.join(dest_dir, "knowledge.md"),
                )
            except Exception as e:
                logger.warning(f"DB save for skill '{skill_id}' failed: {e}")

            # Refresh catalog installed status
            self._catalog.refresh_installed()

            return (
                f"Successfully installed skill: **{manifest['name']}**\n"
                f"- Domain: {manifest.get('domain', 'general')}\n"
                f"- Keywords: {', '.join(manifest.get('triggers', {}).get('keywords', []))}\n"
                f"This skill is now active and will be used in future conversations "
                f"when relevant topics come up."
            )

        except Exception as e:
            logger.error(f"Failed to install skill '{skill_id}': {e}")
            return f"Failed to install skill '{skill_id}': {e}"

    async def _skill_catalog_categories(self, params: dict) -> str:
        """List available categories."""
        if not self._catalog:
            return "Skill catalog is not available."

        categories = self._catalog.list_categories()
        if not categories:
            return "No categories found in the catalog."

        lines = [f"**Skill Catalog Categories** ({len(self._catalog.index)} total skills):\n"]
        for cat in categories:
            lines.append(f"- **{cat['category']}**: {cat['count']} skills")
        lines.append(
            "\nUse `skill_catalog_search` with a category filter to browse skills in a specific category."
        )
        return "\n".join(lines)

    # ── Meta-tool handlers ──────────────────────────────────────────

    async def _skill_execute(self, params: dict) -> str:
        """Execute a skill action dynamically mid-conversation."""
        if not self._skills_engine:
            return "Skills engine is not available."

        action_name = params.get("action_name", "").strip()
        if not action_name:
            return "Please provide an action_name to execute."

        # Parse params JSON string
        import json
        params_str = params.get("params", "{}")
        try:
            action_params = json.loads(params_str) if isinstance(params_str, str) else params_str
        except json.JSONDecodeError as e:
            return f"Invalid params JSON: {e}. Pass a valid JSON string."

        if not isinstance(action_params, dict):
            action_params = {}

        # Execute with timing and audit
        start = time.monotonic()
        try:
            result = await self._skills_engine.execute_action(action_name, action_params)
            duration_ms = (time.monotonic() - start) * 1000

            # Audit log
            logger.info(
                f"skill_execute: {action_name} completed in {duration_ms:.1f}ms "
                f"(params: {list(action_params.keys())})"
            )

            return result
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(f"skill_execute: {action_name} failed in {duration_ms:.1f}ms: {e}")
            return f"Error executing action '{action_name}': {e}"

    async def _skill_get_knowledge(self, params: dict) -> str:
        """Load a skill's knowledge content into context."""
        if not self._skills_engine:
            return "Skills engine is not available."

        skill_id = params.get("skill_id", "").strip()
        if not skill_id:
            # List available skills to help
            ids = sorted(self._skills_engine.skills.keys())
            return f"Please provide a skill_id. Available: {', '.join(ids)}"

        skill = self._skills_engine.skills.get(skill_id)
        if not skill:
            # Fuzzy match — try partial matches
            matches = [
                sid for sid in self._skills_engine.skills
                if skill_id.lower() in sid.lower()
            ]
            if matches:
                return (
                    f"Skill '{skill_id}' not found. Did you mean: {', '.join(matches)}?"
                )
            return f"Skill '{skill_id}' not found. Use /skills to see installed skills."

        knowledge = skill.get_knowledge()
        if not knowledge:
            return f"Skill '{skill_id}' has no knowledge content."

        # Strip YAML frontmatter
        if knowledge.startswith("---"):
            end = knowledge.find("---", 3)
            if end != -1:
                knowledge = knowledge[end + 3:].strip()

        # Add metadata header
        header = (
            f"## Skill: {skill.name}\n"
            f"**Type:** {skill.type} | **Domain:** {skill.domain}\n"
            f"**Description:** {skill.description}\n\n"
        )

        # Add available actions if any
        actions_info = ""
        if skill.actions:
            configured = skill.is_configured(self._skills_engine.config) if self._skills_engine.config else True
            if configured:
                actions_info = "\n**Available actions:**\n"
                for a in skill.actions:
                    actions_info += a.to_prompt_description() + "\n"
                actions_info += "\nUse `skill_execute` to call these actions.\n\n"

        return header + actions_info + knowledge

    async def _skill_list_actions(self, params: dict) -> str:
        """List all executable skill actions."""
        if not self._skills_engine:
            return "Skills engine is not available."

        lines = ["**Installed Skill Actions:**\n"]
        total = 0

        for skill in sorted(self._skills_engine.skills.values(), key=lambda s: s.name):
            if not skill.actions:
                continue

            configured = skill.is_configured(self._skills_engine.config) if self._skills_engine.config else True
            status = "ready" if configured else "needs config"

            lines.append(f"### {skill.name} ({skill.id}) [{status}]")
            for action in skill.actions:
                param_str = ", ".join(f"{k}: {v}" for k, v in action.parameters.items())
                lines.append(f"  - **{action.name}**({param_str})")
                lines.append(f"    {action.description}")
                total += 1
            lines.append("")

        if total == 0:
            return "No skill actions are currently installed. Use skill_catalog_search and skill_catalog_install to add skills with actions."

        lines.insert(1, f"_{total} actions across {sum(1 for s in self._skills_engine.skills.values() if s.actions)} skills_\n")
        lines.append("Use `skill_execute` with `action_name` and `params` to call any action.")
        return "\n".join(lines)
