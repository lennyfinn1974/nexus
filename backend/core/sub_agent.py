"""Sub-Agent Orchestration System.

Spawns multiple AgentAttempt instances (or Claude Code subprocesses) in parallel,
each with different models and roles, then synthesises the results into a single
coherent response.

Architecture
------------
- ``SubAgentOrchestrator`` sits between ``AgentRunner`` and ``AgentAttempt``.
- Each sub-agent is defined by a ``SubAgentSpec`` (role, model, prompt, dependencies).
- Specs are topologically sorted into dependency layers and executed via ``asyncio.gather``.
- Claude Code sub-agents run as direct subprocess invocations (``ClaudeCodeClient``).
- Results are synthesised by a final LLM call or returned directly if only one agent.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from core.errors import AgentAbortError
from websocket_manager import websocket_manager

if TYPE_CHECKING:
    from config_manager import ConfigManager

logger = logging.getLogger("nexus.sub_agent")


# ── Enums ────────────────────────────────────────────────────────


class SubAgentRole(str, Enum):
    BUILDER = "builder"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"
    VERIFIER = "verifier"
    SYNTHESIZER = "synthesizer"


class SubAgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── Data Classes ─────────────────────────────────────────────────


@dataclass
class SubAgentSpec:
    """Definition of a single sub-agent to spawn."""

    id: str
    role: SubAgentRole
    prompt: str
    model: str | None = None          # None = auto-route. "ollama", "claude", "claude_code"
    system_addendum: str = ""         # Extra system prompt appended per sub-agent
    depends_on: list = field(default_factory=list)  # IDs of specs this depends on
    timeout_seconds: int = 120        # Claude Code gets 300s default
    include_tools: bool = True
    include_context: bool = True      # Whether sub-agent sees conversation history
    use_mcp: bool = False             # True for claude_code


@dataclass
class SubAgentResult:
    """Result from a completed sub-agent."""

    id: str
    role: SubAgentRole
    model_used: str
    output: str
    error: str = ""
    status: SubAgentStatus = SubAgentStatus.COMPLETED
    duration_ms: int = 0


@dataclass
class Orchestration:
    """Full orchestration: specs + results + final output."""

    id: str
    strategy: str
    specs: list = field(default_factory=list)
    results: dict = field(default_factory=dict)  # spec_id -> SubAgentResult
    final_output: str = ""


# ── Role Prompts ─────────────────────────────────────────────────

ROLE_PROMPTS: dict[str, dict[str, str]] = {
    "builder": {
        "default": (
            "You are a builder sub-agent. Produce the primary output for the task below. "
            "Be thorough and complete — your work will be reviewed by another agent."
        ),
        "claude_code": (
            "You are a builder sub-agent with full MCP tool access. "
            "Create files, run commands, and verify your output works. "
            "Be thorough — another agent will review your work."
        ),
    },
    "reviewer": {
        "default": (
            "You are a reviewer sub-agent. Analyse the output from the builder. "
            "Identify errors, suggest specific improvements, and rate quality 1-10. "
            "Don't rewrite everything — focus on what matters."
        ),
        "claude_code": (
            "You are a reviewer sub-agent with full MCP tool access. "
            "Read the builder's output, run tests if applicable, check for bugs. "
            "Rate quality 1-10 and suggest specific improvements."
        ),
    },
    "researcher": {
        "default": (
            "You are a researcher sub-agent. Gather information using available tools. "
            "Be thorough but concise — another agent will synthesise your findings."
        ),
    },
    "verifier": {
        "default": (
            "You are a verifier sub-agent. Independently verify the claim below. "
            "Search for evidence, cross-reference sources. "
            "Report your confidence as a percentage (0-100%) with reasoning."
        ),
    },
    "synthesizer": {
        "default": (
            "You are a synthesiser. Merge the outputs below into one coherent, "
            "well-structured response. Resolve any contradictions. "
            "Do NOT mention sub-agents, orchestration, or that multiple agents were used."
        ),
    },
}


def _get_role_prompt(role: SubAgentRole, model: str | None = None) -> str:
    """Get the appropriate role prompt, with model-specific variant if available."""
    role_dict = ROLE_PROMPTS.get(role.value, {})
    if model and model in role_dict:
        return role_dict[model]
    return role_dict.get("default", "")


# ── Strategy Factory ─────────────────────────────────────────────


class OrchestrationStrategy:
    """Factory for pre-defined orchestration patterns."""

    @staticmethod
    def parallel_research(
        queries: list[str],
        cfg: ConfigManager | None = None,
    ) -> Orchestration:
        """N researchers run in parallel, synthesiser merges results."""
        orch_id = f"orch-{uuid.uuid4().hex[:8]}"
        specs = []

        for i, query in enumerate(queries):
            spec_id = f"sa-{uuid.uuid4().hex[:6]}"
            specs.append(SubAgentSpec(
                id=spec_id,
                role=SubAgentRole.RESEARCHER,
                prompt=query,
                model=None,  # auto-route
            ))

        # Add synthesiser that depends on all researchers
        synth_id = f"sa-synth-{uuid.uuid4().hex[:6]}"
        specs.append(SubAgentSpec(
            id=synth_id,
            role=SubAgentRole.SYNTHESIZER,
            prompt="Merge the research findings above into one coherent response.",
            depends_on=[s.id for s in specs],
            include_tools=False,
        ))

        return Orchestration(id=orch_id, strategy="parallel_research", specs=specs)

    @staticmethod
    def build_review(
        task: str,
        builder_model: str | None = None,
        reviewer_model: str | None = None,
        cfg: ConfigManager | None = None,
    ) -> Orchestration:
        """Builder creates output, Reviewer critiques it."""
        orch_id = f"orch-{uuid.uuid4().hex[:8]}"

        # Resolve default models from config
        if cfg and not builder_model:
            builder_model = cfg.get("SUB_AGENT_BUILDER_MODEL") or None
        if cfg and not reviewer_model:
            reviewer_model = cfg.get("SUB_AGENT_REVIEWER_MODEL") or "claude"

        builder_id = f"sa-build-{uuid.uuid4().hex[:6]}"
        reviewer_id = f"sa-review-{uuid.uuid4().hex[:6]}"

        specs = [
            SubAgentSpec(
                id=builder_id,
                role=SubAgentRole.BUILDER,
                prompt=task,
                model=builder_model,
            ),
            SubAgentSpec(
                id=reviewer_id,
                role=SubAgentRole.REVIEWER,
                prompt=f"Review the following output:\n\n{{{{result:{builder_id}}}}}",
                model=reviewer_model,
                depends_on=[builder_id],
            ),
        ]

        return Orchestration(id=orch_id, strategy="build_review", specs=specs)

    @staticmethod
    def build_review_code(
        task: str,
        cfg: ConfigManager | None = None,
    ) -> Orchestration:
        """Claude Code builds, Claude Code reviews — full MCP tool access."""
        orch_id = f"orch-{uuid.uuid4().hex[:8]}"

        # Resolve models from config
        code_builder = "claude_code"
        code_reviewer = "claude_code"
        if cfg:
            code_builder = cfg.get("SUB_AGENT_CODE_BUILDER_MODEL") or "claude_code"
            code_reviewer = cfg.get("SUB_AGENT_CODE_REVIEWER_MODEL") or "claude_code"

        builder_id = f"sa-build-{uuid.uuid4().hex[:6]}"
        reviewer_id = f"sa-review-{uuid.uuid4().hex[:6]}"

        specs = [
            SubAgentSpec(
                id=builder_id,
                role=SubAgentRole.BUILDER,
                prompt=task,
                model=code_builder,
                use_mcp=code_builder == "claude_code",
                timeout_seconds=300,
            ),
            SubAgentSpec(
                id=reviewer_id,
                role=SubAgentRole.REVIEWER,
                prompt=f"Review the following output:\n\n{{{{result:{builder_id}}}}}",
                model=code_reviewer,
                use_mcp=code_reviewer == "claude_code",
                depends_on=[builder_id],
                timeout_seconds=300,
            ),
        ]

        return Orchestration(id=orch_id, strategy="build_review_code", specs=specs)

    @staticmethod
    def verify(
        claim: str,
        num_verifiers: int = 2,
        cfg: ConfigManager | None = None,
    ) -> Orchestration:
        """N verifiers independently check a claim in parallel."""
        orch_id = f"orch-{uuid.uuid4().hex[:8]}"
        specs = []

        for i in range(num_verifiers):
            spec_id = f"sa-verify-{uuid.uuid4().hex[:6]}"
            specs.append(SubAgentSpec(
                id=spec_id,
                role=SubAgentRole.VERIFIER,
                prompt=f"Verify this claim: {claim}",
                model=None,  # auto-route
            ))

        # Synthesiser merges verification results
        synth_id = f"sa-synth-{uuid.uuid4().hex[:6]}"
        specs.append(SubAgentSpec(
            id=synth_id,
            role=SubAgentRole.SYNTHESIZER,
            prompt="Compare the verification results and provide a final verdict with confidence level.",
            depends_on=[s.id for s in specs],
            include_tools=False,
        ))

        return Orchestration(id=orch_id, strategy="verify", specs=specs)

    @staticmethod
    def from_plan(plan: Any, cfg: Any = None) -> Orchestration:
        """Convert a Plan (from planner.py) into an Orchestration.

        Independent plan steps (no depends_on) become parallel sub-agents.
        Dependent steps are executed in order via the dependency graph.
        """
        orch_id = f"orch-plan-{uuid.uuid4().hex[:8]}"
        specs = []

        for step in plan.steps:
            spec_id = f"sa-plan-{step.id}"
            specs.append(SubAgentSpec(
                id=spec_id,
                role=SubAgentRole.RESEARCHER,
                prompt=f"{step.title}: {step.description}",
                model=None,  # auto-route
                depends_on=[f"sa-plan-{dep}" for dep in getattr(step, 'depends_on', [])],
                include_tools=getattr(step, 'tool_hint', '') not in ("none", ""),
            ))

        # If there are multiple independent steps, add a synthesiser
        independent_count = sum(1 for s in specs if not s.depends_on)
        if len(specs) > 1 and independent_count > 1:
            synth_id = f"sa-plan-synth-{uuid.uuid4().hex[:6]}"
            specs.append(SubAgentSpec(
                id=synth_id,
                role=SubAgentRole.SYNTHESIZER,
                prompt="Merge the results from all plan steps into one coherent response.",
                depends_on=[s.id for s in specs],
                include_tools=False,
            ))

        return Orchestration(id=orch_id, strategy="plan_execution", specs=specs)


# ── Runner Shim ──────────────────────────────────────────────────


@dataclass
class SubAgentRunnerShim:
    """Lightweight shim that satisfies AgentAttempt's runner interface.

    AgentAttempt reads ``runner.abort``, ``runner.state``, ``runner.ws_id``.
    This provides those fields without duplicating the full AgentRunner.
    """

    state: Any
    abort: asyncio.Event
    ws_id: str
    conv_id: str = ""
    text: str = ""
    force_model: str | None = None


# ── Orchestrator ─────────────────────────────────────────────────


class SubAgentOrchestrator:
    """Execute an orchestration: spawn sub-agents, collect results, synthesise."""

    def __init__(
        self,
        state: Any,
        ws_id: str | None,
        conv_id: str,
        parent_abort: asyncio.Event,
        messages: list[dict],
        cfg: ConfigManager | None = None,
    ):
        self.state = state
        self.ws_id = ws_id
        self.conv_id = conv_id
        self.parent_abort = parent_abort
        self.messages = messages
        self.cfg = cfg

        # Concurrency controls
        max_concurrent = 4
        cc_concurrent = 2
        if cfg:
            max_concurrent = cfg.get_int("SUB_AGENT_MAX_CONCURRENT", 4)
            cc_concurrent = cfg.get_int("SUB_AGENT_CLAUDE_CODE_CONCURRENT", 2)

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._claude_code_semaphore = asyncio.Semaphore(cc_concurrent)

        # Track running tasks for abort
        self._running_tasks: list[asyncio.Task] = []

    async def execute(self, orchestration: Orchestration) -> str:
        """Run the full orchestration. Returns synthesised output."""
        from core.work_registry import work_registry

        logger.info(
            f"[{orchestration.id}] Starting orchestration: {orchestration.strategy} "
            f"with {len(orchestration.specs)} sub-agents"
        )

        # Register orchestration in work registry
        try:
            await work_registry.register(
                orchestration.id, "orchestration",
                f"{orchestration.strategy} ({len(orchestration.specs)} agents)",
                status="running", conv_id=self.conv_id,
            )
        except Exception:
            pass

        # Notify UI
        if self.ws_id:
            await websocket_manager.send_to_client(
                self.ws_id,
                {
                    "type": "sub_agent_start",
                    "orchestration_id": orchestration.id,
                    "strategy": orchestration.strategy,
                    "sub_agent_count": len(orchestration.specs),
                    "sub_agents": [
                        {
                            "id": s.id,
                            "role": s.role.value,
                            "model": s.model or "auto",
                        }
                        for s in orchestration.specs
                    ],
                },
            )

        try:
            # Topologically sort specs into dependency layers
            layers = self._topological_sort(orchestration.specs)

            for layer_idx, layer in enumerate(layers):
                if self.parent_abort.is_set():
                    raise AgentAbortError("Orchestration aborted by user")

                logger.info(
                    f"[{orchestration.id}] Executing layer {layer_idx + 1}/{len(layers)}: "
                    f"{[s.id for s in layer]}"
                )

                # Execute all specs in this layer concurrently
                tasks = []
                for spec in layer:
                    task = asyncio.create_task(
                        self._run_sub_agent_with_semaphore(spec, orchestration),
                        name=f"sub-agent-{spec.id}",
                    )
                    self._running_tasks.append(task)
                    tasks.append(task)

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results
                for spec, result in zip(layer, results):
                    if isinstance(result, Exception):
                        logger.error(f"[{orchestration.id}] Sub-agent {spec.id} failed: {result}")
                        orchestration.results[spec.id] = SubAgentResult(
                            id=spec.id,
                            role=spec.role,
                            model_used=spec.model or "unknown",
                            output="",
                            error=str(result),
                            status=SubAgentStatus.FAILED,
                        )
                    else:
                        orchestration.results[spec.id] = result

                    # Notify UI of completion
                    if self.ws_id:
                        r = orchestration.results[spec.id]
                        await websocket_manager.send_to_client(
                            self.ws_id,
                            {
                                "type": "sub_agent_complete",
                                "orchestration_id": orchestration.id,
                                "sub_agent_id": spec.id,
                                "sub_agent_role": spec.role.value,
                                "sub_agent_model": r.model_used,
                                "sub_agent_status": r.status.value,
                                "content": r.output[:500] if r.output else r.error[:200],
                                "duration_ms": r.duration_ms,
                            },
                        )

            # Synthesise results
            final = await self._synthesize(orchestration)
            orchestration.final_output = final

            logger.info(
                f"[{orchestration.id}] Orchestration complete: "
                f"{sum(1 for r in orchestration.results.values() if r.status == SubAgentStatus.COMPLETED)} "
                f"succeeded, "
                f"{sum(1 for r in orchestration.results.values() if r.status == SubAgentStatus.FAILED)} "
                f"failed"
            )

            try:
                await work_registry.update(orchestration.id, "completed")
            except Exception:
                pass

            return final

        except AgentAbortError:
            # Cancel all running tasks
            for task in self._running_tasks:
                if not task.done():
                    task.cancel()
            try:
                await work_registry.update(orchestration.id, "cancelled")
            except Exception:
                pass
            raise

        except Exception as exc:
            logger.error(f"[{orchestration.id}] Orchestration error: {exc}")
            try:
                await work_registry.update(orchestration.id, "failed", {"error": str(exc)})
            except Exception:
                pass
            raise

    async def _run_sub_agent_with_semaphore(
        self, spec: SubAgentSpec, orchestration: Orchestration
    ) -> SubAgentResult:
        """Run a sub-agent with concurrency control."""
        async with self._semaphore:
            return await self._run_sub_agent(spec, orchestration)

    async def _run_sub_agent(
        self, spec: SubAgentSpec, orchestration: Orchestration
    ) -> SubAgentResult:
        """Execute a single sub-agent. Routes to the appropriate execution path."""
        start_time = time.monotonic()

        # Check abort
        if self.parent_abort.is_set():
            return SubAgentResult(
                id=spec.id,
                role=spec.role,
                model_used=spec.model or "cancelled",
                output="",
                error="Aborted",
                status=SubAgentStatus.CANCELLED,
            )

        # Register sub-agent in work registry
        from core.work_registry import work_registry
        try:
            await work_registry.register(
                spec.id, "sub_agent",
                f"{spec.role.value} ({spec.model or 'auto'})",
                status="running", parent_id=orchestration.id,
                conv_id=self.conv_id, model=spec.model,
            )
        except Exception:
            pass

        # Notify UI of start
        if self.ws_id:
            await websocket_manager.send_to_client(
                self.ws_id,
                {
                    "type": "sub_agent_progress",
                    "orchestration_id": orchestration.id,
                    "sub_agent_id": spec.id,
                    "sub_agent_role": spec.role.value,
                    "content": f"Starting {spec.role.value} ({spec.model or 'auto'})...",
                },
            )

        # Build the prompt — inject dependency results
        prompt = self._resolve_prompt(spec, orchestration)

        # Get role-specific system addendum
        role_prompt = _get_role_prompt(spec.role, spec.model)
        system_addendum = spec.system_addendum or role_prompt

        try:
            # Route to the right execution path
            if spec.model == "claude_code" or spec.use_mcp:
                result = await self._run_claude_code_sub_agent(
                    spec, prompt, system_addendum, orchestration
                )
            else:
                result = await self._run_attempt_sub_agent(
                    spec, prompt, system_addendum, orchestration
                )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            result.duration_ms = duration_ms

            logger.info(
                f"[{orchestration.id}] Sub-agent {spec.id} ({spec.role.value}) "
                f"completed in {duration_ms}ms via {result.model_used}"
            )

            try:
                await work_registry.update(spec.id, "completed",
                                           {"duration_ms": duration_ms, "model_used": result.model_used})
            except Exception:
                pass

            return result

        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(
                f"[{orchestration.id}] Sub-agent {spec.id} timed out after {spec.timeout_seconds}s"
            )
            try:
                await work_registry.update(spec.id, "failed",
                                           {"error": f"Timed out after {spec.timeout_seconds}s"})
            except Exception:
                pass
            return SubAgentResult(
                id=spec.id,
                role=spec.role,
                model_used=spec.model or "timeout",
                output="",
                error=f"Timed out after {spec.timeout_seconds}s",
                status=SubAgentStatus.FAILED,
                duration_ms=duration_ms,
            )

        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(f"[{orchestration.id}] Sub-agent {spec.id} error: {exc}")
            try:
                await work_registry.update(spec.id, "failed", {"error": str(exc)})
            except Exception:
                pass
            return SubAgentResult(
                id=spec.id,
                role=spec.role,
                model_used=spec.model or "error",
                output="",
                error=str(exc),
                status=SubAgentStatus.FAILED,
                duration_ms=duration_ms,
            )

    async def _run_claude_code_sub_agent(
        self,
        spec: SubAgentSpec,
        prompt: str,
        system_addendum: str,
        orchestration: Orchestration,
    ) -> SubAgentResult:
        """Run a sub-agent via Claude Code CLI subprocess."""
        claude_code = getattr(self.state, "claude_code_client", None)
        if not claude_code:
            raise RuntimeError("Claude Code client not available for sub-agent")

        # Apply Claude Code semaphore (heavier resource usage)
        async with self._claude_code_semaphore:
            # Build system prompt with role addendum
            from core.system_prompt import build_system_prompt

            system = build_system_prompt(
                self.cfg,
                getattr(self.state, "plugin_manager", None),
                tool_calling_mode="native",
                model="claude_code",
            )
            if system_addendum:
                system += f"\n\n{system_addendum}"

            # Build messages for Claude Code
            messages = []
            if spec.include_context and self.messages:
                # Include conversation context (truncated for claude_code)
                context_limit = 10  # Keep last 10 messages for context
                messages = list(self.messages[-context_limit:])

            messages.append({"role": "user", "content": prompt})

            # Stream progress to UI if WebSocket available
            if self.ws_id:
                # Use streaming mode
                full_text = ""
                async for chunk in claude_code.chat_stream(messages, system):
                    if self.parent_abort.is_set():
                        raise AgentAbortError("Sub-agent aborted")

                    if isinstance(chunk, str):
                        full_text += chunk
                        # Send progress periodically (every ~200 chars)
                        if len(full_text) % 200 < len(chunk):
                            await websocket_manager.send_to_client(
                                self.ws_id,
                                {
                                    "type": "sub_agent_progress",
                                    "orchestration_id": orchestration.id,
                                    "sub_agent_id": spec.id,
                                    "content": full_text[-500:],
                                },
                            )

                return SubAgentResult(
                    id=spec.id,
                    role=spec.role,
                    model_used="claude_code",
                    output=full_text,
                    status=SubAgentStatus.COMPLETED,
                )
            else:
                # Non-streaming (Telegram path)
                result = await asyncio.wait_for(
                    claude_code.chat(messages, system),
                    timeout=spec.timeout_seconds,
                )
                return SubAgentResult(
                    id=spec.id,
                    role=spec.role,
                    model_used=result.get("model", "claude_code"),
                    output=result.get("content", ""),
                    status=SubAgentStatus.COMPLETED,
                )

    async def _run_attempt_sub_agent(
        self,
        spec: SubAgentSpec,
        prompt: str,
        system_addendum: str,
        orchestration: Orchestration,
    ) -> SubAgentResult:
        """Run a sub-agent via AgentAttempt (Ollama/Claude API path)."""
        from core.agent_attempt import AgentAttempt
        from core.system_prompt import build_system_prompt

        # Determine model — auto-route if not specified
        model_name = spec.model
        if not model_name:
            model_name = self.state.model_router.select_model(prompt)

        # Build system prompt
        system = build_system_prompt(
            self.cfg,
            getattr(self.state, "plugin_manager", None),
            tool_calling_mode="native",
            model=model_name,
        )
        if system_addendum:
            system += f"\n\n{system_addendum}"

        # Build messages
        messages = []
        if spec.include_context and self.messages:
            context_limit = 10
            messages = list(self.messages[-context_limit:])

        messages.append({"role": "user", "content": prompt})

        # Build tool definitions
        tool_executor = getattr(self.state, "tool_executor", None)
        tools_for_api = None
        if spec.include_tools and tool_executor and model_name != "claude_code":
            if model_name == "claude":
                tools_for_api = tool_executor.to_anthropic_tools()
            elif model_name == "ollama":
                tools_for_api = tool_executor.to_ollama_tools(message=prompt)

        # Use a virtual ws_id for this sub-agent so its streaming messages
        # get transformed into sub_agent_progress messages
        virtual_ws_id = f"sa-{spec.id}"
        real_ws_id = self.ws_id

        if real_ws_id:
            # Register a transform that converts stream_* messages to sub_agent_*
            def _transform(message: dict) -> tuple[str, dict | None]:
                msg_type = message.get("type", "")
                if msg_type == "stream_start":
                    return real_ws_id, {
                        "type": "sub_agent_progress",
                        "orchestration_id": orchestration.id,
                        "sub_agent_id": spec.id,
                        "sub_agent_role": spec.role.value,
                        "content": f"[{spec.role.value} starting on {model_name}]",
                    }
                elif msg_type == "stream_chunk":
                    return real_ws_id, {
                        "type": "sub_agent_progress",
                        "orchestration_id": orchestration.id,
                        "sub_agent_id": spec.id,
                        "content": message.get("content", ""),
                    }
                elif msg_type == "stream_end":
                    # Suppress — orchestrator sends sub_agent_complete
                    return real_ws_id, None
                elif msg_type == "system":
                    return real_ws_id, {
                        "type": "sub_agent_progress",
                        "orchestration_id": orchestration.id,
                        "sub_agent_id": spec.id,
                        "content": f"[{message.get('content', '')}]",
                    }
                # Pass through anything else
                return real_ws_id, message

            websocket_manager.register_transform(virtual_ws_id, _transform)

        try:
            # Create a runner shim for AgentAttempt
            shim = SubAgentRunnerShim(
                state=self.state,
                abort=self.parent_abort,
                ws_id=virtual_ws_id if real_ws_id else f"sub-agent-{spec.id}",
                conv_id=self.conv_id,
                text=prompt,
                force_model=model_name,
            )

            # Create and execute attempt
            attempt = AgentAttempt(
                runner=shim,
                model_name=model_name,
                messages=messages,
                system=system,
                tools_for_api=tools_for_api,
                ws_id=virtual_ws_id if real_ws_id else f"sub-agent-{spec.id}",
            )

            # Execute with timeout
            result_text = await asyncio.wait_for(
                attempt.execute(),
                timeout=spec.timeout_seconds,
            )

            return SubAgentResult(
                id=spec.id,
                role=spec.role,
                model_used=model_name,
                output=result_text,
                status=SubAgentStatus.COMPLETED,
            )

        finally:
            # Always clean up the transform
            if real_ws_id:
                websocket_manager.unregister_transform(virtual_ws_id)

    async def _synthesize(self, orchestration: Orchestration) -> str:
        """Merge all sub-agent results into a single coherent response."""
        completed = {
            sid: r for sid, r in orchestration.results.items()
            if r.status == SubAgentStatus.COMPLETED and r.output
        }

        if not completed:
            failed = [
                r for r in orchestration.results.values()
                if r.status == SubAgentStatus.FAILED
            ]
            errors = "; ".join(r.error for r in failed if r.error)
            return f"All sub-agents failed. Errors: {errors}"

        # Single result — return directly
        if len(completed) == 1:
            return list(completed.values())[0].output

        # If a synthesizer sub-agent already ran and succeeded, use its output directly
        # (avoids double-synthesis where we'd call another LLM to re-merge)
        synth_results = [
            r for r in completed.values()
            if r.role == SubAgentRole.SYNTHESIZER and r.output
        ]
        if synth_results:
            return synth_results[0].output

        # Build/Review: if reviewer rates high (>7), return builder output with review notes
        if orchestration.strategy in ("build_review", "build_review_code"):
            builder_result = None
            reviewer_result = None
            for r in completed.values():
                if r.role == SubAgentRole.BUILDER:
                    builder_result = r
                elif r.role == SubAgentRole.REVIEWER:
                    reviewer_result = r

            if builder_result and reviewer_result:
                # Check if review mentions high quality
                review_text = reviewer_result.output.lower()
                # Look for ratings 8/10, 9/10, 10/10
                import re
                rating_match = re.search(r"(\d+)\s*/\s*10", review_text)
                if rating_match and int(rating_match.group(1)) >= 8:
                    # High quality — return builder output with brief review note
                    return (
                        f"{builder_result.output}\n\n"
                        f"---\n*Review ({reviewer_result.model_used}): "
                        f"{reviewer_result.output[:300]}*"
                    )

        # General synthesis — ask an LLM to merge results
        synthesis_prompt = "Merge the following outputs into a single coherent response:\n\n"
        for r in completed.values():
            role_label = r.role.value.capitalize()
            synthesis_prompt += f"## {role_label} ({r.model_used})\n{r.output}\n\n"
        synthesis_prompt += (
            "---\nProvide a unified, well-structured response that incorporates "
            "all the above. Do not mention that multiple agents were used."
        )

        # Use the model router for synthesis (prefer Claude for quality)
        try:
            synth_result = await asyncio.wait_for(
                self.state.model_router.chat(
                    [{"role": "user", "content": synthesis_prompt}],
                    system=_get_role_prompt(SubAgentRole.SYNTHESIZER),
                    force_model="claude" if self.state.model_router._claude_available else None,
                ),
                timeout=60,
            )
            return synth_result.get("content", synthesis_prompt)
        except Exception as exc:
            logger.warning(f"Synthesis LLM call failed, falling back to concatenation: {exc}")
            # Fallback: concatenate results
            parts = []
            for r in completed.values():
                parts.append(f"**{r.role.value.capitalize()}** ({r.model_used}):\n{r.output}")
            return "\n\n---\n\n".join(parts)

    def _resolve_prompt(self, spec: SubAgentSpec, orchestration: Orchestration) -> str:
        """Replace {{result:spec_id}} placeholders with actual results.

        If the prompt has no explicit placeholders but has dependencies,
        automatically appends all dependency results so the sub-agent has context.
        """
        prompt = spec.prompt
        has_placeholders = "{{result:" in prompt

        if has_placeholders:
            # Explicit placeholders — replace them
            for dep_id in spec.depends_on:
                placeholder = f"{{{{result:{dep_id}}}}}"
                if dep_id in orchestration.results:
                    dep_result = orchestration.results[dep_id]
                    if dep_result.status == SubAgentStatus.COMPLETED:
                        prompt = prompt.replace(placeholder, dep_result.output)
                    else:
                        prompt = prompt.replace(
                            placeholder,
                            f"[{dep_result.role.value} failed: {dep_result.error}]",
                        )
                else:
                    prompt = prompt.replace(placeholder, "[result not available]")
        elif spec.depends_on:
            # No placeholders but has dependencies — auto-append results
            dep_sections = []
            for dep_id in spec.depends_on:
                if dep_id in orchestration.results:
                    dep_result = orchestration.results[dep_id]
                    if dep_result.status == SubAgentStatus.COMPLETED and dep_result.output:
                        role_label = dep_result.role.value.capitalize()
                        dep_sections.append(
                            f"## {role_label} ({dep_result.model_used})\n{dep_result.output}"
                        )
                    elif dep_result.error:
                        dep_sections.append(
                            f"## {dep_result.role.value.capitalize()} [FAILED]\n{dep_result.error}"
                        )
            if dep_sections:
                prompt += "\n\n---\n\n" + "\n\n".join(dep_sections)

        return prompt

    @staticmethod
    def _topological_sort(specs: list[SubAgentSpec]) -> list[list[SubAgentSpec]]:
        """Sort specs into dependency layers for parallel execution.

        Returns a list of layers. Each layer contains specs that can run
        concurrently (all their dependencies are in earlier layers).
        """
        spec_map = {s.id: s for s in specs}
        remaining = set(s.id for s in specs)
        completed = set()
        layers = []

        while remaining:
            # Find all specs whose dependencies are satisfied
            layer = []
            for sid in list(remaining):
                spec = spec_map[sid]
                deps = set(spec.depends_on)
                if deps.issubset(completed):
                    layer.append(spec)

            if not layer:
                # Circular dependency — force remaining into one layer
                logger.warning("Circular dependency detected, forcing remaining specs")
                layer = [spec_map[sid] for sid in remaining]

            for spec in layer:
                remaining.discard(spec.id)
                completed.add(spec.id)

            layers.append(layer)

        return layers
