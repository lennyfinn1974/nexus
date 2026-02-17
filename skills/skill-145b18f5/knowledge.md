# krea-prompt-to-workflow-nexus

## Overview
**Krea AI's prompt-to-workflow** is a feature announced in mid-2025 within Krea Nodes—Krea's visual, node-based creative pipeline builder. It allows users to describe a desired creative pipeline in natural language (e.g., "generate 10 product photo shoots from a single prompt, then turn the best into a video") and have the system automatically generate a complete, executable node graph. Instead of manually dragging, connecting, and configuring dozens of nodes across 50+ AI models (Flux, ChatGPT Image, Sora, Wan, Imagen, etc.), a user types a paragraph and gets a reusable, shareable workflow in seconds. This shifts production from "prompt-and-pray" single-shot generation to **systemized, repeatable creative pipelines** that any team member can operate.

**Building the same capability for Nexus with Claude Code** means creating a system where a user describes a desired multi-step agent workflow in natural language, and the system compiles it into an executable Directed Acyclic Graph (DAG) of Claude Code subagents, MCP tool calls, and orchestration logic. Claude Code already provides the foundational primitives: subagents with isolated contexts, MCP for external tool integration, slash commands for reusable workflows, hooks for lifecycle automation, and plugins for bundling. The core engineering challenge is the **"compiler" layer**—an LLM-powered planner that parses intent, maps it to available tools/agents, resolves dependencies, and emits an executable workflow definition (JSON/YAML DAG or programmatic pipeline). This is architecturally analogous to Prompt2DAG (academic research on NL→Airflow DAGs) but applied to creative/development agent orchestration rather than data pipelines.

The convergence matters because it represents the **next evolution of AI tooling**: moving from single-prompt interactions to composable, automated pipelines where the AI itself designs and assembles the pipeline from a high-level description. For Nexus—a FastAPI + Redis + Ollama/Claude system—this would be a differentiating capability: users describe what they want accomplished, and the system provisions, orchestrates, and executes a multi-agent workflow autonomously.

## Key Concepts
- **Prompt-to-Workflow (P2W)**: The paradigm where natural language instructions are compiled into executable multi-step pipelines—Krea's implementation auto-generates node graphs for creative AI tasks; the general pattern applies to any domain.

- **Node-Based Workflow Builder**: A visual DAG editor where each node represents an operation (model inference, image processing, text manipulation, etc.) with typed inputs/outputs connected by edges. Krea Nodes offers 50+ models across image, video, 3D, audio, and utility categories.

- **Workflow-as-Template**: Generated workflows are treated as reusable assets—stripped of project-specific details, named by business function ("Look Development Base," "Storyboard Batch"), and shareable. This is key to scaling from individual use to team production.

- **Claude Code Subagents**: Specialized AI assistants defined as Markdown files with YAML frontmatter, running in isolated context windows with custom system prompts, specific tool access, and independent permissions. Built-in types include Explore (read-only, Haiku), Plan (research), and General-purpose (full tools).

- **MCP (Model Context Protocol)**: The universal adapter layer connecting Claude Code to external tools, APIs, databases, and services. Each MCP server exposes tools, resources, and prompts. This is the "plugin system" for extending what workflows can do.

- **DAG Compilation from NL**: The core technical challenge—using an LLM as a "planner" that decomposes a natural language description into a structured workflow definition (nodes, edges, parameters, dependencies) that can be validated and executed.

- **Quality Gates & Human Checkpoints**: Both Krea and production Claude Code workflows benefit from built-in verification nodes—visual consistency checks, technical compliance enforcement, decision snapshots for reproducibility, and approval gates where a human must sign off before proceeding.

- **Workflow Execution Engine**: The runtime that traverses the DAG, dispatches each node to the appropriate executor (model API, tool call, subagent), manages data flow between nodes, handles errors/retries, and collects outputs. In Nexus this maps to FastAPI endpoints + Redis pub/sub + agent orchestration.

