"""Convert external skill formats (anti-gravity SKILL.md) to Nexus format.

Anti-gravity skills:  SKILL.md (YAML frontmatter + markdown body)
Nexus skills:         skill.yaml (manifest) + knowledge.md (content)

The converter reads the source, generates a proper Nexus manifest with
auto-extracted keywords and triggers, and writes the converted files
to the destination directory.
"""

from __future__ import annotations

import logging
import os
import re
import shutil

import yaml

logger = logging.getLogger("nexus.skills.converter")

# Common stopwords to filter from auto-generated keywords
_STOPWORDS = frozenset(
    "a an the and or but in on at to for of is it this that with from by as be"
    " are was were been have has had do does did will would shall should may might"
    " can could use when how what which who whom whose where why not no nor"
    " your you i my me we our they them their its also very just more most"
    " about into through during before after above below between any all each"
    " such only other than too out up down over then so if because while".split()
)


def _extract_keywords(name: str, description: str, max_keywords: int = 10) -> list[str]:
    """Generate trigger keywords from skill name and description.

    Strategy:
    1. Split name on hyphens → individual words (high value)
    2. Take meaningful words from description (skip stopwords)
    3. Deduplicate, cap at max_keywords
    """
    keywords: list[str] = []

    # Name words (high value — always include)
    name_words = [w.lower() for w in re.findall(r"[a-zA-Z]+", name) if len(w) > 2]
    keywords.extend(name_words)

    # Full name as multi-word keyword (if multi-word)
    clean_name = name.replace("-", " ").strip()
    if " " in clean_name:
        keywords.append(clean_name.lower())

    # Description words (skip stopwords, short words)
    desc_words = re.findall(r"[a-zA-Z]+", description.lower())
    for w in desc_words:
        if len(w) > 3 and w not in _STOPWORDS and w not in keywords:
            keywords.append(w)
            if len(keywords) >= max_keywords:
                break

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)

    return unique[:max_keywords]


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from SKILL.md content.

    Returns (frontmatter_dict, body_without_frontmatter).
    """
    if not content.startswith("---"):
        return {}, content

    end = content.find("---", 3)
    if end == -1:
        return {}, content

    try:
        fm = yaml.safe_load(content[3:end]) or {}
    except yaml.YAMLError:
        fm = {}

    body = content[end + 3:].strip()
    return fm, body


def convert_antigravity_skill(
    source_dir: str,
    dest_dir: str,
    category: str = "general",
    skill_id: str | None = None,
) -> dict:
    """Convert a single anti-gravity skill to Nexus format.

    Parameters
    ----------
    source_dir : str
        Path to the anti-gravity skill directory (contains SKILL.md).
    dest_dir : str
        Path where the Nexus skill directory will be created.
    category : str
        Category from the catalog index.
    skill_id : str, optional
        Override skill ID (defaults to directory name).

    Returns
    -------
    dict
        The generated manifest.
    """
    skill_md_path = os.path.join(source_dir, "SKILL.md")
    if not os.path.exists(skill_md_path):
        raise FileNotFoundError(f"No SKILL.md in {source_dir}")

    # Read source
    with open(skill_md_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Parse frontmatter
    fm, body = _parse_frontmatter(content)
    if not skill_id:
        skill_id = os.path.basename(source_dir)

    name = fm.get("name", skill_id)
    description = fm.get("description", "").strip()
    source = fm.get("source", "antigravity")

    # If description is very long (some anti-gravity skills have multi-line),
    # truncate for the manifest but keep full in knowledge
    manifest_desc = description[:200] if len(description) > 200 else description

    # Generate keywords
    keywords = _extract_keywords(name, description)

    # Build Nexus manifest
    manifest = {
        "id": skill_id,
        "name": name,
        "type": "knowledge",
        "version": "1.0",
        "domain": category,
        "description": manifest_desc,
        "author": source if source != "unknown" else "antigravity",
        "triggers": {
            "keywords": keywords,
        },
    }

    # Create destination directory
    os.makedirs(dest_dir, exist_ok=True)

    # Write skill.yaml
    with open(os.path.join(dest_dir, "skill.yaml"), "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, allow_unicode=True)

    # Write knowledge.md (body without frontmatter)
    with open(os.path.join(dest_dir, "knowledge.md"), "w") as f:
        f.write(body)

    # Copy supporting directories if they exist
    for subdir in ("resources", "references", "scripts", "examples", "templates"):
        src = os.path.join(source_dir, subdir)
        if os.path.isdir(src):
            dst = os.path.join(dest_dir, subdir)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    logger.info(f"Converted skill: {name} ({skill_id}) → {dest_dir}")
    return manifest
