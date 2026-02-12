"""Nexus Skills CLI — browse, search, install anti-gravity skills.

Standalone CLI that works without the full server running.

Usage:
    nexus.sh skills search <query>        Search the skill catalog
    nexus.sh skills categories            List skill categories
    nexus.sh skills info <skill-id>       Show skill details
    nexus.sh skills install <skill-id>    Install a skill (can list multiple)
    nexus.sh skills list                  Show installed skills
    nexus.sh skills sync                  Re-scan catalog sources
    nexus.sh skills stats                 Show catalog statistics
"""

from __future__ import annotations

import json
import os
import sys

# ── Resolve paths ────────────────────────────────────────────────────
NEXUS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(NEXUS_DIR, "backend")
SKILLS_DIR = os.path.join(NEXUS_DIR, "skills")

# Well-known catalog source locations
CATALOG_SOURCES = [
    os.path.expanduser("~/antigravity-awesome-skills"),
    os.path.expanduser("~/.agent/skills"),
]


def _get_catalog():
    """Create and load a SkillCatalog instance."""
    from skills.catalog import SkillCatalog

    sources = [s for s in CATALOG_SOURCES if os.path.isdir(s)]
    if not sources:
        print("No skill catalog sources found.")
        print(f"Expected: {', '.join(CATALOG_SOURCES)}")
        sys.exit(1)

    catalog = SkillCatalog(sources=sources, installed_dir=SKILLS_DIR)
    catalog.load_index()
    return catalog


def cmd_search(args: list[str]) -> None:
    """Search the skill catalog."""
    if not args:
        print("Usage: nexus.sh skills search <query>")
        sys.exit(1)

    query = " ".join(args)
    catalog = _get_catalog()
    results = catalog.search(query, limit=15)

    if not results:
        print(f"No skills found matching '{query}'.")
        return

    print(f"\n  Found {len(results)} skill(s) matching '{query}':\n")
    for r in results:
        status = "\033[32m[installed]\033[0m" if r.get("installed") else "\033[33m[available]\033[0m"
        name = r["name"]
        desc = r.get("description", "")[:70]
        cat = r.get("category", "general")
        size = f"{r.get('size_kb', 0):.1f}KB"
        print(f"  {status} \033[1m{r['id']}\033[0m ({cat}, {size})")
        if desc:
            print(f"           {desc}{'...' if len(r.get('description', '')) > 70 else ''}")
    print(f"\n  Install: nexus.sh skills install <skill-id>")


