#!/usr/bin/env python3
"""Detailed tests for new plugins."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from plugins.macos_plugin import MacOSPlugin
from plugins.brave_browser_plugin import BraveBrowserPlugin
from plugins.terminal_plugin import TerminalPlugin


async def test_macos_detailed():
    print("\n🖥️  macOS Plugin - Detailed Tests")
    print("=" * 60)

    plugin = MacOSPlugin(None, None, None)
    await plugin.setup()
    plugin.register_tools()

    tests = [
        ("Get clipboard", plugin._macos_clipboard_get, {}),
        ("File info on current dir", plugin._file_info, {"path": "."}),
        ("List current directory", plugin._file_find, {"pattern": "*.py", "path": "."}),
    ]

    for name, func, params in tests:
        print(f"\n🧪 {name}:")
        try:
            result = await func(params)
            print(f"   {result[:100]}..." if len(result) > 100 else f"   {result}")
        except Exception as e:
            print(f"   ❌ Error: {e}")


async def test_terminal_detailed():
    print("\n\n💻 Terminal Plugin - Detailed Tests")
    print("=" * 60)

    plugin = TerminalPlugin(None, None, None)
    await plugin.setup()
    plugin.register_tools()

    tests = [
        ("List tmux sessions", plugin._tmux_list_sessions, {}),
        ("List Terminal windows", plugin._terminal_list_windows, {}),
    ]

    for name, func, params in tests:
        print(f"\n🧪 {name}:")
        try:
            result = await func(params)
            print(f"   {result[:200]}..." if len(result) > 200 else f"   {result}")
        except Exception as e:
            print(f"   ❌ Error: {e}")


async def test_brave_detailed():
    print("\n\n🌐 Brave Browser Plugin - Detailed Tests")
    print("=" * 60)

    plugin = BraveBrowserPlugin(None, None, None)
    await plugin.setup()
    plugin.register_tools()

    print("\n🧪 Opening Brave with test URL:")
    try:
        result = await plugin._brave_open({"url": "https://example.com"})
        print(f"   {result}")
        await asyncio.sleep(2)  # Wait for page to load

        print("\n🧪 Getting current URL:")
        result = await plugin._brave_get_url({})
        print(f"   {result}")

        print("\n🧪 Getting page title:")
        result = await plugin._brave_get_title({})
        print(f"   {result}")

        print("\n🧪 Listing tabs:")
        result = await plugin._brave_get_tabs({})
        print(f"   {result[:200]}..." if len(result) > 200 else f"   {result}")

    except Exception as e:
        print(f"   ⚠️  Brave not running or error: {e}")


async def main():
    print("\n" + "=" * 60)
    print("NEXUS PLUGINS - DETAILED FUNCTIONALITY TESTS")
    print("=" * 60)

    await test_macos_detailed()
    await test_terminal_detailed()
    await test_brave_detailed()

    print("\n" + "=" * 60)
    print("DETAILED TESTS COMPLETE")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
