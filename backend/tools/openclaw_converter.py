"""OpenClaw Extension Converter - Convert OpenClaw extensions to Nexus skill packs.

Reads OpenClaw extension metadata and generates Nexus-compatible skill.yaml,
knowledge.md, and actions.py files.
"""

import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger("nexus.tools.openclaw_converter")


async def convert_openclaw_extension(extension_path: str, output_dir: str) -> dict:
    """Convert an OpenClaw extension to a Nexus skill pack.

    Args:
        extension_path: Path to OpenClaw extension directory
        output_dir: Output directory for generated skill pack

    Returns:
        dict with skill_id, name, files_created
    """
    ext_path = Path(extension_path).resolve()
    out_path = Path(output_dir).resolve()

    if not ext_path.exists() or not ext_path.is_dir():
        raise ValueError(f"Extension path does not exist: {extension_path}")

    # Read metadata from openclaw.plugin.json or package.json
    metadata = await _read_extension_metadata(ext_path)
    if not metadata:
        raise ValueError("No valid metadata found (openclaw.plugin.json or package.json)")

    # Extract skill info
    skill_id = metadata.get("id") or metadata.get("name", "").lower().replace(" ", "-")
    skill_name = metadata.get("displayName") or metadata.get("name", skill_id)
    skill_description = metadata.get("description", "")
    skill_version = metadata.get("version", "1.0.0")
    skill_domain = metadata.get("category") or metadata.get("domain", "general")

    # Read README for knowledge content
    knowledge_content = await _read_readme(ext_path)

    # Parse exported tools from index.ts
    tools = await _parse_extension_tools(ext_path)

    # Generate skill.yaml
    skill_yaml = _generate_skill_yaml(
        skill_id=skill_id,
        name=skill_name,
        description=skill_description,
        version=skill_version,
        domain=skill_domain,
        tools=tools,
    )

    # Generate knowledge.md
    knowledge_md = _generate_knowledge_md(
        name=skill_name,
        description=skill_description,
        readme_content=knowledge_content,
    )

    # Generate actions.py with stub functions
    actions_py = _generate_actions_py(skill_id=skill_id, tools=tools)

    # Create output directory
    skill_dir = out_path / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Write files
    files_created = []

    skill_yaml_path = skill_dir / "skill.yaml"
    skill_yaml_path.write_text(skill_yaml)
    files_created.append(str(skill_yaml_path))

    knowledge_md_path = skill_dir / "knowledge.md"
    knowledge_md_path.write_text(knowledge_md)
    files_created.append(str(knowledge_md_path))

    if tools:
        actions_py_path = skill_dir / "actions.py"
        actions_py_path.write_text(actions_py)
        files_created.append(str(actions_py_path))

    logger.info(f"✅ Converted {skill_name} to {skill_dir}")

    return {
        "skill_id": skill_id,
        "name": skill_name,
        "files_created": files_created,
    }


async def _read_extension_metadata(ext_path: Path) -> Optional[Dict]:
    """Read extension metadata from openclaw.plugin.json or package.json."""
    # Try openclaw.plugin.json first
    plugin_json = ext_path / "openclaw.plugin.json"
    if plugin_json.exists():
        try:
            with open(plugin_json) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read openclaw.plugin.json: {e}")

    # Fallback to package.json
    package_json = ext_path / "package.json"
    if package_json.exists():
        try:
            with open(package_json) as f:
                pkg_data = json.load(f)
                # Extract relevant fields
                return {
                    "id": pkg_data.get("name", "").replace("@", "").replace("/", "-"),
                    "name": pkg_data.get("name", ""),
                    "displayName": pkg_data.get("displayName") or pkg_data.get("name"),
                    "description": pkg_data.get("description", ""),
                    "version": pkg_data.get("version", "1.0.0"),
                    "category": pkg_data.get("category", "general"),
                }
        except Exception as e:
            logger.warning(f"Failed to read package.json: {e}")

    return None


async def _read_readme(ext_path: Path) -> str:
    """Read README.md content."""
    readme_path = ext_path / "README.md"
    if readme_path.exists():
        try:
            return readme_path.read_text()
        except Exception as e:
            logger.warning(f"Failed to read README.md: {e}")

    return ""


