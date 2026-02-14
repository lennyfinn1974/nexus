"""Skills Engine v2 — Knowledge packs and integration connectors.

Skills come in two flavors:

1. **Knowledge Skills** — markdown files with research, concepts, decision
   guides.  Created via ``/learn`` or document ingestion.

2. **Integration Skills** — structured packs with a config schema (settings
   they need such as API keys), trigger patterns (when to activate),
   actions (functions the AI can invoke), and knowledge content.

Both live in ``data/skills/<skill_id>/`` as folders with a ``skill.yaml``
manifest.

Folder layout::

    data/skills/google-search/
        skill.yaml          # Manifest
        knowledge.md        # Context injected into prompts
        actions.py          # Optional: executable action handlers
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import time
import uuid
from collections import defaultdict

import yaml

logger = logging.getLogger("nexus.skills")


# ── Template for /learn-created knowledge ──

KNOWLEDGE_TEMPLATE = """# {name}

## Overview
{overview}

## Key Concepts
{concepts}

## Decision Guide
{decision_guide}

## Quick Reference
{quick_reference}

## Sources & Notes
{sources}
"""


# ────────────────────────────────────────────────────────────────────
# Data classes
# ────────────────────────────────────────────────────────────────────


class SkillAction:
    """An action exposed by a skill (lighter than a full plugin tool)."""

    def __init__(self, name: str, description: str, parameters: dict, handler):
        self.name = name
        self.description = description
        self.parameters = parameters  # {param_name: description_str}
        self.handler = handler  # async callable(params) -> str

    def to_prompt_description(self) -> str:
        params = ", ".join(f"{k}: {v}" for k, v in self.parameters.items())
        return f"- **{self.name}**({params}): {self.description}"

    def validate_params(self, params: dict) -> list[str]:
        """Validate parameters against the action's parameter schema.

        Returns a list of warning messages (empty = all good).
        Checks for missing parameters and flags unknown ones.
        """
        warnings = []
        provided = {k for k in params if k != "_config"}
        expected = set(self.parameters.keys())

        missing = expected - provided
        if missing:
            # Check if the description hints at a default (e.g. "default 7")
            truly_missing = []
            for m in missing:
                desc = str(self.parameters.get(m, "")).lower()
                if "default" not in desc and "optional" not in desc:
                    truly_missing.append(m)
            if truly_missing:
                warnings.append(
                    f"Missing required parameter(s): {', '.join(truly_missing)}"
                )

        unknown = provided - expected
        if unknown:
            warnings.append(
                f"Unknown parameter(s): {', '.join(unknown)} "
                f"(expected: {', '.join(expected)})"
            )

        return warnings


class Skill:
    """A loaded skill — manifest + knowledge + optional actions."""

    def __init__(self, skill_dir: str, manifest: dict):
        self.dir = skill_dir
        self.manifest = manifest
        self.id: str = manifest["id"]
        self.name: str = manifest.get("name", self.id)
        self.type: str = manifest.get("type", "knowledge")  # knowledge | integration
        self.version: str = manifest.get("version", "1.0")
        self.domain: str = manifest.get("domain", "general")
        self.description: str = manifest.get("description", "")
        self.author: str = manifest.get("author", "user")

        # Config schema  {KEY: {label, type, required, description}}
        self.config_schema: dict = manifest.get("config", {})

        # Trigger keywords & regex patterns
        triggers = manifest.get("triggers", {})
        self.keywords: list[str] = [k.lower() for k in triggers.get("keywords", [])]
        self.patterns: list[re.Pattern] = []
        for p in triggers.get("patterns", []):
            try:
                self.patterns.append(re.compile(p, re.IGNORECASE))
            except re.error:
                logger.warning(f"Skill {self.id}: bad regex: {p}")

        # Action definitions (from manifest) & loaded handlers
        self.action_defs: list[dict] = manifest.get("actions", [])
        self.actions: list[SkillAction] = []

        # Knowledge — lazy-loaded
        self._knowledge: str | None = None
        self._legacy_file: str | None = None  # for migrated single-file skills

    # ── knowledge ──

    @property
    def knowledge_path(self) -> str:
        return os.path.join(self.dir, "knowledge.md")

    @property
    def actions_path(self) -> str:
        return os.path.join(self.dir, "actions.py")

    def get_knowledge(self) -> str:
        if self._knowledge is None:
            try:
                # Try standard location first
                if os.path.exists(self.knowledge_path):
                    with open(self.knowledge_path) as f:
                        self._knowledge = f.read()
                # Fall back to legacy single-file path
                elif self._legacy_file and os.path.exists(self._legacy_file):
                    with open(self._legacy_file) as f:
                        self._knowledge = f.read()
                else:
                    self._knowledge = ""
            except (PermissionError, OSError) as e:
                logger.warning(f"Cannot read knowledge for {self.id}: {e}")
                self._knowledge = ""
        return self._knowledge

    # ── matching ──

    def matches(self, message: str) -> float:
        """Score how well this skill matches a message.  0 = no match."""
        msg_lower = message.lower()
        msg_words = set(re.findall(r"\w+", msg_lower))
        score = 0.0

        # Keyword matching
        for kw in self.keywords:
            kw_words = set(kw.split())
            if kw_words.issubset(msg_words):
                score += 2.0
            elif kw_words & msg_words:
                score += 0.5

        # Regex pattern matching (strong signal)
        for pat in self.patterns:
            if pat.search(msg_lower):
                score += 3.0

        # Weak fallback: name/description word overlap
        score += len(set(re.findall(r"\w+", self.name.lower())) & msg_words) * 0.3
        score += len(set(re.findall(r"\w+", self.description.lower())) & msg_words) * 0.2

        return score

    # ── config helpers ──

    def get_config_status(self, config_manager) -> dict:
        status = {}
        for key, schema in self.config_schema.items():
            value = config_manager.get(key, "")
            status[key] = {
                "label": schema.get("label", key),
                "type": schema.get("type", "text"),
                "required": schema.get("required", False),
                "description": schema.get("description", ""),
                "is_set": bool(value),
            }
        return status

    def is_configured(self, config_manager) -> bool:
        for key, schema in self.config_schema.items():
            if schema.get("required", False) and not config_manager.get(key, ""):
                return False
        return True

    # ── serialization ──

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "version": self.version,
            "domain": self.domain,
            "description": self.description,
            "author": self.author,
            "has_actions": bool(self.action_defs),
            "config_keys": list(self.config_schema.keys()),
            "keywords": self.keywords,
        }


# ────────────────────────────────────────────────────────────────────
# Engine
# ────────────────────────────────────────────────────────────────────


class SkillsEngine:
    """Load, match, invoke, and manage skills."""

    def __init__(self, skills_dir: str, db, config_manager=None):
        self.skills_dir = skills_dir
        self.db = db
        self.config = config_manager
        self.skills: dict[str, Skill] = {}
        os.makedirs(skills_dir, exist_ok=True)

        # ── Audit tracking ──
        # Tracks action execution history for observability
        self._audit_log: list[dict] = []  # Recent action executions (ring buffer, max 200)
        self._audit_stats: dict[str, dict] = defaultdict(
            lambda: {"calls": 0, "errors": 0, "total_ms": 0.0}
        )
        _AUDIT_LOG_MAX = 200

    # ── loading ──

    async def load_all(self):
        """Scan skills_dir and load every skill manifest."""
        self.skills.clear()
        count = 0

        for item in sorted(os.listdir(self.skills_dir)):
            skill_path = os.path.join(self.skills_dir, item)
            if not os.path.isdir(skill_path):
                continue

            manifest_path = os.path.join(skill_path, "skill.yaml")
            if not os.path.exists(manifest_path):
                continue  # Not a valid skill folder

            try:
                with open(manifest_path) as f:
                    manifest = yaml.safe_load(f) or {}
                manifest.setdefault("id", item)

                skill = Skill(skill_path, manifest)
                self._load_actions(skill)
                self.skills[skill.id] = skill
                count += 1
                logger.info(f"Loaded skill: {skill.name} ({skill.type})")
            except Exception as e:
                logger.error(f"Failed to load skill {item}: {e}")

        # Incorporate legacy DB-registered skills
        await self._load_legacy_skills()
        logger.info(f"Skills engine: {len(self.skills)} skills ready")

    async def _load_legacy_skills(self):
        """Import skills created by the old engine (DB + single .md file)."""
        try:
            db_skills = await self.db.list_skills()
        except Exception:
            return

        for s in db_skills:
            sid = s["id"]
            if sid in self.skills:
                continue

            file_path = s.get("file_path", "")
            if not file_path or not os.path.exists(file_path):
                continue

            # Build a Skill object that points at the legacy file
            name = s.get("name", sid)
            desc = s.get("description", "")
            manifest = {
                "id": sid,
                "name": name,
                "type": "knowledge",
                "domain": s.get("domain", "general"),
                "description": desc,
                "triggers": {
                    "keywords": re.findall(r"\w+", f"{name} {desc}".lower()),
                },
            }
            skill = Skill(os.path.dirname(file_path), manifest)
            skill._legacy_file = file_path
            self.skills[sid] = skill

    def _load_actions(self, skill: Skill):
        """Dynamically load action handlers from actions.py."""
        if not os.path.exists(skill.actions_path):
            return
        try:
            spec = importlib.util.spec_from_file_location(
                f"skill_actions_{skill.id}",
                skill.actions_path,
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            for adef in skill.action_defs:
                handler_name = adef.get("handler", adef["name"])
                handler = getattr(mod, handler_name, None)
                if handler and callable(handler):
                    skill.actions.append(
                        SkillAction(
                            name=adef["name"],
                            description=adef.get("description", ""),
                            parameters=adef.get("parameters", {}),
                            handler=handler,
                        )
                    )
                    logger.info(f"  Action: {adef['name']}")
                else:
                    logger.warning(f"  Action handler missing: {handler_name}")
        except Exception as e:
            logger.error(f"Failed loading actions for {skill.id}: {e}")

    # ── querying ──

    async def find_relevant_skills(self, message: str, threshold: float = 0.5) -> list:
        results = []
        for skill in self.skills.values():
            score = skill.matches(message)
            if score >= threshold:
                results.append((skill, score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:5]

    async def build_skill_context(self, message: str) -> str:
        """Build context string for prompt injection."""
        relevant = await self.find_relevant_skills(message)
        if not relevant:
            return ""

        parts = ["## Available Knowledge & Integrations\n"]
        for skill, _score in relevant:
            knowledge = skill.get_knowledge()
            if knowledge:
                # Strip YAML frontmatter
                if knowledge.startswith("---"):
                    end = knowledge.find("---", 3)
                    if end != -1:
                        knowledge = knowledge[end + 3 :].strip()
                if len(knowledge) > 2000:
                    knowledge = knowledge[:2000] + "\n...(truncated)"
                parts.append(f"### {skill.name}\n{knowledge}\n")

            if skill.actions:
                configured = skill.is_configured(self.config) if self.config else True
                if configured:
                    parts.append(f"**Actions for {skill.name}:**")
                    for a in skill.actions:
                        parts.append(a.to_prompt_description())
                    parts.append("")

            try:
                await self.db.increment_skill_usage(skill.id)
            except Exception:
                pass

        return "\n".join(parts)

    async def build_skill_directory(self, message: str) -> str:
        """Build a lightweight skill directory — names + descriptions only.

        Instead of injecting full knowledge (up to 2000 chars each × 5 skills),
        this returns just the skill ID, name, and description (~50 tokens/skill).
        The model can load full knowledge on demand via skill_get_knowledge tool.
        Saves ~8000 tokens vs build_skill_context() on Ollama's 32K window.
        """
        relevant = await self.find_relevant_skills(message)
        if not relevant:
            return ""

        parts = ["## Relevant Skills (use skill_get_knowledge to load details)\n"]
        for skill, _score in relevant:
            actions_hint = ""
            if skill.actions:
                action_names = [a.name for a in skill.actions]
                actions_hint = f" | Actions: {', '.join(action_names)}"
            parts.append(
                f"- **{skill.name}** (`{skill.id}`): {skill.description}{actions_hint}"
            )

        return "\n".join(parts)

    async def execute_action(self, action_name: str, params: dict) -> str:
        """Find and run a skill action by name, with audit logging."""
        import asyncio as _asyncio

        for skill in self.skills.values():
            for action in skill.actions:
                if action.name == action_name:
                    if self.config and not skill.is_configured(self.config):
                        missing = [
                            k for k, s in skill.config_schema.items()
                            if s.get("required") and not self.config.get(k)
                        ]
                        return (
                            f"Skill '{skill.name}' not configured. "
                            f"Missing: {', '.join(missing)}"
                        )

                    # Validate parameters before execution
                    param_warnings = action.validate_params(params)
                    if param_warnings:
                        for w in param_warnings:
                            logger.warning(f"Action {action_name}: {w}")

                    start = time.monotonic()
                    error_msg = None
                    try:
                        # Inject config and validate params
                        exec_params = {k: v for k, v in params.items() if k != "_config"}
                        exec_params["_config"] = self.config

                        result = action.handler(exec_params)
                        # Support both sync and async action handlers
                        if _asyncio.iscoroutine(result):
                            result = await result
                        return str(result)
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"Action {action_name} failed: {e}")
                        return f"Error: {e}"
                    finally:
                        duration_ms = (time.monotonic() - start) * 1000
                        self._record_audit(
                            skill_id=skill.id,
                            action_name=action_name,
                            params={k: v for k, v in params.items() if k != "_config"},
                            duration_ms=duration_ms,
                            error=error_msg,
                        )

        return f"Unknown action: {action_name}"

    def _record_audit(
        self,
        skill_id: str,
        action_name: str,
        params: dict,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        """Record an action execution in the audit log."""
        import datetime as _dt

        entry = {
            "timestamp": _dt.datetime.now().isoformat(),
            "skill_id": skill_id,
            "action": action_name,
            "params": {k: str(v)[:100] for k, v in params.items()},  # Truncate values
            "duration_ms": round(duration_ms, 1),
            "success": error is None,
            "error": error,
        }

        # Ring buffer — keep last 200 entries
        self._audit_log.append(entry)
        if len(self._audit_log) > 200:
            self._audit_log = self._audit_log[-200:]

        # Aggregate stats
        stats = self._audit_stats[action_name]
        stats["calls"] += 1
        stats["total_ms"] += duration_ms
        if error:
            stats["errors"] += 1

        logger.info(
            f"Skill audit: {skill_id}/{action_name} "
            f"{'OK' if not error else 'FAIL'} "
            f"in {duration_ms:.1f}ms"
        )

    def get_audit_summary(self) -> dict:
        """Return audit stats for all skill actions."""
        summary = {}
        for action_name, stats in self._audit_stats.items():
            avg_ms = stats["total_ms"] / stats["calls"] if stats["calls"] else 0
            summary[action_name] = {
                "calls": stats["calls"],
                "errors": stats["errors"],
                "avg_ms": round(avg_ms, 1),
                "total_ms": round(stats["total_ms"], 1),
            }
        return summary

    def get_recent_audit_log(self, limit: int = 20) -> list[dict]:
        """Return the most recent audit log entries."""
        return self._audit_log[-limit:]

    # ── listing ──

    async def list_skills(self) -> list:
        result = []
        for skill in self.skills.values():
            info = skill.to_dict()
            if self.config:
                info["configured"] = skill.is_configured(self.config)
                info["config_status"] = skill.get_config_status(self.config)
            result.append(info)
        return result

    # ── creation ──

    async def create_knowledge_skill(
        self,
        name,
        domain,
        description,
        overview,
        concepts,
        decision_guide,
        quick_reference,
        sources,
        keywords,
    ) -> dict:
        """Create a knowledge skill from /learn output."""
        skill_id = f"skill-{uuid.uuid4().hex[:8]}"
        skill_dir = os.path.join(self.skills_dir, skill_id)
        os.makedirs(skill_dir, exist_ok=True)

        manifest = {
            "id": skill_id,
            "name": name,
            "type": "knowledge",
            "version": "1.0",
            "domain": domain,
            "description": description,
            "author": "user",
            "triggers": {"keywords": keywords[:10]},
        }
        with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
            yaml.dump(manifest, f, default_flow_style=False)

        content = KNOWLEDGE_TEMPLATE.format(
            name=name,
            overview=overview,
            concepts=concepts,
            decision_guide=decision_guide,
            quick_reference=quick_reference,
            sources=sources,
        )
        with open(os.path.join(skill_dir, "knowledge.md"), "w") as f:
            f.write(content)

        await self.db.save_skill(
            skill_id,
            name,
            description,
            domain,
            os.path.join(skill_dir, "knowledge.md"),
        )
        skill = Skill(skill_dir, manifest)
        self.skills[skill_id] = skill
        logger.info(f"Created skill: {name} ({skill_id})")
        return {"id": skill_id, "name": name, "domain": domain}

    async def install_skill_pack(self, source_dir: str) -> dict:
        """Install a skill pack from a directory."""
        import shutil

        manifest_path = os.path.join(source_dir, "skill.yaml")
        if not os.path.exists(manifest_path):
            raise ValueError(f"No skill.yaml in {source_dir}")

        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)

        skill_id = manifest.get("id", os.path.basename(source_dir))
        dest = os.path.join(self.skills_dir, skill_id)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(source_dir, dest)

        skill = Skill(dest, manifest)
        self._load_actions(skill)
        self.skills[skill_id] = skill
        await self.db.save_skill(
            skill_id,
            skill.name,
            skill.description,
            skill.domain,
            skill.knowledge_path,
        )
        logger.info(f"Installed skill pack: {skill.name}")
        return skill.to_dict()

    async def delete_skill(self, skill_id: str):
        import shutil

        d = os.path.join(self.skills_dir, skill_id)
        if os.path.isdir(d):
            shutil.rmtree(d)
        self.skills.pop(skill_id, None)
        await self.db.delete_skill(skill_id)
        logger.info(f"Deleted skill: {skill_id}")

    # ── research prompt ──

    def get_research_prompt(self, topic: str) -> str:
        return f"""You are a research analyst. Thoroughly research and distil knowledge about the following topic.

