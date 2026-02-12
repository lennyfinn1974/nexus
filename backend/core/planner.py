"""Multi-step planning engine for complex tasks.

Allows the agent to:
1. Decompose a complex request into discrete steps
2. Present the plan for user approval
3. Execute steps sequentially with progress tracking
4. Handle failures and re-planning

Plan lifecycle: draft -> approved -> executing -> completed/failed

Usage:
    planner = PlanExecutor(db, model_router, task_queue)
    plan = await planner.create_plan(user_request, model="ollama")
    # User reviews plan...
    await planner.approve_plan(plan_id)
    # Execution begins automatically via task queue
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("nexus.planner")


class PlanStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    id: str
    title: str
    description: str
    tool_hint: str = ""  # Suggested tool to use
    depends_on: list = field(default_factory=list)  # IDs of steps this depends on
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    error: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "tool_hint": self.tool_hint,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class Plan:
    id: str
    title: str
    original_request: str
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: str = ""
    updated_at: str = ""
    conv_id: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @property
    def progress(self) -> dict:
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in self.steps if s.status == StepStatus.FAILED)
        running = sum(1 for s in self.steps if s.status == StepStatus.RUNNING)
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "percent": round(completed / total * 100) if total else 0,
        }

    @property
    def current_step(self) -> Optional[PlanStep]:
        for step in self.steps:
            if step.status in (StepStatus.PENDING, StepStatus.RUNNING):
                return step
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "original_request": self.original_request,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "progress": self.progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "conv_id": self.conv_id,
        }


# In-memory plan store (persists per server session; could be moved to DB later)
_plans: dict[str, Plan] = {}


PLAN_GENERATION_PROMPT = """You are a task planner. Break the following user request into discrete, actionable steps.

User request: {request}

Respond with a JSON object containing:
- "title": A short title for this plan (max 60 chars)
- "steps": An array of step objects, each with:
  - "title": Short step title (max 80 chars)
  - "description": What this step does (1-2 sentences)
  - "tool_hint": Which tool or action to use (e.g., "web_search", "file_read", "terminal", "code_edit", "none")
  - "depends_on": (optional) Array of step IDs this step depends on. Steps with no dependencies can run in parallel.

Keep to 3-7 steps. Be specific and actionable. Respond with ONLY the JSON, no other text.
Steps that can be done independently should have empty depends_on arrays so they can run in parallel.

