"""Skill Catalog — index external skill sources for browsing, searching, installing.

Indexes anti-gravity skills (and future sources) from disk without importing
them into the Nexus skills engine.  Provides a read-only catalog for discovery
plus a conversion + install path.

The catalog prefers ``skills_index.json`` (anti-gravity ships one) for fast
loading.  Falls back to scanning ``SKILL.md`` files and parsing YAML
frontmatter.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import yaml

logger = logging.getLogger("nexus.skills.catalog")

# Common stopwords to skip during keyword extraction
_STOPWORDS = frozenset(
    "a an the and or but in on at to for of is it this that with from by as be"
    " are was were been have has had do does did will would shall should may might"
    " can could use when how what which who whom whose where why not no nor"
    " your you i my me we our they them their its".split()
)


class SkillCatalog:
    """Index of external skill sources (anti-gravity, GitHub, etc.)."""

    def __init__(self, sources: list[str], installed_dir: str | None = None):
        self.sources = [s for s in sources if os.path.isdir(s)]
        self.installed_dir = installed_dir  # Nexus skills directory for installed check
        self.index: list[dict] = []
        self._by_id: dict[str, dict] = {}

    # ── Loading ──────────────────────────────────────────────────

    def load_index(self) -> int:
        """Scan all source directories and build the index.  Returns count."""
        self.index.clear()
        self._by_id.clear()

        for source_dir in self.sources:
            try:
                count = self._load_source(source_dir)
                logger.info(f"Catalog: loaded {count} skills from {source_dir}")
            except Exception as e:
                logger.error(f"Catalog: failed to load {source_dir}: {e}")

        # Mark installed skills
        if self.installed_dir and os.path.isdir(self.installed_dir):
            installed_ids = set(os.listdir(self.installed_dir))
            for entry in self.index:
                entry["installed"] = entry["id"] in installed_ids

        logger.info(f"Catalog: {len(self.index)} total skills indexed")
        return len(self.index)

    def _load_source(self, source_dir: str) -> int:
        """Load skills from a single source directory."""
        # Fast path: use skills_index.json if available
        index_path = os.path.join(source_dir, "skills_index.json")
        if os.path.exists(index_path):
            return self._load_from_index_json(source_dir, index_path)

        # Slow path: scan SKILL.md files
        return self._load_from_scan(source_dir)

    def _load_from_index_json(self, source_dir: str, index_path: str) -> int:
        """Load from pre-built skills_index.json (anti-gravity format)."""
        with open(index_path) as f:
            raw = json.load(f)

        count = 0
        for entry in raw:
            skill_id = entry.get("id", "")
            if not skill_id or skill_id in self._by_id:
                continue

            # Resolve absolute path from relative path in index
            rel_path = entry.get("path", f"skills/{skill_id}")
            abs_path = os.path.join(source_dir, rel_path)

            record = {
                "id": skill_id,
                "name": entry.get("name", skill_id),
                "description": entry.get("description", ""),
                "category": entry.get("category", "general"),
                "source": entry.get("source", "antigravity"),
                "risk": entry.get("risk", "unknown"),
                "source_path": abs_path,
                "source_dir": source_dir,
                "installed": False,
                "size_kb": 0,
            }

            # Get file size if SKILL.md exists
            skill_md = os.path.join(abs_path, "SKILL.md")
            if os.path.exists(skill_md):
                try:
                    record["size_kb"] = round(os.path.getsize(skill_md) / 1024, 1)
                except OSError:
                    pass

            self.index.append(record)
            self._by_id[skill_id] = record
            count += 1

        return count

    def _load_from_scan(self, source_dir: str) -> int:
        """Scan directory tree for SKILL.md files and parse frontmatter."""
        skills_root = os.path.join(source_dir, "skills")
        if not os.path.isdir(skills_root):
            skills_root = source_dir

        count = 0
        for item in sorted(os.listdir(skills_root)):
            item_path = os.path.join(skills_root, item)
            if not os.path.isdir(item_path):
                continue

            skill_md = os.path.join(item_path, "SKILL.md")
            if not os.path.exists(skill_md):
                # Check subdirectories (some skills nest under category dirs)
                for sub in os.listdir(item_path):
                    sub_path = os.path.join(item_path, sub)
                    sub_skill = os.path.join(sub_path, "SKILL.md")
                    if os.path.isdir(sub_path) and os.path.exists(sub_skill):
                        self._parse_and_add(sub, sub_path, sub_skill, source_dir, category=item)
                        count += 1
                continue

            self._parse_and_add(item, item_path, skill_md, source_dir)
            count += 1

        return count

    def _parse_and_add(
        self, skill_id: str, skill_path: str, skill_md: str,
        source_dir: str, category: str = "general",
    ) -> None:
        """Parse SKILL.md frontmatter and add to index."""
        if skill_id in self._by_id:
            return

        name = skill_id
        description = ""
        source = "unknown"

        try:
            with open(skill_md, encoding="utf-8", errors="replace") as f:
                content = f.read(2000)  # Only need frontmatter

            if content.startswith("---"):
                end = content.find("---", 3)
                if end != -1:
                    try:
                        fm = yaml.safe_load(content[3:end]) or {}
                        name = fm.get("name", skill_id)
                        description = fm.get("description", "").strip()
                        source = fm.get("source", "unknown")
                    except yaml.YAMLError:
                        pass
        except OSError:
            pass

        record = {
            "id": skill_id,
            "name": name,
            "description": description,
            "category": category,
            "source": source,
            "risk": "unknown",
            "source_path": skill_path,
            "source_dir": source_dir,
            "installed": False,
            "size_kb": 0,
        }

        try:
            record["size_kb"] = round(os.path.getsize(skill_md) / 1024, 1)
        except OSError:
            pass

        self.index.append(record)
        self._by_id[skill_id] = record

    # ── Searching ────────────────────────────────────────────────

    def search(self, query: str, category: str | None = None, limit: int = 20) -> list[dict]:
        """Fuzzy search by name/description with optional category filter."""
        if not query and not category:
            # No filter — return first N
            return self.index[:limit]

        query_words = set(re.findall(r"\w+", query.lower())) if query else set()
        results: list[tuple[float, dict]] = []

        for entry in self.index:
            if category and entry["category"] != category:
                continue

            if not query_words:
                results.append((0.0, entry))
                continue

            score = 0.0
            name_words = set(re.findall(r"\w+", entry["name"].lower()))
            desc_words = set(re.findall(r"\w+", entry["description"].lower()))

            # Exact id match
            if query.lower().replace(" ", "-") == entry["id"]:
                score += 10.0

            # Name word overlap (high weight)
            name_overlap = query_words & name_words
            score += len(name_overlap) * 3.0

            # Description word overlap
            desc_overlap = query_words & desc_words
            score += len(desc_overlap) * 1.0

            # Substring match in name
            if query.lower() in entry["name"].lower():
                score += 5.0

            # Substring match in description
            if query.lower() in entry["description"].lower():
                score += 2.0

            if score > 0:
                results.append((score, entry))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    def list_categories(self) -> list[dict]:
        """Return categories with counts, sorted by count descending."""
        cats: dict[str, int] = {}
        for entry in self.index:
            c = entry.get("category", "general")
            cats[c] = cats.get(c, 0) + 1

        return [
            {"category": c, "count": n}
            for c, n in sorted(cats.items(), key=lambda x: -x[1])
        ]

    def get_by_id(self, skill_id: str) -> dict | None:
        """Get a catalog entry by ID."""
        return self._by_id.get(skill_id)

    def get_skill_detail(self, skill_id: str) -> dict | None:
        """Return full detail for a skill including preview of SKILL.md."""
        entry = self._by_id.get(skill_id)
        if not entry:
            return None

        detail = dict(entry)

        # Read first 500 chars of SKILL.md for preview
        skill_md = os.path.join(entry["source_path"], "SKILL.md")
        if os.path.exists(skill_md):
            try:
                with open(skill_md, encoding="utf-8", errors="replace") as f:
                    content = f.read(1000)
                # Strip frontmatter for preview
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end != -1:
                        content = content[end + 3:].strip()
                detail["preview"] = content[:500]
            except OSError:
                detail["preview"] = ""
        else:
            detail["preview"] = ""

        # List supporting files
        try:
            files = os.listdir(entry["source_path"])
            detail["files"] = [f for f in files if f != "SKILL.md"]
        except OSError:
            detail["files"] = []

        return detail

    def get_skill_content(self, skill_id: str) -> str:
        """Return full SKILL.md content for a skill."""
        entry = self._by_id.get(skill_id)
        if not entry:
            return ""

        skill_md = os.path.join(entry["source_path"], "SKILL.md")
        if os.path.exists(skill_md):
            try:
                with open(skill_md, encoding="utf-8", errors="replace") as f:
                    return f.read()
            except OSError:
                pass
        return ""

    def refresh_installed(self) -> None:
        """Re-check which catalog skills are installed."""
        if not self.installed_dir or not os.path.isdir(self.installed_dir):
            return
        installed_ids = set(os.listdir(self.installed_dir))
        for entry in self.index:
            entry["installed"] = entry["id"] in installed_ids