Topic: {topic}

Respond in this exact format:

<overview>
2-3 paragraph overview. What is it? Why does it matter?
</overview>

<concepts>
Key concepts as bullet points (5-10).
</concepts>

<decision_guide>
Practical guide: "If user asks X, consider Y."
</decision_guide>

<quick_reference>
Cheat sheet of the most important facts, numbers, commands.
</quick_reference>

<sources>
Key sources and caveats.
</sources>

<metadata>
name: (short name)
domain: (category)
description: (one sentence)
keywords: (comma-separated, 5-10)
</metadata>

Be thorough, accurate, and practical."""

    def parse_research_output(self, output: str) -> dict:
        def extract(tag):
            m = re.search(f"<{tag}>(.*?)</{tag}>", output, re.DOTALL)
            return m.group(1).strip() if m else ""

        meta_raw = extract("metadata")
        meta = {}
        for line in meta_raw.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()

        kws = [k.strip() for k in meta.get("keywords", "").split(",") if k.strip()]
        return {
            "name": meta.get("name", "Untitled"),
            "domain": meta.get("domain", "general"),
            "description": meta.get("description", ""),
            "overview": extract("overview"),
            "concepts": extract("concepts"),
            "decision_guide": extract("decision_guide"),
            "quick_reference": extract("quick_reference"),
            "sources": extract("sources"),
            "keywords": kws,
        }