Example:
{{"title": "Set up Python project", "steps": [{{"title": "Create project directory", "description": "Create a new directory structure for the Python project with src/ and tests/ folders.", "tool_hint": "terminal", "depends_on": []}}, {{"title": "Initialize virtual environment", "description": "Create a Python virtual environment and install base dependencies.", "tool_hint": "terminal", "depends_on": ["step-1"]}}]}}"""


class PlanExecutor:
    """Creates and manages execution plans."""

    def __init__(self, model_router: Any = None, task_queue: Any = None):
        self.model_router = model_router
        self.task_queue = task_queue

    async def create_plan(self, request: str, conv_id: str = "") -> Plan:
        """Generate a plan from a user request using the LLM."""
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"

        if self.model_router:
            prompt = PLAN_GENERATION_PROMPT.format(request=request)
            try:
                response = await self.model_router.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are a task planning assistant. Respond only with valid JSON.",
                )
                # Parse the JSON response
                data = json.loads(response.strip())
                title = data.get("title", "Untitled Plan")
                steps = []
                for i, s in enumerate(data.get("steps", [])):
                    steps.append(PlanStep(
                        id=f"step-{i+1}",
                        title=s.get("title", f"Step {i+1}"),
                        description=s.get("description", ""),
                        tool_hint=s.get("tool_hint", ""),
                        depends_on=s.get("depends_on", []),
                    ))
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to parse plan from LLM: {e}")
                title = "Plan"
                steps = [PlanStep(
                    id="step-1",
                    title="Execute request",
                    description=request,
                )]
        else:
            title = "Plan"
            steps = [PlanStep(id="step-1", title="Execute request", description=request)]

        plan = Plan(
            id=plan_id,
            title=title,
            original_request=request,
            steps=steps,
            conv_id=conv_id,
        )
        _plans[plan_id] = plan
        logger.info(f"Created plan {plan_id}: '{title}' with {len(steps)} steps")

        # Register in work registry
        try:
            from core.work_registry import work_registry
            await work_registry.register(
                plan_id, "plan", title,
                status="pending", conv_id=conv_id,
                metadata={"steps": len(steps)},
            )
            for step in steps:
                await work_registry.register(
                    f"{plan_id}/{step.id}", "plan_step", step.title,
                    status="pending", parent_id=plan_id,
                )
        except Exception:
            pass

        return plan

    async def approve_plan(self, plan_id: str) -> Plan:
        """Mark a plan as approved (ready for execution)."""
        plan = _plans.get(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        if plan.status != PlanStatus.DRAFT:
            raise ValueError(f"Plan {plan_id} is not in draft state (current: {plan.status})")

        plan.status = PlanStatus.APPROVED
        plan.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"Plan {plan_id} approved")
        return plan

    async def cancel_plan(self, plan_id: str) -> Plan:
        """Cancel a plan."""
        plan = _plans.get(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")

        plan.status = PlanStatus.CANCELLED
        plan.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"Plan {plan_id} cancelled")
        try:
            from core.work_registry import work_registry
            await work_registry.update(plan_id, "cancelled")
        except Exception:
            pass
        return plan

    async def start_step(self, plan_id: str, step_id: str) -> PlanStep:
        """Mark a step as running."""
        plan = _plans.get(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")

        step = next((s for s in plan.steps if s.id == step_id), None)
        if not step:
            raise ValueError(f"Step {step_id} not found in plan {plan_id}")

        step.status = StepStatus.RUNNING
        step.started_at = datetime.now(timezone.utc).isoformat()
        plan.status = PlanStatus.EXECUTING
        plan.updated_at = datetime.now(timezone.utc).isoformat()
        try:
            from core.work_registry import work_registry
            await work_registry.update(f"{plan_id}/{step_id}", "running")
            await work_registry.update(plan_id, "running")
        except Exception:
            pass
        return step

    async def complete_step(self, plan_id: str, step_id: str, result: str = "") -> PlanStep:
        """Mark a step as completed."""
        plan = _plans.get(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")

        step = next((s for s in plan.steps if s.id == step_id), None)
        if not step:
            raise ValueError(f"Step {step_id} not found")

        step.status = StepStatus.COMPLETED
        step.result = result
        step.completed_at = datetime.now(timezone.utc).isoformat()
        plan.updated_at = datetime.now(timezone.utc).isoformat()

        # Check if all steps are done
        if all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in plan.steps):
            plan.status = PlanStatus.COMPLETED
            logger.info(f"Plan {plan_id} completed")

        try:
            from core.work_registry import work_registry
            await work_registry.update(f"{plan_id}/{step_id}", "completed")
            if plan.status == PlanStatus.COMPLETED:
                await work_registry.update(plan_id, "completed")
        except Exception:
            pass

        return step

    async def fail_step(self, plan_id: str, step_id: str, error: str = "") -> PlanStep:
        """Mark a step as failed."""
        plan = _plans.get(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")

        step = next((s for s in plan.steps if s.id == step_id), None)
        if not step:
            raise ValueError(f"Step {step_id} not found")

        step.status = StepStatus.FAILED
        step.error = error
        step.completed_at = datetime.now(timezone.utc).isoformat()
        plan.status = PlanStatus.FAILED
        plan.updated_at = datetime.now(timezone.utc).isoformat()
        logger.warning(f"Plan {plan_id} step {step_id} failed: {error}")
        try:
            from core.work_registry import work_registry
            await work_registry.update(f"{plan_id}/{step_id}", "failed", {"error": error})
            await work_registry.update(plan_id, "failed")
        except Exception:
            pass
        return step

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        return _plans.get(plan_id)

    def list_plans(self, conv_id: str = "") -> list[dict]:
        plans = _plans.values()
        if conv_id:
            plans = [p for p in plans if p.conv_id == conv_id]
        return [p.to_dict() for p in sorted(plans, key=lambda p: p.created_at, reverse=True)]
