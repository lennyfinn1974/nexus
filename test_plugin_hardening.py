#!/usr/bin/env python3
"""Test suite for plugin system hardening features.

Tests:
- Rate limiting (60 calls/min per tool)
- File access validation with allowed_dirs
- Execution timing and performance monitoring
- Audit trail and call count tracking
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from plugins.base import NexusPlugin, ToolInfo
from plugins.manager import PluginManager


# Mock plugin for testing
class TestPlugin(NexusPlugin):
    """Test plugin with security features."""

    name = "test_plugin"
    description = "Plugin for testing hardening features"
    version = "1.0.0"
    rate_limit = 5  # Low limit for testing (5 calls/min)
    allowed_dirs = ["/tmp", "/var/tmp"]  # Restricted directories

    def __init__(self, config, db, router):
        super().__init__(config, db, router)

    async def setup(self) -> bool:
        return True

    def register_tools(self) -> None:
        self.add_tool(
            name="test_tool",
            description="A simple test tool",
            parameters={"message": "string"},
            handler=self.tool_test_tool,
        )
        self.add_tool(
            name="file_tool",
            description="Tool that accesses files",
            parameters={"path": "string"},
            handler=self.tool_file_tool,
        )

    def register_commands(self) -> None:
        pass

    async def tool_test_tool(self, params: dict) -> str:
        """Simple test tool that returns a message."""
        message = params.get("message", "Hello")
        await asyncio.sleep(0.01)  # Simulate some work
        return f"Test tool executed: {message}"

    async def tool_file_tool(self, params: dict) -> str:
        """Tool that validates file access."""
        path = params.get("path", "")
        if not self.validate_file_access(path):
            raise PermissionError(f"Access denied to path: {path}")
        return f"Access granted to: {path}"


def print_test(name: str):
    """Print test section header."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print('='*60)