- **Composability & Parallelism**: Both Krea Nodes and Claude Code support running operations in parallel (Krea: side-by-side model comparisons; Claude Code: parallel subagents via the Task tool). P2W systems must resolve which steps are independent (parallelizable) vs. sequential (dependent).

- **Prompt2DAG Pattern**: Academic/open-source approach (arxiv:2509.13487) using multi-stage LLM decomposition—(1) analyze requirements, (2) generate structured workflow definition, (3) synthesize executable code via templates. Directly applicable to building Nexus P2W.

## Decision Guide
**If user asks "What is Krea's prompt-to-workflow?"** → Explain it as a feature within Krea Nodes that converts natural language descriptions into executable visual node graphs chaining 50+ AI models (image, video, 3D, audio, utility). Emphasize it's about **systematizing creative production**, not just better prompting.

**If user asks "How do I build something similar with Claude Code?"** → Point them to the three-layer architecture: (1) **Planner agent** (LLM that parses NL intent into a structured DAG definition), (2) **Workflow definition schema** (JSON/YAML specifying nodes, edges, params, tool mappings), (3) **Execution engine** (runtime that dispatches subagents/MCP calls, manages data flow, handles errors). Use Claude Code subagents as the execution units, MCP servers as tool providers, and CLAUDE.md + slash commands for configuration.

**If user asks "What primitives does Claude Code already provide?"** → Subagents (isolated AI workers with custom prompts/tools/models), MCP servers (external tool integration), slash commands (reusable triggered workflows), hooks (lifecycle event automation), plugins (shareable bundles), agent teams (multi-session coordination), and CLAUDE.md (persistent project context).

**If user asks "How is this different from n8n/Zapier/Airflow?"** → Those are general workflow automation tools. Krea P2W is domain-specific (creative AI) with built-in model access. A Nexus P2W would be domain-specific (development/agent orchestration) with built-in Claude Code agent access. The key differentiator is the **AI generates the workflow itself** from natural language, rather than requiring manual construction.

**If user asks "What's the hardest part?"** → The planner/compiler layer. It must: understand available tools and their I/O schemas, decompose ambiguous NL into concrete steps, resolve dependencies to determine execution order, handle error cases, and produce a valid DAG. Use structured output (JSON mode), few-shot examples of NL→DAG mappings, and a tool/capability registry the planner can query.

**If user asks "Can I do this today with Nexus?"** → Partially. Nexus already has FastAPI backend, Redis for clustering, Ollama/Claude for inference, and MCP integration. The missing piece is the planner agent and workflow execution engine. Recommend building: (1) a tool registry MCP server, (2) a planner subagent with structured output, (3) a workflow executor that maps DAG nodes to subagent dispatches.

**If user asks about pricing/access for Krea P2W** → Krea Nodes requires Pro plan ($35/mo, 20K compute units) or higher. Prompt-to-workflow is part of the Nodes feature. Free tier has limited access; full Nodes access starts at Pro.

## Quick Reference
### Krea AI Quick Facts
| Item | Detail |
|---|---|
| **Company** | Krea AI, San Francisco. Backed by a16z, Bain Capital. $16M seed round |
| **Users** | 30M+ users across 191 countries |
| **Krea Nodes** | Visual node-based workflow builder, 50+ models, infinite canvas |
| **Prompt-to-Workflow** | Announced mid-2025. NL text → executable node graph in seconds |
| **Model Categories** | Generate Image (30+), Generate Video (15+), Edit, Enhance, 3D, Audio, Lipsync, Utility |
| **Pricing (Nodes)** | Pro $35/mo (full Nodes access), Max $105/mo, Business $200/mo |
| **Node Anatomy** | Inputs (left) → Parameters (internal) → Outputs (right) |
| **Key Models** | Flux 2 Pro, ChatGPT Image 1.5, Imagen 4 Ultra, Sora 2, Wan, Krea 1, Seedream 4.5 |

