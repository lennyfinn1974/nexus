#!/usr/bin/env python3
"""Test script for Self-Improvement Engine."""
import asyncio
import sys
sys.path.insert(0, '/Users/lennyfinn/Nexus/backend')

from core.self_improve import SelfImprovementEngine

class MockDB:
    """Mock database for testing."""
    async def execute(self, query, params):
        class MockCursor:
            async def fetchall(self):
                return []
        return MockCursor()

class MockSkillsEngine:
    """Mock skills engine for testing."""
    pass

class MockConfig:
    """Mock config for testing."""
    pass

async def test_self_improvement_engine():
    """Test the Self-Improvement Engine."""
    print("=" * 60)
    print("Testing Self-Improvement Engine")
    print("=" * 60)

    # Initialize engine
    db = MockDB()
    skills_engine = MockSkillsEngine()
    config = MockConfig()

    engine = SelfImprovementEngine(db, skills_engine, config)

    print("\n1. Testing analyze_skill_performance()...")
    skill_analysis = await engine.analyze_skill_performance(days=7)
    print(f"   ✅ Analyzed {len(skill_analysis)} skills")
    if skill_analysis:
        for skill in skill_analysis[:3]:
            print(f"   - {skill['skill_id']}: {skill['usage_count']} uses, "
                  f"{skill['success_rate']:.1%} success")

    print("\n2. Testing analyze_tool_failures()...")
    failure_analysis = await engine.analyze_tool_failures(days=7)
    print(f"   ✅ Found {len(failure_analysis)} error patterns")
    if failure_analysis:
        for failure in failure_analysis[:3]:
            print(f"   - {failure['tool_name']}: {failure['error_type']} "
                  f"({failure['count']} times)")

    print("\n3. Testing generate_improvement_report()...")
    report = await engine.generate_improvement_report(days=7)
    print(f"   ✅ Generated report ({len(report)} chars)")
    print("\n   Report preview:")
    print("   " + "-" * 56)
    for line in report.split('\n')[:15]:
        print(f"   {line}")
    print("   " + "-" * 56)

    print("\n4. Testing helper methods...")

    # Test skill mention extraction
    test_content = "Using skill: research for data analysis"
    mentions = engine._extract_skill_mentions(test_content)
    print(f"   ✅ Extract skill mentions: {mentions}")

    # Test error classification
    test_errors = [
        "Connection timeout error occurred",
        "File not found: /path/to/file",
        "Permission denied accessing resource",
        "Invalid input format provided"
    ]
    for error in test_errors:
        error_type = engine._classify_error(error)
        print(f"   ✅ Classify '{error[:30]}...': {error_type}")

    # Test suggestion generation
    suggestion = engine._generate_skill_suggestion("test-skill", 25, 0.85)
    print(f"   ✅ Skill suggestion: {suggestion}")

    failure_suggestion = engine._generate_failure_suggestion("test_tool", "timeout", 5)
    print(f"   ✅ Failure suggestion: {failure_suggestion}")

    print("\n" + "=" * 60)
    print("✅ Self-Improvement Engine Test Complete")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_self_improvement_engine())