def print_result(passed: bool, message: str):
    """Print test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status}: {message}")


async def test_rate_limiting():
    """Test rate limiting functionality."""
    print_test("Rate Limiting (5 calls/min)")

    plugin = TestPlugin(None, None, None)
    await plugin.setup()
    plugin.register_tools()

    # Test 1: Should allow first 5 calls
    print("\n1. Testing rate limit allowance (first 5 calls)...")
    success_count = 0
    for i in range(5):
        allowed = plugin.check_rate_limit("test_tool")
        if allowed:
            success_count += 1
        print(f"   Call {i+1}: {'Allowed' if allowed else 'Blocked'}")

    print_result(success_count == 5, f"Allowed {success_count}/5 calls within limit")

    # Test 2: Should block 6th call
    print("\n2. Testing rate limit enforcement (6th call)...")
    blocked = not plugin.check_rate_limit("test_tool")
    print(f"   Call 6: {'Blocked' if blocked else 'Allowed'}")
    print_result(blocked, "6th call blocked by rate limiter")

    # Test 3: Different tools have separate limits
    print("\n3. Testing separate limits per tool...")
    allowed = plugin.check_rate_limit("file_tool")
    print(f"   Different tool call: {'Allowed' if allowed else 'Blocked'}")
    print_result(allowed, "Different tool has separate rate limit")

    return success_count == 5 and blocked and allowed


async def test_file_access_validation():
    """Test file access validation."""
    print_test("File Access Validation")

    plugin = TestPlugin(None, None, None)
    plugin.allowed_dirs = ["/tmp", "/var/tmp"]

    # Test 1: Allowed directory
    print("\n1. Testing allowed directory access...")
    allowed_path = "/tmp/test.txt"
    result1 = plugin.validate_file_access(allowed_path)
    print(f"   Path: {allowed_path}")
    print(f"   Result: {'Allowed' if result1 else 'Denied'}")
    print_result(result1, "Access granted to allowed directory")

    # Test 2: Disallowed directory
    print("\n2. Testing disallowed directory access...")
    disallowed_path = "/etc/passwd"
    result2 = plugin.validate_file_access(disallowed_path)
    print(f"   Path: {disallowed_path}")
    print(f"   Result: {'Allowed' if result2 else 'Denied'}")
    print_result(not result2, "Access denied to disallowed directory")

    # Test 3: Empty allowed_dirs (allow all)
    print("\n3. Testing unrestricted access (empty allowed_dirs)...")
    plugin.allowed_dirs = []
    result3 = plugin.validate_file_access("/etc/passwd")
    print(f"   Path: /etc/passwd (with no restrictions)")
    print(f"   Result: {'Allowed' if result3 else 'Denied'}")
    print_result(result3, "Access granted when no restrictions")

    # Test 4: Subdirectory access
    print("\n4. Testing subdirectory access...")
    plugin.allowed_dirs = ["/tmp"]
    subdir_path = "/tmp/subdir/file.txt"
    result4 = plugin.validate_file_access(subdir_path)
    print(f"   Path: {subdir_path}")
    print(f"   Result: {'Allowed' if result4 else 'Denied'}")
    print_result(result4, "Access granted to subdirectory")

    return result1 and not result2 and result3 and result4


async def test_timing_and_audit():
    """Test execution timing and audit tracking."""
    print_test("Execution Timing & Audit Trail")

    # Create plugin manager
    manager = PluginManager(None, None, None)
    plugin = TestPlugin(None, None, None)
    await plugin.setup()
    plugin.register_tools()
    manager.plugins[plugin.name] = plugin

    print("\n1. Testing execution timing...")
    tool_info = plugin.tools[0]
    start = time.time()
    result = await tool_info.handler({"message": "test"})
    duration_ms = (time.time() - start) * 1000
    print(f"   Tool: {tool_info.name}")
    print(f"   Result: {result}")
    print(f"   Duration: {duration_ms:.2f}ms")
    print_result(duration_ms > 0, f"Execution timing measured: {duration_ms:.2f}ms")

    print("\n2. Testing audit trail...")
    # Simulate multiple tool calls
    await manager.audit_tool_call(plugin, "test_tool", {}, result, duration_ms)
    await manager.audit_tool_call(plugin, "test_tool", {}, result, 10.5)
    await manager.audit_tool_call(plugin, "file_tool", {}, result, 5.2)

    summary = manager.get_audit_summary()
    print(f"   Audit summary: {summary}")

    test1 = summary.get("test_plugin", {}).get("test_tool") == 2
    test2 = summary.get("test_plugin", {}).get("file_tool") == 1
    print_result(test1 and test2, f"Audit tracking correct: {summary}")

    return duration_ms > 0 and test1 and test2


async def test_rate_tracker_cleanup():
    """Test that rate tracker cleans up old timestamps."""
    print_test("Rate Tracker Cleanup")

    plugin = TestPlugin(None, None, None)
    plugin.rate_limit = 100  # High limit to avoid blocking

    print("\n1. Adding timestamps and checking cleanup...")
    # Add old timestamps (>60 seconds ago)
    plugin._rate_tracker["test_tool"] = [
        time.time() - 70,  # 70 seconds ago (should be removed)
        time.time() - 65,  # 65 seconds ago (should be removed)
        time.time() - 30,  # 30 seconds ago (should be kept)
        time.time() - 10,  # 10 seconds ago (should be kept)
    ]

    print(f"   Initial tracker: {len(plugin._rate_tracker['test_tool'])} timestamps")

    # Call check_rate_limit to trigger cleanup
    plugin.check_rate_limit("test_tool")

    remaining = len(plugin._rate_tracker["test_tool"])
    print(f"   After cleanup: {remaining} timestamps (should be 3: 2 old + 1 new)")

    # Should have 3: the 2 recent ones + the new one we just added
    print_result(remaining == 3, f"Old timestamps cleaned up correctly ({remaining} remaining)")

    return remaining == 3


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("PLUGIN SYSTEM HARDENING TEST SUITE")
    print("="*60)

    results = []

    # Run tests
    results.append(await test_rate_limiting())
    results.append(await test_file_access_validation())
    results.append(await test_timing_and_audit())
    results.append(await test_rate_tracker_cleanup())

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    passed = sum(results)
    total = len(results)
    print(f"\nTests passed: {passed}/{total}")

    if passed == total:
        print("\n✅ ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n❌ {total - passed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
