"""Self-Improvement Engine - Analyze skill performance and suggest improvements.

Monitors skill usage, success rates, tool failures, and generates
actionable improvement reports for the Nexus AI agent.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nexus.core.self_improve")


class SelfImprovementEngine:
    """Analyze agent performance and generate improvement suggestions."""

    def __init__(self, db: Any, skills_engine: Any, config: Any):
        """Initialize self-improvement engine.

        Args:
            db: Database connection for querying metrics
            skills_engine: Skills engine instance for skill metadata
            config: Configuration manager
        """
        self.db = db
        self.skills_engine = skills_engine
        self.config = config

    async def analyze_skill_performance(self, days: int = 7) -> List[Dict]:
        """Analyze skill usage patterns and success rates.

        Args:
            days: Number of days to analyze (default: 7)

        Returns:
            List of dicts with skill_id, usage_count, success_rate, suggestion
        """
        try:
            # Query skill usage from database
            cutoff_date = datetime.now() - timedelta(days=days)
            results = []

            # Get all conversations with skill usage
            conversations = await self._get_recent_conversations(cutoff_date)

            # Aggregate skill usage
            skill_stats = defaultdict(lambda: {"uses": 0, "successes": 0, "failures": 0})

            for conv in conversations:
                # Parse conversation messages for skill invocations
                messages = conv.get("messages", [])
                for msg in messages:
                    content = msg.get("content", "")

                    # Look for skill usage patterns (tool calls, skill mentions)
                    skill_mentions = self._extract_skill_mentions(content)

                    for skill_id in skill_mentions:
                        skill_stats[skill_id]["uses"] += 1

                        # Check if execution was successful (heuristic)
                        if self._was_execution_successful(msg):
                            skill_stats[skill_id]["successes"] += 1
                        else:
                            skill_stats[skill_id]["failures"] += 1

            # Generate analysis results
            for skill_id, stats in skill_stats.items():
                usage_count = stats["uses"]
                success_rate = stats["successes"] / usage_count if usage_count > 0 else 0.0

                # Generate suggestion based on metrics
                suggestion = self._generate_skill_suggestion(
                    skill_id, usage_count, success_rate
                )

                results.append({
                    "skill_id": skill_id,
                    "usage_count": usage_count,
                    "success_rate": success_rate,
                    "successes": stats["successes"],
                    "failures": stats["failures"],
                    "suggestion": suggestion,
                })

            # Sort by usage count descending
            results.sort(key=lambda x: x["usage_count"], reverse=True)

            logger.info(f"Analyzed {len(results)} skills over {days} days")
            return results

        except Exception as e:
            logger.error(f"Failed to analyze skill performance: {e}")
            return []

    async def analyze_tool_failures(self, days: int = 7) -> List[Dict]:
        """Analyze tool execution failures and error patterns.

        Args:
            days: Number of days to analyze (default: 7)

        Returns:
            List of failed tool patterns with tool_name, error_type, count, suggestion
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            conversations = await self._get_recent_conversations(cutoff_date)

            # Track error patterns
            error_patterns = defaultdict(lambda: {"count": 0, "examples": []})

            for conv in conversations:
                messages = conv.get("messages", [])
                for msg in messages:
                    content = msg.get("content", "")

                    # Look for error indicators
                    if any(indicator in content.lower() for indicator in [
                        "error:", "failed", "exception", "timeout", "not found"
                    ]):
                        # Extract tool name and error type
                        tool_name = self._extract_tool_name_from_error(content)
                        error_type = self._classify_error(content)

                        if tool_name and error_type:
                            key = f"{tool_name}:{error_type}"
                            error_patterns[key]["count"] += 1

                            # Keep example (limit to 3 per pattern)
                            if len(error_patterns[key]["examples"]) < 3:
                                error_patterns[key]["examples"].append(
                                    content[:200]  # First 200 chars
                                )

            # Generate failure analysis
            results = []
            for pattern_key, data in error_patterns.items():
                tool_name, error_type = pattern_key.split(":", 1)
                count = data["count"]

                suggestion = self._generate_failure_suggestion(
                    tool_name, error_type, count
                )

                results.append({
                    "tool_name": tool_name,
                    "error_type": error_type,
                    "count": count,
                    "examples": data["examples"],
                    "suggestion": suggestion,
                })

            # Sort by count descending
            results.sort(key=lambda x: x["count"], reverse=True)

            logger.info(f"Analyzed {len(results)} error patterns over {days} days")
            return results

        except Exception as e:
            logger.error(f"Failed to analyze tool failures: {e}")
            return []

    async def generate_improvement_report(self, days: int = 7) -> str:
        """Generate comprehensive improvement report.

        Args:
            days: Number of days to analyze (default: 7)

        Returns:
            Formatted markdown report with findings and suggestions
        """
        try:
            # Run analyses
            skill_analysis = await self.analyze_skill_performance(days)
            failure_analysis = await self.analyze_tool_failures(days)

            # Build report
            report = []
            report.append(f"# 🤖 Self-Improvement Report")
            report.append(f"\n**Period:** Last {days} days")
            report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

            # Skill Performance Section
            report.append("## 📊 Skill Performance Analysis\n")

            if skill_analysis:
                report.append(f"Analyzed **{len(skill_analysis)}** skills\n")

                # Top performers
                top_skills = [s for s in skill_analysis if s["success_rate"] > 0.8]
                if top_skills:
                    report.append("### ✅ Top Performing Skills\n")
                    for skill in top_skills[:5]:
                        report.append(
                            f"- **{skill['skill_id']}**: "
                            f"{skill['usage_count']} uses, "
                            f"{skill['success_rate']:.1%} success rate"
                        )
                    report.append("")

                # Needs improvement
                problem_skills = [s for s in skill_analysis if s["success_rate"] < 0.5 and s["usage_count"] > 3]
                if problem_skills:
                    report.append("### ⚠️  Skills Needing Attention\n")
                    for skill in problem_skills:
                        report.append(
                            f"- **{skill['skill_id']}**: "
                            f"{skill['failures']} failures / {skill['usage_count']} uses"
                        )
                        report.append(f"  💡 {skill['suggestion']}\n")
                    report.append("")

                # Underutilized
                underused = [s for s in skill_analysis if s["usage_count"] == 1]
                if underused:
                    report.append(f"### 💤 Underutilized Skills: {len(underused)} skills used only once\n")

            else:
                report.append("*No skill usage data available*\n")

            # Tool Failure Section
            report.append("## 🔧 Tool Failure Analysis\n")

            if failure_analysis:
                report.append(f"Detected **{len(failure_analysis)}** error patterns\n")

                for i, failure in enumerate(failure_analysis[:10], 1):
                    report.append(f"### {i}. {failure['tool_name']} - {failure['error_type']}\n")
                    report.append(f"**Occurrences:** {failure['count']}")
                    report.append(f"**Suggestion:** {failure['suggestion']}\n")

                    if failure["examples"]:
                        report.append("**Example:**")
                        report.append(f"```\n{failure['examples'][0]}\n```\n")
            else:
                report.append("*No tool failures detected* ✅\n")

            # Recommendations Section
            report.append("## 💡 Action Items\n")

            action_items = self._generate_action_items(skill_analysis, failure_analysis)
            for i, action in enumerate(action_items, 1):
                report.append(f"{i}. {action}")

            report.append("\n---")
            report.append("*Generated by Nexus Self-Improvement Engine*")

            return "\n".join(report)

        except Exception as e:
            logger.error(f"Failed to generate improvement report: {e}")
            return f"# Error Generating Report\n\n{str(e)}"

    # ────────────────────────────────────────────
    # Helper Methods
    # ────────────────────────────────────────────

    async def _get_recent_conversations(self, cutoff_date: datetime) -> List[Dict]:
        """Get conversations since cutoff date."""
        try:
            # Query database for recent conversations
            # This is a placeholder - adjust based on actual DB schema
            if hasattr(self.db, "execute"):
                cursor = await self.db.execute(
                    "SELECT * FROM conversations WHERE created_at > ? ORDER BY created_at DESC",
                    (cutoff_date.isoformat(),)
                )
                rows = await cursor.fetchall()

                # Convert to dicts (adjust based on actual schema)
                conversations = []
                for row in rows:
                    conversations.append({
                        "id": row[0] if len(row) > 0 else None,
                        "messages": [],  # Would need to parse from row
                    })

                return conversations

            return []

        except Exception as e:
            logger.warning(f"Failed to query conversations: {e}")
            return []

    def _extract_skill_mentions(self, content: str) -> List[str]:
        """Extract skill IDs mentioned in content."""
        skills = []

        # Look for skill patterns
        if "skill:" in content.lower():
            # Extract skill IDs (basic pattern)
            import re
            matches = re.findall(r'skill:\s*(\w+[\w-]*)', content, re.IGNORECASE)
            skills.extend(matches)

        # Check for tool calls that might indicate skills
        if "tool:" in content.lower() or "action:" in content.lower():
            # Parse tool names (would map to skills)
            pass  # Implement based on actual tool naming

        return list(set(skills))  # Deduplicate

    def _was_execution_successful(self, message: Dict) -> bool:
        """Heuristic to determine if execution was successful."""
        content = message.get("content", "").lower()

        # Success indicators
        if any(indicator in content for indicator in ["✅", "success", "completed", "done"]):
            return True

        # Failure indicators
        if any(indicator in content for indicator in ["❌", "error", "failed", "exception"]):
            return False

        # Default: assume success if no error indicators
        return "error" not in content and "failed" not in content

    def _extract_tool_name_from_error(self, content: str) -> Optional[str]:
        """Extract tool name from error message."""
        import re

        # Try to find tool name patterns
        patterns = [
            r'tool[_\s]+(\w+)',
            r'function[_\s]+(\w+)',
            r'(\w+)\s+failed',
            r'error in (\w+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _classify_error(self, content: str) -> str:
        """Classify error type from content."""
        content_lower = content.lower()

        if "timeout" in content_lower:
            return "timeout"
        elif "not found" in content_lower or "404" in content_lower:
            return "not_found"
        elif "permission" in content_lower or "denied" in content_lower:
            return "permission"
        elif "invalid" in content_lower or "parse" in content_lower:
            return "invalid_input"
        elif "network" in content_lower or "connection" in content_lower:
            return "network"
        else:
            return "unknown"

    def _generate_skill_suggestion(
        self, skill_id: str, usage_count: int, success_rate: float
    ) -> str:
        """Generate improvement suggestion for a skill."""
        if success_rate < 0.3:
            return f"Review {skill_id} implementation - high failure rate"
        elif success_rate < 0.6:
            return f"Improve error handling in {skill_id}"
        elif usage_count == 1:
            return f"Consider promoting {skill_id} for more use cases"
        elif usage_count > 20:
            return f"Optimize {skill_id} for performance - high usage"
        else:
            return f"Monitor {skill_id} performance"

    def _generate_failure_suggestion(
        self, tool_name: str, error_type: str, count: int
    ) -> str:
        """Generate suggestion for tool failure pattern."""
        if error_type == "timeout":
            return f"Increase timeout limit or optimize {tool_name} performance"
        elif error_type == "not_found":
            return f"Add validation or better error messages to {tool_name}"
        elif error_type == "permission":
            return f"Review permission requirements for {tool_name}"
        elif error_type == "invalid_input":
            return f"Add input validation and better documentation for {tool_name}"
        elif error_type == "network":
            return f"Add retry logic and network error handling to {tool_name}"
        else:
            return f"Investigate {tool_name} for {error_type} errors ({count} occurrences)"

    def _generate_action_items(
        self, skill_analysis: List[Dict], failure_analysis: List[Dict]
    ) -> List[str]:
        """Generate prioritized action items."""
        actions = []

        # High priority: frequent failures
        critical_failures = [f for f in failure_analysis if f["count"] >= 5]
        if critical_failures:
            actions.append(
                f"🔴 **Critical:** Address {len(critical_failures)} high-frequency error patterns"
            )

        # Skills with low success rates
        problem_skills = [s for s in skill_analysis if s["success_rate"] < 0.5 and s["usage_count"] > 3]
        if problem_skills:
            actions.append(
                f"🟡 **Important:** Fix {len(problem_skills)} underperforming skills"
            )

        # Optimization opportunities
        high_usage = [s for s in skill_analysis if s["usage_count"] > 20]
        if high_usage:
            actions.append(
                f"🟢 **Optimize:** Consider caching or optimization for {len(high_usage)} frequently-used skills"
            )

        # Documentation
        if not actions:
            actions.append("✅ No critical issues detected - continue monitoring")

        return actions