### Claude Code Primitives for Building P2W
| Primitive | Purpose | How to Use |
|---|---|---|
| **Subagents** | Isolated AI workers | `.claude/agents/*.md` with YAML frontmatter |
| **MCP Servers** | External tool integration | `claude mcp add <name> <command>` |
| **Slash Commands** | Reusable triggered workflows | `.claude/commands/*.md` |
| **Hooks** | Lifecycle event automation | In `.claude/settings.json` or frontmatter |
| **Plugins** | Shareable bundles | Combine commands + hooks + skills |
| **Agent Teams** | Multi-session coordination | Separate sessions with shared context |
| **CLAUDE.md** | Project memory/context | Hierarchical: enterprise → user → project → directory |
| **Task Tool** | Spawn subagents | Claude auto-delegates based on description matching |

### Architecture Blueprint for Nexus P2W
```
User NL Description
        ↓
[1. Planner Agent] ← Tool Registry (available MCP tools, subagents, models)
        ↓
[2. DAG Definition] → JSON/YAML schema: {nodes[], edges[], params{}}
        ↓
[3. Validator] → Schema check, dependency resolution, capability verification
        ↓
[4. Execution Engine] → Topological sort → dispatch nodes → collect outputs
        ↓
    Results + Artifacts
```

### Key Commands
```bash
# Claude Code subagent management
/agents                          # Interactive subagent management
claude mcp add <name> <cmd>     # Add MCP server
/context                         # Monitor context window usage

# Create a planner subagent
# ~/.claude/agents/workflow-planner.md
---
description: "Generates executable workflow DAGs from natural language descriptions"
model: sonnet
tools: ["Read", "mcp__nexus__*"]
---
```

### Prompt2DAG Three-Stage Pattern
1. **Analyze** → LLM extracts intent, identifies required tools, determines constraints
2. **Structure** → LLM generates DAG definition with typed nodes/edges/parameters
3. **Synthesize** → Template engine converts DAG definition into executable code/config

## Sources & Notes
**Primary Sources:**
- **Krea AI Official**: [krea.ai/features/nodes](https://www.krea.ai/features/nodes) — Node workflow feature page
- **Krea Nodes Docs**: [docs.krea.ai/user-guide/features/nodes](https://docs.krea.ai/user-guide/features/nodes) — Full technical documentation
- **Krea AI LinkedIn Announcement**: [linkedin.com/posts/krea-ai](https://www.linkedin.com/posts/krea-ai_introducing-prompt-to-workflow-now-you-activity-7427014761759924225-FFWZ) — Official P2W announcement
- **Claude Code Subagents Docs**: [code.claude.com/docs/en/sub-agents](https://code.claude.com/docs/en/sub-agents) — Official subagent documentation
- **Claude Code Full Stack Guide**: [alexop.dev](https://alexop.dev/posts/understanding-claude-code-full-stack/) — Comprehensive feature stack explainer
- **Prompt2DAG Paper**: [arxiv:2509.13487](https://arxiv.org/html/2509.13487v1) — Academic methodology for NL→DAG generation
- **AI Workflow Engine**: [github.com/shwetank-dev/ai-workflow-engine](https://github.com/shwetank-dev/ai-workflow-engine) — Reference OSS implementation of NL→workflow
- **Florent Delavous Analysis**: [linkedin.com/in/florent-delavous](https://www.linkedin.com/posts/florent-delavous_you-can-now-actually-turn-text-prompts-into-activity-7427667982304075776-BPbu) — Production workflow strategy for P2W

**Caveats:**
- Krea's prompt-to-workflow is very new (mid-2025 announcement) with limited public technical documentation on the internal implementation. The NL→node compilation logic is proprietary.
- Claude Code subagents cannot spawn other subagents (no nesting), which limits recursive workflow patterns—agent teams are needed for multi-session coordination.
- Building a robust P2W system requires significant prompt engineering for the planner agent—LLMs can generate invalid DAGs, miss dependencies, or hallucinate tools. A strict schema validator is essential.
- Krea's P2W is domain-specific to creative AI (images/video/3D). Translating the pattern to dev/ops agent orchestration requires a different tool registry and execution model.
- Nexus architecture details are based on stored memory (FastAPI + Redis + Ollama/Claude); specific implementation constraints may vary.
