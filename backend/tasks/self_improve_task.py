"""Self-Improvement Task - Periodic analysis task for Nexus performance.

Can be registered with TaskQueue to run periodically and generate
improvement reports automatically.
"""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("nexus.tasks.self_improve")


async def run_self_improvement_analysis(
    db,
    skills_engine,
    config,
    days: int = 7,
    save_report: bool = True
) -> dict:
    """Run self-improvement analysis and optionally save report.

    This async function can be registered with Nexus TaskQueue for
    periodic execution.

    Args:
        db: Database connection
        skills_engine: Skills engine instance
        config: Configuration manager
        days: Number of days to analyze (default: 7)
        save_report: Whether to save report to disk (default: True)

    Returns:
        dict with status, report_path, and summary statistics
    """
    try:
        logger.info(f"Starting self-improvement analysis for last {days} days")

        # Import here to avoid circular dependencies
        from core.self_improve import SelfImprovementEngine

        # Initialize engine
        engine = SelfImprovementEngine(db, skills_engine, config)

        # Generate analyses
        skill_analysis = await engine.analyze_skill_performance(days)
        failure_analysis = await engine.analyze_tool_failures(days)

        # Generate full report
        report_content = await engine.generate_improvement_report(days)

        # Save report if requested
        report_path = None
        if save_report:
            report_path = await _save_report(report_content)
            logger.info(f"Report saved to: {report_path}")

        # Compile summary statistics
        summary = {
            "skills_analyzed": len(skill_analysis),
            "error_patterns": len(failure_analysis),
            "top_skill": skill_analysis[0]["skill_id"] if skill_analysis else None,
            "most_common_error": failure_analysis[0]["tool_name"] if failure_analysis else None,
            "critical_issues": _count_critical_issues(skill_analysis, failure_analysis),
        }

        logger.info(f"Analysis complete: {summary}")

        return {
            "status": "success",
            "report_path": report_path,
            "summary": summary,
            "report_content": report_content,
        }

    except Exception as e:
        logger.error(f"Self-improvement analysis failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "report_path": None,
            "summary": {},
        }


async def _save_report(report_content: str) -> str:
    """Save report to disk with timestamp."""
    try:
        # Determine report directory
        report_dir = Path("data/reports/self-improvement")
        report_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"improvement_report_{timestamp}.md"

        # Write report
        report_path.write_text(report_content)

        return str(report_path)

    except Exception as e:
        logger.error(f"Failed to save report: {e}")
        return None


def _count_critical_issues(skill_analysis: list, failure_analysis: list) -> int:
    """Count critical issues requiring immediate attention."""
    critical_count = 0

    # Critical: Skills with very low success rate and high usage
    for skill in skill_analysis:
        if skill["success_rate"] < 0.3 and skill["usage_count"] > 5:
            critical_count += 1

    # Critical: Frequent error patterns
    for failure in failure_analysis:
        if failure["count"] >= 5:
            critical_count += 1

    return critical_count


# ────────────────────────────────────────────
# Task Queue Registration Helper
# ────────────────────────────────────────────

def register_with_task_queue(task_queue, db, skills_engine, config):
    """Register self-improvement task with TaskQueue.

    Example usage:
        from tasks.self_improve_task import register_with_task_queue
        register_with_task_queue(task_queue, db, skills_engine, config)

    Args:
        task_queue: TaskQueue instance
        db: Database connection
        skills_engine: Skills engine
        config: Configuration manager
    """
    try:
        # Register daily analysis task
        task_queue.register_periodic_task(
            name="self_improvement_daily",
            handler=lambda: run_self_improvement_analysis(
                db, skills_engine, config, days=7, save_report=True
            ),
            interval_hours=24,
            description="Daily self-improvement analysis",
        )

        logger.info("✅ Self-improvement task registered with TaskQueue")

    except Exception as e:
        logger.error(f"Failed to register self-improvement task: {e}")


# ────────────────────────────────────────────
# CLI Mode (for manual execution)
# ────────────────────────────────────────────

async def main():
    """CLI entry point for manual execution."""
    import argparse
    import sys
    from pathlib import Path

    # Add parent directory to path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    parser = argparse.ArgumentParser(
        description="Run Nexus self-improvement analysis"
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=7,
        help="Number of days to analyze (default: 7)"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save report to disk"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # This would need proper initialization in production
    print("⚠️  CLI mode requires proper database and skills engine initialization")
    print("    Run from within Nexus application context instead")

    # Placeholder for CLI execution
    print(f"\nWould analyze last {args.days} days")
    print(f"Save report: {not args.no_save}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
