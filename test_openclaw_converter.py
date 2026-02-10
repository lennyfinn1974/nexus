#!/usr/bin/env python3
"""Test script for OpenClaw Converter."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, '/Users/lennyfinn/Nexus/backend')

from tools.openclaw_converter import convert_openclaw_extension

async def test_openclaw_converter():
    """Test the OpenClaw converter with a mock extension."""
    print("=" * 60)
    print("Testing OpenClaw Converter")
    print("=" * 60)

    # Create a mock OpenClaw extension
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "test-extension"
        ext_dir.mkdir()

        # Create openclaw.plugin.json
        plugin_json = {
            "id": "test-skill",
            "name": "Test Skill Extension",
            "displayName": "Test Skill",
            "description": "A test OpenClaw extension for demonstration",
            "version": "1.0.0",
            "category": "productivity"
        }
        (ext_dir / "openclaw.plugin.json").write_text(json.dumps(plugin_json, indent=2))

        # Create README.md
        readme = """# Test Skill Extension

This is a demonstration extension for testing the OpenClaw converter.

## Features
- Feature 1: Does something cool
- Feature 2: Does something else cool

## Usage
Use this skill to test the conversion process.
"""
        (ext_dir / "README.md").write_text(readme)

        # Create index.ts with some functions
        index_ts = """
export async function testTool(param: string): Promise<string> {
    return "Test result: " + param;
}

export async function anotherTool(value: number): Promise<number> {
    return value * 2;
}

export function helperFunction() {
    // Internal helper
}

export { testTool, anotherTool };
"""
        (ext_dir / "index.ts").write_text(index_ts)

        # Run conversion
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        print("\n1. Converting OpenClaw extension...")
        print(f"   Extension path: {ext_dir}")
        print(f"   Output dir: {output_dir}")

        result = await convert_openclaw_extension(str(ext_dir), str(output_dir))

        print("\n2. Conversion result:")
        print(f"   ✅ Skill ID: {result['skill_id']}")
        print(f"   ✅ Name: {result['name']}")
        print(f"   ✅ Files created: {len(result['files_created'])}")

        print("\n3. Generated files:")
        for file_path in result['files_created']:
            print(f"   📄 {Path(file_path).name}")

        # Show generated content
        skill_dir = output_dir / result['skill_id']

        print("\n4. skill.yaml content:")
        print("-" * 60)
        print((skill_dir / "skill.yaml").read_text())

        print("\n5. knowledge.md content:")
        print("-" * 60)
        print((skill_dir / "knowledge.md").read_text()[:300] + "...")

        print("\n6. actions.py content:")
        print("-" * 60)
        print((skill_dir / "actions.py").read_text()[:500] + "...")

    print("\n" + "=" * 60)
    print("✅ OpenClaw Converter Test Complete")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_openclaw_converter())