def cmd_categories(args: list[str]) -> None:
    """List available skill categories."""
    catalog = _get_catalog()
    cats = catalog.list_categories()

    if not cats:
        print("No categories found.")
        return

    total = sum(c["count"] for c in cats)
    print(f"\n  Skill Catalog — {total} skills in {len(cats)} categories:\n")
    for c in cats:
        bar = "#" * min(c["count"] // 10, 40)
        print(f"  {c['category']:25s} {c['count']:4d} skills  {bar}")


def cmd_info(args: list[str]) -> None:
    """Show details for a specific skill."""
    if not args:
        print("Usage: nexus.sh skills info <skill-id>")
        sys.exit(1)

    skill_id = args[0]
    catalog = _get_catalog()
    detail = catalog.get_skill_detail(skill_id)

    if not detail:
        print(f"Skill '{skill_id}' not found. Try: nexus.sh skills search <query>")
        sys.exit(1)

    status = "\033[32mInstalled\033[0m" if detail.get("installed") else "\033[33mAvailable\033[0m"
    print(f"\n  \033[1m{detail['name']}\033[0m ({status})")
    print(f"  ID:       {detail['id']}")
    print(f"  Category: {detail.get('category', 'general')}")
    print(f"  Source:   {detail.get('source', 'unknown')}")
    print(f"  Size:     {detail.get('size_kb', 0)} KB")

    if detail.get("description"):
        print(f"\n  {detail['description']}")

    if detail.get("preview"):
        print(f"\n  --- Preview ---")
        for line in detail["preview"].split("\n")[:10]:
            print(f"  {line}")
        if len(detail["preview"].split("\n")) > 10:
            print(f"  ...")

    if detail.get("files"):
        print(f"\n  Supporting files: {', '.join(detail['files'])}")

    if not detail.get("installed"):
        print(f"\n  Install: nexus.sh skills install {detail['id']}")


def cmd_install(args: list[str]) -> None:
    """Install one or more skills from the catalog."""
    if not args:
        print("Usage: nexus.sh skills install <skill-id> [skill-id ...]")
        sys.exit(1)

    from skills.converter import convert_antigravity_skill

    catalog = _get_catalog()
    os.makedirs(SKILLS_DIR, exist_ok=True)

    installed = 0
    for skill_id in args:
        entry = catalog.get_by_id(skill_id)
        if not entry:
            print(f"  \033[31m[error]\033[0m Skill '{skill_id}' not found in catalog.")
            continue
        if entry.get("installed"):
            print(f"  \033[33m[skip]\033[0m  {entry['name']} already installed.")
            continue

        try:
            dest_dir = os.path.join(SKILLS_DIR, skill_id)
            manifest = convert_antigravity_skill(
                source_dir=entry["source_path"],
                dest_dir=dest_dir,
                category=entry.get("category", "general"),
                skill_id=skill_id,
            )
            keywords = ", ".join(manifest.get("triggers", {}).get("keywords", [])[:5])
            print(f"  \033[32m[installed]\033[0m \033[1m{manifest['name']}\033[0m")
            print(f"              Domain: {manifest.get('domain', 'general')}")
            print(f"              Keywords: {keywords}")
            installed += 1
        except Exception as e:
            print(f"  \033[31m[error]\033[0m Failed to install '{skill_id}': {e}")

    if installed > 0:
        print(f"\n  Installed {installed} skill(s).")
        print(f"  Restart Nexus to activate: nexus.sh restart")
    else:
        print("\n  No new skills installed.")


def cmd_list(args: list[str]) -> None:
    """List installed skills."""
    if not os.path.isdir(SKILLS_DIR):
        print("No skills installed.")
        return

    import yaml

    skills = []
    for item in sorted(os.listdir(SKILLS_DIR)):
        skill_dir = os.path.join(SKILLS_DIR, item)
        if not os.path.isdir(skill_dir):
            continue
        manifest_path = os.path.join(skill_dir, "skill.yaml")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path) as f:
                    m = yaml.safe_load(f) or {}
                skills.append({
                    "id": item,
                    "name": m.get("name", item),
                    "type": m.get("type", "unknown"),
                    "domain": m.get("domain", "general"),
                })
            except Exception:
                skills.append({"id": item, "name": item, "type": "unknown", "domain": "general"})
        else:
            skills.append({"id": item, "name": item, "type": "unknown", "domain": "general"})

    if not skills:
        print("No skills installed.")
        return

    print(f"\n  Installed Skills ({len(skills)}):\n")
    for s in skills:
        print(f"  \033[1m{s['id']:30s}\033[0m {s['type']:12s} {s['domain']}")
    print(f"\n  Skills directory: {SKILLS_DIR}")


def cmd_sync(args: list[str]) -> None:
    """Re-scan catalog sources and update the index."""
    catalog = _get_catalog()
    print(f"\n  Catalog synced: {len(catalog.index)} skills indexed")
    cats = catalog.list_categories()
    installed = sum(1 for e in catalog.index if e.get("installed"))
    print(f"  Installed: {installed}")
    print(f"  Categories: {len(cats)}")
    for c in cats[:5]:
        print(f"    {c['category']}: {c['count']}")
    if len(cats) > 5:
        print(f"    ... and {len(cats) - 5} more")


def cmd_stats(args: list[str]) -> None:
    """Show catalog statistics."""
    catalog = _get_catalog()
    cats = catalog.list_categories()
    installed = sum(1 for e in catalog.index if e.get("installed"))
    total_size = sum(e.get("size_kb", 0) for e in catalog.index)

    print(f"\n  Skill Catalog Statistics")
    print(f"  {'─' * 40}")
    print(f"  Total skills:     {len(catalog.index)}")
    print(f"  Installed:        {installed}")
    print(f"  Available:        {len(catalog.index) - installed}")
    print(f"  Categories:       {len(cats)}")
    print(f"  Total size:       {total_size / 1024:.1f} MB")
    print(f"  Sources:          {len(catalog.sources)}")
    for s in catalog.sources:
        print(f"    - {s}")


COMMANDS = {
    "search": cmd_search,
    "categories": cmd_categories,
    "info": cmd_info,
    "install": cmd_install,
    "list": cmd_list,
    "sync": cmd_sync,
    "stats": cmd_stats,
}


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(COMMANDS.keys())}")
        sys.exit(1)

    COMMANDS[cmd](args[1:])


if __name__ == "__main__":
    main()
