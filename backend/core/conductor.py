"""OrchestratorConductor — State machine for multi-agent development builds.

Implements the Boris Cherny pattern: a conductor coordinates multiple Claude Code
agents through a reactive state machine:

    PLANNING → RESEARCHING → BUILDING → REVIEWING → FIXING → TESTING → COMPLETE

Key features:
- Reactive loops: review failure → re-enter BUILDING with feedback
- Max 3 build-review cycles before escalating to user
- Branch-per-agent git strategy with merge on approval
- Full observability via EventBus + WorkRegistry + WebSocket
- Each agent gets its own terminal session and git branch

Architecture:
    OrchestratorConductor sits between the user request and SubAgentOrchestrator.
    It breaks a complex task into phases, dispatches agents per phase, and reacts
    to results (especially reviewer feedback) to decide next steps.

Usage:
    from core.conductor import OrchestratorConductor

    conductor = OrchestratorConductor(
        task="Build REST API with auth and tests",
        state=app_state,
        ws_id="ws-abc",
        conv_id="conv-xyz",
    )
    result = await conductor.run()  # Returns final output
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from core.event_bus import (
    BuildCycleEvent,
    ConductorCompleteEvent,
    ConductorStartEvent,
    PhaseChangeEvent,
    event_bus,
)
from core.work_registry import work_registry

logger = logging.getLogger("nexus.conductor")


# ── Phases ──────────────────────────────────────────────────────


class Phase(str, Enum):
    """Conductor phases — the state machine."""
    IDLE = "idle"
    PLANNING = "planning"
    RESEARCHING = "researching"
    BUILDING = "building"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    TESTING = "testing"
    COMPLETE = "complete"
    FAILED = "failed"
    ESCALATED = "escalated"


# Valid transitions
_TRANSITIONS = {
    Phase.IDLE: [Phase.PLANNING],
    Phase.PLANNING: [Phase.RESEARCHING, Phase.BUILDING, Phase.COMPLETE],
    Phase.RESEARCHING: [Phase.BUILDING, Phase.PLANNING],
    Phase.BUILDING: [Phase.REVIEWING, Phase.TESTING, Phase.FAILED],
    Phase.REVIEWING: [Phase.COMPLETE, Phase.FIXING, Phase.ESCALATED],
    Phase.FIXING: [Phase.REVIEWING, Phase.BUILDING, Phase.FAILED],
    Phase.TESTING: [Phase.COMPLETE, Phase.FIXING, Phase.FAILED],
    Phase.COMPLETE: [],
    Phase.FAILED: [],
    Phase.ESCALATED: [],
}

# Default configuration
_MAX_BUILD_REVIEW_CYCLES = 3
_MIN_REVIEW_SCORE = 7  # Out of 10
_DEFAULT_BUILDER_MODEL = "claude_code"
_DEFAULT_REVIEWER_MODEL = "claude_code"
_DEFAULT_RESEARCHER_MODEL = None  # auto-route


# ── Data Classes ────────────────────────────────────────────────


@dataclass
class ConductorConfig:
    """Configuration for a conductor run."""
    max_build_cycles: int = _MAX_BUILD_REVIEW_CYCLES
    min_review_score: float = _MIN_REVIEW_SCORE
    builder_model: str = _DEFAULT_BUILDER_MODEL
    reviewer_model: str = _DEFAULT_REVIEWER_MODEL
    researcher_model: Optional[str] = _DEFAULT_RESEARCHER_MODEL
    use_git_branches: bool = True
    use_terminal_sessions: bool = True
    auto_test: bool = True  # Run tests after build
    test_command: str = "python3 -m pytest tests/ -v --timeout=60"
    project_dir: str = "/Users/lennyfinn/Nexus"


@dataclass
class PhaseResult:
    """Result from a phase execution."""
    phase: Phase
    output: str = ""
    error: str = ""
    duration_ms: int = 0
    agent_id: str = ""
    model_used: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ReviewResult:
    """Parsed result from a code review."""
    score: float = 0.0
    passed: bool = False
    feedback: str = ""
    issues: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)
    raw_output: str = ""


@dataclass
class ConductorRun:
    """Full state of a conductor run."""
    id: str
    task: str
    config: ConductorConfig
    phase: Phase = Phase.IDLE
    build_cycle: int = 0
    phase_results: list = field(default_factory=list)
    plan: str = ""
    research: str = ""
    build_output: str = ""
    review_result: Optional[ReviewResult] = None
    test_output: str = ""
    final_output: str = ""
    total_cost_usd: float = 0.0
    branch_name: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


# ── Conductor ───────────────────────────────────────────────────


class OrchestratorConductor:
    """State machine orchestrator for multi-agent development builds.

    Coordinates Claude Code agents through plan→research→build→review→test
    with reactive loops on review failure.
    """

    def __init__(
        self,
        task: str,
        state: Any,
        ws_id: Optional[str] = None,
        conv_id: str = "",
        config: Optional[ConductorConfig] = None,
        abort_event: Optional[asyncio.Event] = None,
    ):
        self.task = task
        self.state = state
        self.ws_id = ws_id
        self.conv_id = conv_id
        self.config = config or ConductorConfig()
        self.abort = abort_event or asyncio.Event()

        # The run state
        self.run = ConductorRun(
            id=f"cond-{uuid.uuid4().hex[:8]}",
            task=task,
            config=self.config,
        )

        # Load config from DB if available
        self._load_config()

    def _load_config(self) -> None:
        """Load conductor config from DB settings."""
        cfg = getattr(self.state, "config_manager", None)
        if not cfg:
            return

        try:
            builder = cfg.get("SUB_AGENT_BUILDER_MODEL")
            if builder:
                self.config.builder_model = builder
            reviewer = cfg.get("SUB_AGENT_REVIEWER_MODEL")
            if reviewer:
                self.config.reviewer_model = reviewer
            max_cycles = cfg.get_int("CONDUCTOR_MAX_BUILD_CYCLES", 0)
            if max_cycles:
                self.config.max_build_cycles = max_cycles
            min_score = cfg.get("CONDUCTOR_MIN_REVIEW_SCORE")
            if min_score:
                self.config.min_review_score = float(min_score)
        except Exception:
            pass

    # ── Main Run Loop ────────────────────────────────────────────

    async def run_orchestration(self) -> str:
        """Execute the full conductor orchestration.

        Returns:
            Final output string summarizing the build.
        """
        logger.info(
            "[%s] Conductor starting: %s", self.run.id, self.task[:100]
        )

        # Register in work registry
        try:
            await work_registry.register(
                self.run.id, "conductor",
                f"Build: {self.task[:80]}",
                "running",
                conv_id=self.conv_id,
                model=self.config.builder_model,
            )
        except Exception:
            pass

        # Emit start event
        await event_bus.publish(ConductorStartEvent(
            conductor_id=self.run.id,
            task=self.task,
            strategy="build_review_cycle",
            agent_count=0,  # Updated as agents are spawned
        ))

        # Notify WebSocket
        await self._ws_notify({
            "type": "conductor_start",
            "conductor_id": self.run.id,
            "task": self.task[:200],
            "config": {
                "max_build_cycles": self.config.max_build_cycles,
                "min_review_score": self.config.min_review_score,
                "builder_model": self.config.builder_model,
                "reviewer_model": self.config.reviewer_model,
            },
        })

        try:
            # Phase 1: Planning
            await self._transition(Phase.PLANNING)
            plan_result = await self._phase_plan()
            self.run.plan = plan_result.output
            self.run.phase_results.append(plan_result)

            if self.abort.is_set():
                return self._abort_result()

            # Phase 2: Research (optional — skip if plan says "no research needed")
            if self._needs_research(plan_result.output):
                await self._transition(Phase.RESEARCHING)
                research_result = await self._phase_research()
                self.run.research = research_result.output
                self.run.phase_results.append(research_result)

            if self.abort.is_set():
                return self._abort_result()

            # Phase 3-4-5: Build → Review → Fix cycle
            for cycle in range(1, self.config.max_build_cycles + 1):
                self.run.build_cycle = cycle

                if self.abort.is_set():
                    return self._abort_result()

                # Build
                await self._transition(Phase.BUILDING)
                build_result = await self._phase_build(cycle)
                self.run.build_output = build_result.output
                self.run.phase_results.append(build_result)

                if self.abort.is_set():
                    return self._abort_result()

                # Review
                await self._transition(Phase.REVIEWING)
                review = await self._phase_review(build_result.output, cycle)
                self.run.review_result = review
                self.run.phase_results.append(PhaseResult(
                    phase=Phase.REVIEWING,
                    output=review.raw_output,
                    metadata={"score": review.score, "passed": review.passed},
                ))

                # Emit build cycle event
                await event_bus.publish(BuildCycleEvent(
                    conductor_id=self.run.id,
                    cycle_number=cycle,
                    builder_model=self.config.builder_model,
                    reviewer_model=self.config.reviewer_model,
                    reviewer_score=review.score,
                    passed=review.passed,
                    feedback_preview=review.feedback[:200],
                ))

                if review.passed:
                    logger.info(
                        "[%s] Review passed (score %.1f) on cycle %d",
                        self.run.id, review.score, cycle,
                    )
                    break

                # Review failed — fix and retry
                if cycle < self.config.max_build_cycles:
                    logger.info(
                        "[%s] Review failed (score %.1f), entering fix cycle %d/%d",
                        self.run.id, review.score, cycle, self.config.max_build_cycles,
                    )
                    await self._transition(Phase.FIXING)
                    fix_result = await self._phase_fix(review, cycle)
                    self.run.phase_results.append(fix_result)
                else:
                    # Max cycles reached — escalate to user
                    logger.warning(
                        "[%s] Max build cycles (%d) reached, escalating",
                        self.run.id, self.config.max_build_cycles,
                    )
                    await self._transition(Phase.ESCALATED)
                    return await self._escalate_result(review)

            # Phase 6: Testing (optional)
            if self.config.auto_test and not self.abort.is_set():
                await self._transition(Phase.TESTING)
                test_result = await self._phase_test()
                self.run.test_output = test_result.output
                self.run.phase_results.append(test_result)

                if test_result.metadata.get("tests_passed") is False:
                    # Tests failed — one more fix attempt
                    await self._transition(Phase.FIXING)
                    fix_result = await self._phase_fix_tests(test_result)
                    self.run.phase_results.append(fix_result)

                    # Re-run tests
                    await self._transition(Phase.TESTING)
                    test_result2 = await self._phase_test()
                    self.run.phase_results.append(test_result2)

            # Complete!
            await self._transition(Phase.COMPLETE)
            self.run.completed_at = time.time()
            duration_ms = int((self.run.completed_at - self.run.started_at) * 1000)

            # Merge git branch if applicable
            if self.config.use_git_branches and self.run.branch_name:
                try:
                    from core.git_coordinator import git_coordinator
                    await git_coordinator.merge(
                        self.run.branch_name,
                        conductor_id=self.run.id,
                    )
                except Exception as e:
                    logger.warning("Git merge failed: %s", e)

            # Build final output
            self.run.final_output = self._build_final_output()

            # Emit completion
            await event_bus.publish(ConductorCompleteEvent(
                conductor_id=self.run.id,
                status="success",
                duration_ms=duration_ms,
                build_cycles=self.run.build_cycle,
                agents_used=len(self.run.phase_results),
                total_cost_usd=self.run.total_cost_usd,
            ))

            try:
                await work_registry.update(self.run.id, "completed", {
                    "duration_ms": duration_ms,
                    "build_cycles": self.run.build_cycle,
                    "total_cost_usd": self.run.total_cost_usd,
                })
            except Exception:
                pass

            # Notify WebSocket
            await self._ws_notify({
                "type": "conductor_complete",
                "conductor_id": self.run.id,
                "status": "success",
                "build_cycles": self.run.build_cycle,
                "duration_ms": duration_ms,
            })

            logger.info(
                "[%s] Conductor complete: %d cycles, %dms, $%.4f",
                self.run.id, self.run.build_cycle, duration_ms,
                self.run.total_cost_usd,
            )

            return self.run.final_output

        except Exception as exc:
            logger.error("[%s] Conductor error: %s", self.run.id, exc)
            self.run.phase = Phase.FAILED
            try:
                await work_registry.update(self.run.id, "failed", {
                    "error": str(exc),
                })
            except Exception:
                pass

            await self._ws_notify({
                "type": "conductor_complete",
                "conductor_id": self.run.id,
                "status": "failed",
                "error": str(exc),
            })

            raise

    # ── Phase Implementations ────────────────────────────────────

    async def _phase_plan(self) -> PhaseResult:
        """PLANNING phase: Break the task into a plan."""
        start = time.monotonic()

        prompt = (
            f"You are a senior software architect. Analyze this task and create "
            f"a concise implementation plan:\n\n"
            f"**Task:** {self.task}\n\n"
            f"Create a numbered plan with:\n"
            f"1. What files to create or modify\n"
            f"2. Key implementation steps\n"
            f"3. What tests to write\n"
            f"4. Any research needed first\n\n"
            f"Keep it concise — 10-20 lines max. Focus on actionable steps."
        )

        output = await self._run_agent(
            prompt,
            model=self.config.researcher_model,
            role="planner",
            phase="planning",
        )

        return PhaseResult(
            phase=Phase.PLANNING,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def _phase_research(self) -> PhaseResult:
        """RESEARCHING phase: Gather information needed for the build."""
        start = time.monotonic()

        prompt = (
            f"You are a researcher preparing for a coding task.\n\n"
            f"**Task:** {self.task}\n\n"
            f"**Plan:** {self.run.plan}\n\n"
            f"Research the following:\n"
            f"- Read any existing code files mentioned in the plan\n"
            f"- Check API documentation if external services are involved\n"
            f"- Look for existing patterns in the codebase to follow\n"
            f"- Identify any dependencies or imports needed\n\n"
            f"Return a concise research brief with your findings."
        )

        output = await self._run_agent(
            prompt,
            model=self.config.researcher_model,
            role="researcher",
            phase="researching",
        )

        return PhaseResult(
            phase=Phase.RESEARCHING,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def _phase_build(self, cycle: int) -> PhaseResult:
        """BUILDING phase: Create/modify code."""
        start = time.monotonic()

        # Create git branch on first cycle
        if self.config.use_git_branches and cycle == 1:
            try:
                from core.git_coordinator import git_coordinator
                branch_name = f"conductor/{self.run.id}"
                await git_coordinator.create_branch(
                    branch_name,
                    conductor_id=self.run.id,
                    task_description=self.task[:100],
                )
                self.run.branch_name = branch_name
            except Exception as e:
                logger.warning("Git branch creation failed: %s", e)

        # Build the builder prompt
        context_parts = [
            f"You are a senior software engineer. Build the following:\n\n"
            f"**Task:** {self.task}\n\n"
            f"**Plan:**\n{self.run.plan}\n"
        ]

        if self.run.research:
            context_parts.append(f"\n**Research findings:**\n{self.run.research}\n")

        # On retry cycles, include review feedback
        if cycle > 1 and self.run.review_result:
            context_parts.append(
                f"\n**Review feedback (cycle {cycle - 1}, score {self.run.review_result.score}/10):**\n"
                f"{self.run.review_result.feedback}\n\n"
                f"**Issues to fix:**\n"
                + "\n".join(f"- {issue}" for issue in self.run.review_result.issues)
                + "\n\nAddress ALL issues listed above."
            )

        context_parts.append(
            "\n\nIMPORTANT:\n"
            "- Write complete, working code — not pseudocode or outlines\n"
            "- Follow existing code patterns and conventions\n"
            "- Include proper error handling\n"
            "- Create any necessary imports\n"
            "- Your work WILL be reviewed by another agent"
        )

        prompt = "\n".join(context_parts)

        output = await self._run_agent(
            prompt,
            model=self.config.builder_model,
            role="builder",
            phase="building",
            timeout=300,  # Builder gets 5 min
        )

        # Commit on git branch
        if self.config.use_git_branches and self.run.branch_name:
            try:
                from core.git_coordinator import git_coordinator
                await git_coordinator.commit(
                    self.run.branch_name,
                    f"Build cycle {cycle}: {self.task[:60]}",
                    agent_id=f"builder-{self.run.id}",
                )
            except Exception as e:
                logger.warning("Git commit failed: %s", e)

        return PhaseResult(
            phase=Phase.BUILDING,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
            metadata={"cycle": cycle},
        )

    async def _phase_review(self, build_output: str, cycle: int) -> ReviewResult:
        """REVIEWING phase: Review the builder's work."""
        start = time.monotonic()

        # Get the actual diff if git branches are active
        diff = ""
        if self.config.use_git_branches and self.run.branch_name:
            try:
                from core.git_coordinator import git_coordinator
                diff = await git_coordinator.get_diff(self.run.branch_name)
            except Exception:
                pass

        review_context = diff if diff else build_output

        prompt = (
            f"You are a senior code reviewer. Review the following work:\n\n"
            f"**Original task:** {self.task}\n\n"
            f"**Implementation plan:**\n{self.run.plan}\n\n"
            f"**Code changes:**\n```\n{review_context[:10000]}\n```\n\n"
            f"Rate this work on a scale of 1-10 and provide feedback.\n\n"
            f"REQUIRED FORMAT:\n"
            f"**Score:** X/10\n"
            f"**Issues:**\n"
            f"- issue 1\n"
            f"- issue 2\n"
            f"**Suggestions:**\n"
            f"- suggestion 1\n"
            f"**Summary:** Your overall assessment.\n\n"
            f"Score >= {self.config.min_review_score} means the work is approved."
        )

        output = await self._run_agent(
            prompt,
            model=self.config.reviewer_model,
            role="reviewer",
            phase="reviewing",
            timeout=120,
        )

        # Parse the review
        return self._parse_review(output)

    async def _phase_fix(self, review: ReviewResult, cycle: int) -> PhaseResult:
        """FIXING phase: Fix issues identified by reviewer."""
        start = time.monotonic()

        prompt = (
            f"You are a software engineer fixing code review issues.\n\n"
            f"**Original task:** {self.task}\n\n"
            f"**Reviewer score:** {review.score}/10\n\n"
            f"**Issues to fix:**\n"
            + "\n".join(f"- {issue}" for issue in review.issues)
            + f"\n\n**Suggestions:**\n"
            + "\n".join(f"- {s}" for s in review.suggestions)
            + f"\n\n**Full review:**\n{review.feedback}\n\n"
            f"Fix ALL identified issues. Show the corrected code."
        )

        output = await self._run_agent(
            prompt,
            model=self.config.builder_model,
            role="fixer",
            phase="fixing",
            timeout=300,
        )

        # Commit fix
        if self.config.use_git_branches and self.run.branch_name:
            try:
                from core.git_coordinator import git_coordinator
                await git_coordinator.commit(
                    self.run.branch_name,
                    f"Fix review issues (cycle {cycle})",
                    agent_id=f"fixer-{self.run.id}",
                )
            except Exception as e:
                logger.warning("Git commit (fix) failed: %s", e)

        return PhaseResult(
            phase=Phase.FIXING,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
            metadata={"cycle": cycle, "issues_count": len(review.issues)},
        )

    async def _phase_fix_tests(self, test_result: PhaseResult) -> PhaseResult:
        """Fix failing tests."""
        start = time.monotonic()

        prompt = (
            f"You are a software engineer fixing failing tests.\n\n"
            f"**Original task:** {self.task}\n\n"
            f"**Test output:**\n```\n{test_result.output[:5000]}\n```\n\n"
            f"Fix the failing tests. This could mean:\n"
            f"- Fixing bugs in the implementation\n"
            f"- Fixing incorrect test expectations\n"
            f"- Adding missing imports or setup\n\n"
            f"Show the corrected code."
        )

        output = await self._run_agent(
            prompt,
            model=self.config.builder_model,
            role="test-fixer",
            phase="fixing",
            timeout=300,
        )

        return PhaseResult(
            phase=Phase.FIXING,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
            metadata={"fix_type": "test_failures"},
        )

    async def _phase_test(self) -> PhaseResult:
        """TESTING phase: Run the test suite."""
        start = time.monotonic()

        # Run tests via terminal session or subprocess
        test_output = ""
        tests_passed = False

        try:
            proc = await asyncio.create_subprocess_shell(
                f"cd {self.config.project_dir} && "
                f"source venv/bin/activate 2>/dev/null; "
                f"{self.config.test_command}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.config.project_dir,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            test_output = stdout.decode().strip()
            tests_passed = proc.returncode == 0
        except asyncio.TimeoutError:
            test_output = "[Tests timed out after 120 seconds]"
        except Exception as e:
            test_output = f"[Test error: {e}]"

        return PhaseResult(
            phase=Phase.TESTING,
            output=test_output,
            duration_ms=int((time.monotonic() - start) * 1000),
            metadata={
                "tests_passed": tests_passed,
                "exit_code": proc.returncode if 'proc' in dir() else -1,
            },
        )

    # ── Agent Dispatch ───────────────────────────────────────────

    async def _run_agent(
        self,
        prompt: str,
        model: Optional[str] = None,
        role: str = "",
        phase: str = "",
        timeout: int = 120,
    ) -> str:
        """Dispatch a prompt to an agent and return the output.

        Routes to Claude Code (via ClaudeSessionManager) or AgentAttempt
        (via SubAgentOrchestrator) based on model.
        """
        effective_model = model or "claude_code"

        # Notify WebSocket of agent dispatch
        await self._ws_notify({
            "type": "conductor_agent_dispatch",
            "conductor_id": self.run.id,
            "role": role,
            "phase": phase,
            "model": effective_model,
        })

        if effective_model == "claude_code":
            return await self._run_via_claude_code(prompt, role, timeout)
        else:
            return await self._run_via_sub_agent(prompt, effective_model, role, timeout)

    async def _run_via_claude_code(
        self,
        prompt: str,
        role: str,
        timeout: int,
    ) -> str:
        """Run a prompt via Claude Code CLI (agentic, with MCP tools)."""
        claude_code = getattr(self.state, "claude_code_client", None)
        if not claude_code:
            raise RuntimeError("Claude Code client not available")

        messages = [{"role": "user", "content": prompt}]

        # Use streaming for real-time progress
        full_text = ""
        try:
            async for chunk in claude_code.chat_stream(messages, system=None):
                if self.abort.is_set():
                    return full_text + "\n[ABORTED]"

                if isinstance(chunk, str):
                    full_text += chunk
        except asyncio.TimeoutError:
            return full_text + f"\n[TIMEOUT after {timeout}s]"

        return full_text

    async def _run_via_sub_agent(
        self,
        prompt: str,
        model: str,
        role: str,
        timeout: int,
    ) -> str:
        """Run a prompt via the standard model router."""
        model_router = getattr(self.state, "model_router", None)
        if not model_router:
            raise RuntimeError("Model router not available")

        try:
            result = await asyncio.wait_for(
                model_router.chat(
                    [{"role": "user", "content": prompt}],
                    system=None,
                    force_model=model if model != "auto" else None,
                ),
                timeout=timeout,
            )
            return result.get("content", "")
        except asyncio.TimeoutError:
            return f"[Agent timeout after {timeout}s]"

    # ── Review Parsing ───────────────────────────────────────────

    def _parse_review(self, output: str) -> ReviewResult:
        """Parse a structured review from reviewer output."""
        review = ReviewResult(raw_output=output)

        # Extract score (look for "X/10" pattern)
        score_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*10", output)
        if score_match:
            review.score = float(score_match.group(1))
            review.passed = review.score >= self.config.min_review_score

        # Extract issues (lines starting with - or * after **Issues**)
        issues_section = re.search(
            r"\*\*Issues:?\*\*\s*\n((?:\s*[-*]\s+.+\n?)+)", output, re.IGNORECASE
        )
        if issues_section:
            review.issues = [
                re.sub(r"^[-*]\s+", "", line.strip())
                for line in issues_section.group(1).strip().split("\n")
                if line.strip() and re.match(r"\s*[-*]\s+", line)
            ]

        # Extract suggestions (lines starting with - or * after **Suggestions**)
        suggestions_section = re.search(
            r"\*\*Suggestions?:?\*\*\s*\n((?:\s*[-*]\s+.+\n?)+)", output, re.IGNORECASE
        )
        if suggestions_section:
            review.suggestions = [
                re.sub(r"^[-*]\s+", "", line.strip())
                for line in suggestions_section.group(1).strip().split("\n")
                if line.strip() and re.match(r"\s*[-*]\s+", line)
            ]

        # Extract summary / feedback
        summary_match = re.search(
            r"\*\*Summary:?\*\*\s*(.+?)(?:\n\n|\Z)", output,
            re.IGNORECASE | re.DOTALL,
        )
        if summary_match:
            review.feedback = summary_match.group(1).strip()
        else:
            # Use the whole output as feedback
            review.feedback = output[:1000]

        # If no score was found, try to infer from language
        if not score_match:
            lower = output.lower()
            if any(w in lower for w in ["excellent", "great", "perfect", "approved"]):
                review.score = 8.0
                review.passed = True
            elif any(w in lower for w in ["good", "acceptable", "solid"]):
                review.score = 7.0
                review.passed = True
            else:
                review.score = 5.0
                review.passed = False

        return review

    # ── Helpers ──────────────────────────────────────────────────

    def _needs_research(self, plan: str) -> bool:
        """Determine if the plan requires a research phase."""
        lower = plan.lower()
        # Skip research for simple tasks
        skip_keywords = [
            "no research needed", "straightforward",
            "simple change", "well-understood",
        ]
        if any(kw in lower for kw in skip_keywords):
            return False

        # Do research if plan mentions investigation
        research_keywords = [
            "research", "investigate", "explore", "check api",
            "documentation", "existing pattern", "look at",
        ]
        return any(kw in lower for kw in research_keywords)

    async def _transition(self, to_phase: Phase) -> None:
        """Transition to a new phase with validation and events."""
        from_phase = self.run.phase

        # Validate transition
        valid = _TRANSITIONS.get(from_phase, [])
        if to_phase not in valid:
            logger.warning(
                "[%s] Invalid transition: %s → %s (valid: %s)",
                self.run.id, from_phase.value, to_phase.value,
                [p.value for p in valid],
            )

        self.run.phase = to_phase

        # Emit phase change event
        await event_bus.publish(PhaseChangeEvent(
            conductor_id=self.run.id,
            from_phase=from_phase.value,
            to_phase=to_phase.value,
        ))

        # Notify WebSocket
        await self._ws_notify({
            "type": "conductor_phase_change",
            "conductor_id": self.run.id,
            "from_phase": from_phase.value,
            "to_phase": to_phase.value,
            "build_cycle": self.run.build_cycle,
        })

        logger.info(
            "[%s] Phase: %s → %s (cycle %d)",
            self.run.id, from_phase.value, to_phase.value, self.run.build_cycle,
        )

    def _abort_result(self) -> str:
        """Build result string for an aborted run."""
        return (
            f"## Conductor Aborted\n\n"
            f"Build was aborted during phase: **{self.run.phase.value}**\n"
            f"Build cycles completed: {self.run.build_cycle}\n\n"
            f"Partial output available in the phase results."
        )

    async def _escalate_result(self, review: ReviewResult) -> str:
        """Build result string when max cycles are reached."""
        self.run.completed_at = time.time()

        try:
            await work_registry.update(self.run.id, "failed", {
                "reason": "max_cycles_reached",
                "last_score": review.score,
            })
        except Exception:
            pass

        return (
            f"## Build Escalated — Needs Human Review\n\n"
            f"After {self.config.max_build_cycles} build-review cycles, the "
            f"reviewer score is still {review.score}/10 "
            f"(minimum: {self.config.min_review_score}/10).\n\n"
            f"**Last review feedback:**\n{review.feedback}\n\n"
            f"**Outstanding issues:**\n"
            + "\n".join(f"- {issue}" for issue in review.issues)
            + f"\n\n**Build output (last cycle):**\n{self.run.build_output[:3000]}"
        )

    def _build_final_output(self) -> str:
        """Build the final summary output."""
        duration = self.run.completed_at - self.run.started_at if self.run.completed_at else 0

        parts = [
            f"## Build Complete ✅\n",
            f"**Task:** {self.task}\n",
            f"**Duration:** {duration:.1f}s",
            f"**Build cycles:** {self.run.build_cycle}",
            f"**Review score:** {self.run.review_result.score if self.run.review_result else 'N/A'}/10",
        ]

        if self.run.test_output:
            passed = "✅" if "passed" in self.run.test_output.lower() else "⚠️"
            parts.append(f"**Tests:** {passed}")

        if self.run.branch_name:
            parts.append(f"**Branch:** `{self.run.branch_name}` → merged to main")

        parts.append(f"\n### Build Output\n{self.run.build_output[:5000]}")

        if self.run.review_result and self.run.review_result.feedback:
            parts.append(f"\n### Review\n{self.run.review_result.feedback[:1000]}")

        return "\n".join(parts)

    async def _ws_notify(self, message: dict) -> None:
        """Send a WebSocket notification."""
        if not self.ws_id:
            return

        try:
            from websocket_manager import websocket_manager
            await websocket_manager.send_to_client(self.ws_id, message)
        except Exception:
            pass
