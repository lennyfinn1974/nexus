#!/usr/bin/env python3
"""Quick test script for new plugins."""

import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from plugins.macos_plugin import MacOSPlugin
from plugins.brave_browser_plugin import BraveBrowserPlugin
from plugins.terminal_plugin import TerminalPlugin


async def test_macos_plugin():
    print("\n🖥️  Testing macOS Plugin...")
    print("-" * 50)

    plugin = MacOSPlugin(None, None, None)
    await plugin.setup()
    plugin.register_tools()
    plugin.register_commands()

    print(f"✅ Plugin: {plugin.name} v{plugin.version}")
    print(f"   Tools: {len(plugin.tools)}")
    print(f"   Commands: {len(plugin.commands)}")
    print(f"   Tool names: {', '.join([t.name for t in plugin.tools[:5]])}...")

    # Test a simple tool
    print("\n🧪 Testing macos_clipboard_get...")
    result = await plugin._macos_clipboard_get({})
    print(f"   Result: {result[:80]}..." if len(result) > 80 else f"   Result: {result}")

    return True


async def test_brave_plugin():
    print("\n🌐 Testing Brave Browser Plugin...")
    print("-" * 50)

    plugin = BraveBrowserPlugin(None, None, None)
    await plugin.setup()
    plugin.register_tools()
    plugin.register_commands()

    print(f"✅ Plugin: {plugin.name} v{plugin.version}")
    print(f"   Tools: {len(plugin.tools)}")
    print(f"   Commands: {len(plugin.commands)}")
    print(f"   Tool names: {', '.join([t.name for t in plugin.tools[:5]])}...")

    # Test checking if Brave is running
    print("\n🧪 Testing brave_get_url...")
    result = await plugin._brave_get_url({})
    print(f"   Result: {result}")

    return True


async def test_terminal_plugin():
    print("\n💻 Testing Terminal Plugin...")
    print("-" * 50)

    plugin = TerminalPlugin(None, None, None)
    await plugin.setup()
    plugin.register_tools()
    plugin.register_commands()

    print(f"✅ Plugin: {plugin.name} v{plugin.version}")
    print(f"   Tools: {len(plugin.tools)}")
    print(f"   Commands: {len(plugin.commands)}")
    print(f"   Tool names: {', '.join([t.name for t in plugin.tools[:5]])}...")

    # Test listing tmux sessions
    print("\n🧪 Testing tmux_list_sessions...")
    result = await plugin._tmux_list_sessions({})
    print(f"   Result: {result[:80]}..." if len(result) > 80 else f"   Result: {result}")

    return True


async def main():
    print("\n" + "=" * 50)
    print("NEXUS PLUGIN TEST SUITE")
    print("=" * 50)

    results = []

    try:
        results.append(await test_macos_plugin())
    except Exception as e:
        print(f"❌ macOS Plugin failed: {e}")
        results.append(False)

    try:
        results.append(await test_brave_plugin())
    except Exception as e:
        print(f"❌ Brave Plugin failed: {e}")
        results.append(False)

    try:
        results.append(await test_terminal_plugin())
    except Exception as e:
        print(f"❌ Terminal Plugin failed: {e}")
        results.append(False)

    print("\n" + "=" * 50)
    print(f"TEST RESULTS: {sum(results)}/{len(results)} passed")
    print("=" * 50 + "\n")

    return all(results)


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
