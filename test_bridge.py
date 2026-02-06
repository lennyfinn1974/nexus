#!/usr/bin/env python3
"""Test the OpenClaw Bridge functionality"""

import sys
import os
sys.path.append('/Users/lennyfinn/Downloads/nexus')

# Import the bridge actions directly
import importlib.util
spec = importlib.util.spec_from_file_location("bridge_actions", "/Users/lennyfinn/Downloads/nexus/skills/openclaw-bridge/actions.py")
bridge_actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_actions)

import asyncio

class MockConfigManager:
    """Mock config manager for testing"""
    def get(self, key, default=""):
        if key == "OPENCLAW_GATEWAY_URL":
            return "http://localhost:18789"
        elif key == "OPENCLAW_TOKEN":
            return "9df94ec862f0d1c64ff6e0e19efa7dd8fef90ec9b8ce63fd"
        return default

async def test_bridge():
    """Test sending a message to Aries"""
    config = MockConfigManager()
    params = {
        "message": "🔄 **NEXUS BRIDGE TEST RESPONSE** 🔄\n\nAries, I received your bridge test message successfully!\n\n✅ Message received from Aries\n✅ Processing through OpenClaw Bridge skill\n✅ Sending response back to Aries\n\n**This confirms bidirectional AI-to-AI communication is working!**\n\nReady for autonomous collaboration! What should we build together first? 🚀",
        "priority": "high"
    }
    
    try:
        result = await bridge_actions.send_to_aries(params, config)
        print("Bridge test result:", result)
    except Exception as e:
        print("Bridge test failed:", e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_bridge())