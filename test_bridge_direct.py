#!/usr/bin/env python3
"""Test Nexus OpenClaw Bridge directly by invoking skill actions"""

import asyncio
import sys
import os

# Add the backend directory to path
sys.path.insert(0, '/Users/lennyfinn/Downloads/nexus/backend')

# Import the required modules
import aiosqlite
from config_manager import ConfigManager
from skills.engine import SkillsEngine

async def test_bridge():
    print("🧪 Testing Nexus → Aries Bridge Communication...")
    
    try:
        # Initialize encryption first
        from storage.encryption import init as init_encryption
        base_dir = "/Users/lennyfinn/Downloads/nexus"
        init_encryption(base_dir)
        
        # Initialize config manager
        db_path = "/Users/lennyfinn/Downloads/nexus/data/nexus.db"
        config = ConfigManager(db_path, base_dir)
        await config.connect()
        
        # Initialize database connection for skills
        db = await aiosqlite.connect(db_path)
        
        # Initialize skills engine
        skills_dir = "/Users/lennyfinn/Downloads/nexus/skills"
        engine = SkillsEngine(skills_dir, db, config)
        await engine.load_all()
        
        print(f"✅ Loaded {len(engine.skills)} skills")
        
        # Find the OpenClaw Bridge skill
        bridge_skill = engine.skills.get("openclaw-bridge")
        if not bridge_skill:
            print("❌ OpenClaw Bridge skill not found!")
            return
            
        print(f"✅ Found OpenClaw Bridge skill: {bridge_skill.name}")
        print(f"✅ Bridge configured: {bridge_skill.is_configured(config)}")
        
        # Test sending a message
        if bridge_skill.actions:
            send_action = None
            for action in bridge_skill.actions:
                if action.name == "send_to_aries":
                    send_action = action
                    break
            
            if send_action:
                print("🚀 Testing send_to_aries action...")
                params = {
                    "message": "🤖 SUCCESS! Bridge communication working perfectly from Nexus to Aries! The partnership is LIVE! 🚀",
                    "priority": "high"
                }
                
                result = await send_action.handler(params, config)
                print(f"📤 Bridge Test Result: {result}")
            else:
                print("❌ send_to_aries action not found")
        else:
            print("❌ No actions loaded for OpenClaw Bridge")
            
        # Cleanup
        await db.close()
        await config.close()
        
    except Exception as e:
        print(f"❌ Bridge test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_bridge())