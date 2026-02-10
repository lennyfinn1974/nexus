#!/usr/bin/env python3
"""Test script for Sovereign plugin."""
import asyncio
import sys
sys.path.insert(0, '/Users/lennyfinn/Nexus/backend')

from plugins.sovereign_plugin import SovereignPlugin

class MockConfig:
    pass

class MockDB:
    pass

class MockRouter:
    pass

async def test_sovereign_plugin():
    """Test the Sovereign plugin tools."""
    print("=" * 60)
    print("Testing Sovereign Plugin")
    print("=" * 60)

    # Initialize plugin
    config = MockConfig()
    db = MockDB()
    router = MockRouter()

    plugin = SovereignPlugin(config, db, router)

    # Test setup
    print("\n1. Testing setup()...")
    result = await plugin.setup()
    print(f"   Setup result: {result}")
    print(f"   Available: {plugin._available}")
    print(f"   Workspace path: {plugin._workspace_path}")

    # Register tools
    plugin.register_tools()
    plugin.register_commands()
    print(f"\n   Tools registered: {len(plugin.tools)}")
    print(f"   Commands registered: {len(plugin.commands)}")

    # Test sovereign_status
    print("\n2. Testing sovereign_status()...")
    status = await plugin._get_status({})
    print(status)

    # Test sovereign_search
    print("\n3. Testing sovereign_search()...")
    search_result = await plugin._search_workspace({
        "query": "py",
        "limit": "5"
    })
    print(search_result)

    # Test sovereign_execute
    print("\n4. Testing sovereign_execute()...")
    exec_result = await plugin._execute_command({
        "command": "SYS:STATUS"
    })
    print(exec_result)

    # Test memory save
    print("\n5. Testing sovereign_memory_save()...")
    save_result = await plugin._save_memory({
        "key": "test_memory",
        "content": "This is a test memory from Nexus",
        "tags": "test, nexus"
    })
    print(save_result)

    # Test memory load
    print("\n6. Testing sovereign_memory_load()...")
    load_result = await plugin._load_memory({
        "key": "test_memory"
    })
    print(load_result)

    # List all tools
    print("\n7. All registered tools:")
    for tool in plugin.tools:
        print(f"   - {tool.name}: {tool.description}")

    # List all commands
    print("\n8. All registered commands:")
    for cmd_name, cmd_info in plugin.commands.items():
        print(f"   - /{cmd_name}: {cmd_info['description']}")

    print("\n" + "=" * 60)
    print("✅ Sovereign Plugin Test Complete")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_sovereign_plugin())