async def _parse_extension_tools(ext_path: Path) -> List[Dict]:
    """Parse tool definitions from index.ts or similar entry points."""
    tools = []

    # Look for index.ts, extension.ts, or main.ts
    entry_files = ["index.ts", "extension.ts", "src/index.ts", "src/extension.ts", "main.ts"]

    for entry_file in entry_files:
        entry_path = ext_path / entry_file
        if entry_path.exists():
            try:
                content = entry_path.read_text()

                # Parse function exports (basic regex pattern)
                # Match: export function toolName(...) or export async function toolName(...)
                function_pattern = r'export\s+(?:async\s+)?function\s+(\w+)\s*\('
                matches = re.finditer(function_pattern, content)

                for match in matches:
                    tool_name = match.group(1)
                    tools.append({
                        "name": tool_name,
                        "description": f"Tool from OpenClaw extension: {tool_name}",
                        "parameters": {},
                    })

                # Also match: export { tool1, tool2 }
                export_pattern = r'export\s*\{\s*([^}]+)\s*\}'
                export_matches = re.finditer(export_pattern, content)

                for match in export_matches:
                    exports = match.group(1).split(",")
                    for exp in exports:
                        exp_name = exp.strip().split()[0]  # Handle 'name as alias'
                        if exp_name and exp_name not in [t["name"] for t in tools]:
                            tools.append({
                                "name": exp_name,
                                "description": f"Tool from OpenClaw extension: {exp_name}",
                                "parameters": {},
                            })

                break  # Found entry file, stop searching

            except Exception as e:
                logger.warning(f"Failed to parse {entry_file}: {e}")

    return tools


def _generate_skill_yaml(
    skill_id: str,
    name: str,
    description: str,
    version: str,
    domain: str,
    tools: List[Dict],
) -> str:
    """Generate skill.yaml content."""
    skill_data = {
        "id": skill_id,
        "name": name,
        "type": "integration" if tools else "knowledge",
        "version": version,
        "domain": domain,
        "description": description,
        "config": {
            "schema": {
                "enabled": {
                    "type": "boolean",
                    "default": True,
                    "description": "Enable this skill",
                }
            }
        },
    }

    # Add actions if tools were found
    if tools:
        skill_data["actions"] = []
        for tool in tools:
            skill_data["actions"].append({
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get("parameters", {}),
            })

    return yaml.dump(skill_data, default_flow_style=False, sort_keys=False)


def _generate_knowledge_md(name: str, description: str, readme_content: str) -> str:
    """Generate knowledge.md content."""
    lines = [
        f"# {name}\n",
        f"{description}\n",
    ]

    if readme_content:
        lines.append("## Extension Documentation\n")
        lines.append(readme_content)
    else:
        lines.append("## Overview\n")
        lines.append(f"This skill was converted from an OpenClaw extension.\n")

    return "\n".join(lines)


def _generate_actions_py(skill_id: str, tools: List[Dict]) -> str:
    """Generate actions.py with stub async functions."""
    lines = [
        f'"""Actions for {skill_id} skill - converted from OpenClaw extension."""\n',
        "import logging\n",
        f'logger = logging.getLogger("nexus.skills.{skill_id}")\n\n',
    ]

    if not tools:
        lines.append("# No tools found in extension\n")
    else:
        for tool in tools:
            tool_name = tool["name"]
            params = tool.get("parameters", {})

            # Generate function signature
            if params:
                param_list = ", ".join([f"{k}: str" for k in params.keys()])
                lines.append(f"async def {tool_name}({param_list}) -> dict:\n")
            else:
                lines.append(f"async def {tool_name}() -> dict:\n")

            # Generate docstring
            lines.append(f'    """{tool["description"]}\n')
            if params:
                lines.append("\n    Args:\n")
                for param_name, param_info in params.items():
                    lines.append(f"        {param_name}: {param_info}\n")
            lines.append('\n    Returns:\n')
            lines.append('        dict: Result with status and data\n')
            lines.append('    """\n')

            # Generate stub implementation
            lines.append(f'    logger.info(f"Executing {tool_name}")\n')
            lines.append("    # TODO: Implement OpenClaw extension functionality\n")
            lines.append('    return {\n')
            lines.append('        "status": "success",\n')
            lines.append(f'        "message": "{tool_name} executed (stub implementation)",\n')
            lines.append('        "data": None,\n')
            lines.append('    }\n\n')

    return "".join(lines)


# ────────────────────────────────────────────
# CLI Mode
# ────────────────────────────────────────────

def main():
    """CLI entry point for converter."""
    parser = argparse.ArgumentParser(
        description="Convert OpenClaw extensions to Nexus skill packs"
    )
    parser.add_argument(
        "extension_path",
        help="Path to OpenClaw extension directory",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="./data/skills",
        help="Output directory for skill pack (default: ./data/skills)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Run conversion
    try:
        result = asyncio.run(convert_openclaw_extension(args.extension_path, args.output))

        print(f"\n✅ Conversion successful!")
        print(f"   Skill ID: {result['skill_id']}")
        print(f"   Name: {result['name']}")
        print(f"\n📁 Files created:")
        for file_path in result["files_created"]:
            print(f"   - {file_path}")

    except Exception as e:
        print(f"\n❌ Conversion failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
