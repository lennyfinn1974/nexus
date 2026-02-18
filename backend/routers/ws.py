"""WebSocket chat handler — lifecycle management and message dispatch.

All AI execution logic (streaming, tool loops, failover) lives in
core/agent_runner.py and core/agent_attempt.py. This module handles
only: WebSocket lifecycle, conversation management, slash commands,
and dispatching user messages to AgentRunner.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from core.agent_runner import AgentRunner
from core.message_processor import process_message
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websocket_manager import websocket_manager

logger = logging.getLogger("nexus.ws")

router = APIRouter()


def _get_state(ws: WebSocket) -> Any:
    """Access AppState from the WebSocket's app."""
    return ws.app.state.nexus


def _build_help_text() -> str:
    """Build the full /help command reference."""
    return """# Nexus Command Reference

## Model Routing
| Command | Action |
|---------|--------|
| `/code` | Switch to **Claude Code** (agentic + MCP tools) |
| `/local` | Switch to **Ollama** (qwen3-coder, local) |
| `/cloud` | Switch to **Claude API** (cloud) |
| `/auto` | Reset to **auto** routing (local-first) |
| `/model <name>` | Full model command — accepts: `code` `local` `cloud` `claude` `ollama` `agentic` `mcp` `agent` `kimi` `api` `auto` |

## Build Procedures
| Command | Action |
|---------|--------|
| `/sov BLD:APP` | Full dev environment — Claude Code + 4 tmux sessions (server, dev, logs, work) |
| `/sov BLD:DEV` | Start dev servers only (no model switch) |
| `/sov BLD:TEST` | Run test suite in tmux |
| `/sov BLD:STOP` | Tear down all procedure sessions + reset model |
| `/sov SYS:STATUS` | Show running procedures, tmux sessions, model state |
| `/sov ANZ:CODE [path]` | Quick codebase analysis (file count, LOC) |

## Knowledge & Skills
| Command | Action |
|---------|--------|
| `/learn <topic>` | Queue background research task |
| `/skills` | List learned skills |
| `/docs` | List documents in docs directory |
| `/ingest <file>` | Ingest a document (or `/ingest all`) |
| `/catalog search <q>` | Search skill catalog |
| `/catalog install <id>` | Install a catalog skill |
| `/install-skill owner/repo` | Install skill from GitHub |

## System
| Command | Action |
|---------|--------|
| `/status` | System status overview |
| `/plugins` | List loaded plugins and their tools |
| `/tasks` | Show task queue |
| `/exec python\\|bash <code>` | Execute code |
| `/clear-board` | Clear all KanBan work items |
| `/help` | This help message |

## Sub-Agents
| Command | Action |
|---------|--------|
| `/multi research <q1> \\| <q2>` | Parallel research across topics |
| `/multi review <task>` | Build + Review (builder → reviewer) |
| `/multi code-review <task>` | Claude Code build + review (full MCP) |
| `/multi verify <claim>` | Independent verification (2 verifiers) |

## Claude Code Sessions
| Command | Action |
|---------|--------|
| `/cc <prompt>` | Start a new interactive Claude Code session |
| `/cc send <id> <msg>` | Send follow-up message to running session |
| `/cc list` | List active Claude Code sessions |
| `/cc stop [id]` | Stop session(s) — all if no ID given |

## Plugin Commands
| Command | Action |
|---------|--------|
| `/sov <CMD:SUB>` | Sovereign procedure commands |
| `/terminal <cmd>` | Execute in Terminal.app |
| `/tmux <action>` | tmux session management |
| `/claude-code <prompt>` | Start Claude Code session (legacy) |
| `/workspace` | Show workspace info |

## Tips
- Use `@skill-name` in messages to boost that skill's actions into the tool set
- All tmux sessions are controllable by Nexus regardless of which model is active
- Claude Code has access to **95 MCP tools** covering terminal, web, files, macOS, memory, and more"""


@router.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    s = _get_state(ws)

    # ── Origin check ──
    allowed_origins = s.allowed_origins
    origin = ws.headers.get("origin")
    if origin and origin not in allowed_origins:
        logger.warning(f"WebSocket rejected: origin {origin!r} not in ALLOWED_ORIGINS")
        await ws.close(code=4003, reason="Origin not allowed")
        return

    # ── Reconnection ──
    session_id = ws.query_params.get("session_id")
    ws_id = await websocket_manager.connect(ws, session_id)

    current_runner: AgentRunner | None = None

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "pong":
                continue

            # ── Abort running request ──
            if msg.get("type") == "abort":
                if current_runner:
                    current_runner.abort.set()
                    logger.info(f"[{ws_id}] Abort requested")
                continue

            # ── Claude Code session follow-up ──
            if msg.get("type") == "cc_session_send":
                session_id = msg.get("session_id", "")
                text_payload = msg.get("text", "")
                if session_id and text_payload and hasattr(s, "claude_session_manager") and s.claude_session_manager:
                    ok = await s.claude_session_manager.send_message(session_id, text_payload)
                    if not ok:
                        await websocket_manager.send_to_client(ws_id, {
                            "type": "cc_session_error",
                            "session_id": session_id,
                            "content": "Session not found or not running",
                        })
                continue

            # ── Switch conversation ──
            if msg.get("type") == "set_conversation":
                await _handle_set_conversation(ws_id, msg, s)
                continue

            text = msg.get("text", "").strip()
            if not text:
                continue

            text_lower = text.lower().split()[0] if text else ""

            # ── /help ──
            if text_lower == "/help":
                await websocket_manager.send_to_client(
                    ws_id, {"type": "system", "content": _build_help_text()}
                )
                continue

            # ── Quick model shortcuts ──
            QUICK_MODEL_CMDS = {
                "/code": "claude_code", "/agent": "claude_code", "/agentic": "claude_code",
                "/local": "ollama", "/kimi": "ollama",
                "/cloud": "claude", "/api": "claude",
                "/auto": None,
            }
            if text_lower in QUICK_MODEL_CMDS:
                force = QUICK_MODEL_CMDS[text_lower]
                if force:
                    labels = {"claude": "Claude API", "ollama": "Ollama (local)", "claude_code": "Claude Code (agentic)"}
                    websocket_manager.update_session_data(ws_id, {"force_model": force})
                    await websocket_manager.send_to_client(
                        ws_id, {"type": "system", "content": f"⚡ Model → {labels[force]}"}
                    )
                else:
                    websocket_manager.update_session_data(ws_id, {"force_model": None})
                    await websocket_manager.send_to_client(ws_id, {"type": "system", "content": "⚡ Model → auto (local-first)"})
                continue

            # ── Model override (full command) ──
            if text.startswith("/model"):
                choice = text[6:].strip().lower()
                MODEL_ALIASES = {
                    "claude": "claude",
                    "cloud": "claude",
                    "api": "claude",
                    "local": "ollama",
                    "ollama": "ollama",
                    "kimi": "ollama",
                    "code": "claude_code",
                    "claude_code": "claude_code",
                    "claude-code": "claude_code",
                    "agentic": "claude_code",
                    "mcp": "claude_code",
                    "agent": "claude_code",
                }
                if choice in MODEL_ALIASES:
                    force = MODEL_ALIASES[choice]
                    labels = {"claude": "Claude API", "ollama": "Ollama (local)", "claude_code": "Claude Code (agentic)"}
                    websocket_manager.update_session_data(ws_id, {"force_model": force})
                    await websocket_manager.send_to_client(
                        ws_id, {"type": "system", "content": f"⚡ Model set to: {labels[force]}"}
                    )
                elif choice in ("auto", ""):
                    websocket_manager.update_session_data(ws_id, {"force_model": None})
                    await websocket_manager.send_to_client(ws_id, {"type": "system", "content": "⚡ Model set to: auto (local-first)"})
                else:
                    models_help = "Available: `local` `claude` `code` `auto` (or aliases: `cloud` `api` `kimi` `agentic` `mcp` `agent`)"
                    await websocket_manager.send_to_client(ws_id, {"type": "system", "content": f"Unknown model '{choice}'. {models_help}"})
                continue

            # ── /clear-board — Purge KanBan work items ──
            if text_lower in ("/clear-board", "/clearboard", "/clear-kanban"):
                from core.work_registry import work_registry
                count = await work_registry.clear_all()
                await websocket_manager.send_to_client(
                    ws_id,
                    {"type": "system", "content": f"🧹 KanBan board cleared — {count} work items removed."},
                )
                continue

            # ── /cc — Claude Code interactive sessions ──
            if text_lower == "/cc" or text.startswith("/cc "):
                await _handle_cc_command(ws_id, text, s)
                continue

            # ── /multi — sub-agent orchestration ──
            if text_lower == "/multi" or text.startswith("/multi "):
                await _handle_multi_command(ws_id, text, s)
                continue

            # ── Slash commands ──
            if text.startswith("/"):
                session_data = websocket_manager.get_session_data(ws_id)
                force_model = session_data.get("force_model") if session_data else None
                response = await process_message(
                    ws_id,
                    text,
                    cfg=s.cfg,
                    db=s.db,
                    skills_engine=s.skills_engine,
                    model_router=s.model_router,
                    task_queue=s.task_queue,
                    plugin_manager=s.plugin_manager,
                    tool_executor=getattr(s, "tool_executor", None),
                    force_model=force_model,
                    skill_catalog=getattr(s, "skill_catalog", None),
                )
                await websocket_manager.send_to_client(
                    ws_id, {"type": "message", "content": response, "model": "system"}
                )
                continue

            # ── Ensure conversation exists ──
            session_data = websocket_manager.get_session_data(ws_id)
            conv_id = session_data.get("conv_id") if session_data else None
            force_model = session_data.get("force_model") if session_data else None

            if not conv_id:
                conv_id = f"conv-{uuid.uuid4().hex[:8]}"
                await s.db.create_conversation(conv_id, title=text[:50])
                websocket_manager.update_session_data(ws_id, {"conv_id": conv_id})
                await websocket_manager.send_to_client(
                    ws_id,
                    {
                        "type": "conversation_set",
                        "conv_id": conv_id,
                        "title": text[:50],
                    },
                )

            try:
                current_runner = await _handle_user_message(ws_id, text, conv_id, force_model, s)
            except Exception as e:
                logger.error(f"Message processing error: {e}", exc_info=True)
                await websocket_manager.send_to_client(ws_id, {"type": "error", "content": f"Error: {e}"})
            finally:
                current_runner = None

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {ws_id}")
        await websocket_manager.disconnect(ws_id, keep_session=True)
    except Exception as e:
        logger.error(f"WebSocket fatal error: {e}", exc_info=True)
        try:
            await websocket_manager.send_to_client(ws_id, {"type": "error", "content": f"Server error: {e}"})
        except Exception:
            pass
        finally:
            await websocket_manager.disconnect(ws_id, keep_session=True)


async def _handle_multi_command(ws_id: str, text: str, s: Any) -> None:
    """Handle /multi slash command for explicit sub-agent orchestration.

    Usage:
        /multi research <query1> | <query2> | ...
        /multi review <task>
        /multi code-review <task>
        /multi verify <claim>
    """
    from core.sub_agent import OrchestrationStrategy, SubAgentOrchestrator

    arg = text[6:].strip()  # strip "/multi"
    if not arg:
        await websocket_manager.send_to_client(
            ws_id,
            {
                "type": "system",
                "content": (
                    "**Sub-Agent Commands:**\n\n"
                    "| Command | Description |\n"
                    "|---------|-------------|\n"
                    "| `/multi research <q1> \\| <q2> \\| ...` | Parallel research across topics |\n"
                    "| `/multi review <task>` | Build + Review (builder→reviewer) |\n"
                    "| `/multi code-review <task>` | Claude Code build + review (full MCP) |\n"
                    "| `/multi verify <claim>` | Independent verification (2 verifiers) |\n"
                ),
            },
        )
        return

    cfg = s.cfg

    # Check master switch
    if not cfg.get_bool("SUB_AGENT_ENABLED", True):
        await websocket_manager.send_to_client(
            ws_id,
            {"type": "system", "content": "Sub-agent system is disabled. Enable it in Admin → Models settings."},
        )
        return

    # Parse sub-command
    parts = arg.split(None, 1)
    sub_cmd = parts[0].lower()
    payload = parts[1] if len(parts) > 1 else ""

    if not payload:
        await websocket_manager.send_to_client(
            ws_id,
            {"type": "system", "content": f"Usage: `/multi {sub_cmd} <text>`"},
        )
        return

    # Ensure conversation exists
    session_data = websocket_manager.get_session_data(ws_id)
    conv_id = session_data.get("conv_id") if session_data else None
    if not conv_id:
        conv_id = f"conv-{uuid.uuid4().hex[:8]}"
        await s.db.create_conversation(conv_id, title=payload[:50])
        websocket_manager.update_session_data(ws_id, {"conv_id": conv_id})
        await websocket_manager.send_to_client(
            ws_id,
            {"type": "conversation_set", "conv_id": conv_id, "title": payload[:50]},
        )

    # Save user message
    await s.db.add_message(conv_id, "user", text)

    # Build conversation context
    from core.context_manager import build_conversation_context

    messages = await build_conversation_context(
        db=s.db,
        conv_id=conv_id,
        new_user_message="",
        model_router=s.model_router,
        system_prompt="",
    )

    # Build orchestration from sub-command
    if sub_cmd == "research":
        queries = [q.strip() for q in payload.split("|") if q.strip()]
        if len(queries) < 2:
            # Try splitting on "and"
            queries = [q.strip() for q in payload.split(" and ") if q.strip() and len(q.strip()) > 10]
        if len(queries) < 2:
            queries = [payload]
        orchestration = OrchestrationStrategy.parallel_research(queries, cfg)
    elif sub_cmd == "review":
        orchestration = OrchestrationStrategy.build_review(payload, cfg=cfg)
    elif sub_cmd in ("code-review", "codereview"):
        orchestration = OrchestrationStrategy.build_review_code(payload, cfg=cfg)
    elif sub_cmd == "verify":
        orchestration = OrchestrationStrategy.verify(payload, cfg=cfg)
    else:
        await websocket_manager.send_to_client(
            ws_id,
            {"type": "system", "content": f"Unknown sub-command: `{sub_cmd}`. Use: `research`, `review`, `code-review`, `verify`"},
        )
        return

    # Notify and execute
    agent_count = len(orchestration.specs)
    await websocket_manager.send_to_client(
        ws_id,
        {"type": "system", "content": f"Launching {agent_count} sub-agents ({sub_cmd})..."},
    )

    parent_abort = asyncio.Event()
    orchestrator = SubAgentOrchestrator(
        state=s,
        ws_id=ws_id,
        conv_id=conv_id,
        parent_abort=parent_abort,
        messages=messages,
        cfg=cfg,
    )

    try:
        result = await orchestrator.execute(orchestration)
        # Save result as assistant message
        await s.db.add_message(conv_id, "assistant", result, model_used="multi-agent")
        # Send final response
        await websocket_manager.send_to_client(
            ws_id,
            {"type": "stream_start", "model": "multi-agent"},
        )
        await websocket_manager.send_to_client(
            ws_id,
            {"type": "stream_chunk", "content": result},
        )
        await websocket_manager.send_to_client(
            ws_id,
            {"type": "stream_end"},
        )
    except Exception as e:
        logger.error(f"[{ws_id}] /multi command error: {e}", exc_info=True)
        await websocket_manager.send_to_client(
            ws_id,
            {"type": "error", "content": f"Sub-agent orchestration failed: {e}"},
        )


async def _handle_cc_command(ws_id: str, text: str, s: Any) -> None:
    """Handle /cc slash command for Claude Code interactive sessions.

    Usage:
        /cc <prompt>             — start new session
        /cc send <id> <message>  — follow-up to running session
        /cc list                 — list active sessions
        /cc stop [id]            — stop session(s)
    """
    mgr = getattr(s, "claude_session_manager", None)
    if not mgr:
        await websocket_manager.send_to_client(
            ws_id, {"type": "system", "content": "Claude Code session manager not available."}
        )
        return

    arg = text[3:].strip()  # strip "/cc"
    if not arg:
        await websocket_manager.send_to_client(
            ws_id,
            {
                "type": "system",
                "content": (
                    "**Claude Code Sessions:**\n\n"
                    "| Command | Description |\n"
                    "|---------|-------------|\n"
                    "| `/cc <prompt>` | Start a new Claude Code session |\n"
                    "| `/cc send <id> <msg>` | Send follow-up to a session |\n"
                    "| `/cc list` | List active sessions |\n"
                    "| `/cc stop [id]` | Stop session(s) |\n"
                ),
            },
        )
        return

    parts = arg.split(None, 1)
    sub_cmd = parts[0].lower()
    payload = parts[1] if len(parts) > 1 else ""

    if sub_cmd == "list":
        sessions = mgr.list_sessions()
        if not sessions:
            await websocket_manager.send_to_client(
                ws_id, {"type": "system", "content": "No active Claude Code sessions."}
            )
        else:
            lines = []
            for sess in sessions:
                status_icon = "🟢" if sess["status"] == "running" else "✅" if sess["status"] == "completed" else "❌"
                lines.append(
                    f"| `{sess['id']}` | {status_icon} {sess['status']} | {sess['name']} | ${sess.get('cost_usd', 0):.4f} |"
                )
            table = (
                "**Claude Code Sessions:**\n\n"
                "| ID | Status | Name | Cost |\n"
                "|-----|--------|------|------|\n"
                + "\n".join(lines)
            )
            await websocket_manager.send_to_client(ws_id, {"type": "system", "content": table})
        return

    if sub_cmd == "stop":
        if payload:
            ok = await mgr.stop_session(payload.strip())
            msg_text = f"✅ Session `{payload.strip()}` stopped." if ok else f"❌ Session `{payload.strip()}` not found."
        else:
            # Stop all running sessions
            sessions = mgr.list_sessions()
            stopped = 0
            for sess in sessions:
                if sess["status"] == "running":
                    await mgr.stop_session(sess["id"])
                    stopped += 1
            msg_text = f"✅ Stopped {stopped} session(s)." if stopped > 0 else "No running sessions to stop."
        await websocket_manager.send_to_client(ws_id, {"type": "system", "content": msg_text})
        return

    if sub_cmd == "send":
        send_parts = payload.split(None, 1) if payload else []
        if len(send_parts) < 2:
            await websocket_manager.send_to_client(
                ws_id, {"type": "system", "content": "Usage: `/cc send <session_id> <message>`"}
            )
            return
        sid, msg_text = send_parts
        ok = await mgr.send_message(sid, msg_text)
        if ok:
            await websocket_manager.send_to_client(
                ws_id, {"type": "system", "content": f"📨 Sent to session `{sid}`"}
            )
        else:
            await websocket_manager.send_to_client(
                ws_id, {"type": "cc_session_error", "session_id": sid, "content": "Session not found or not running"}
            )
        return

    # Default: start a new session with the full arg as prompt
    prompt = arg
    session_data = websocket_manager.get_session_data(ws_id)
    conv_id = session_data.get("conv_id") if session_data else None

    try:
        session = await mgr.create_session(
            prompt=prompt,
            directory=os.path.expanduser("~"),
            ws_id=ws_id,
            conv_id=conv_id,
        )
        await websocket_manager.send_to_client(
            ws_id,
            {
                "type": "system",
                "content": f"🚀 Claude Code session started: `{session.id}` — *{session.name}*\n\nOutput will stream below.",
            },
        )
    except Exception as e:
        logger.error(f"Failed to create CC session: {e}", exc_info=True)
        await websocket_manager.send_to_client(
            ws_id, {"type": "error", "content": f"Failed to start Claude Code session: {e}"}
        )


async def _handle_set_conversation(ws_id: str, msg: dict, s: Any) -> None:
    """Handle set_conversation message type."""
    new_id = msg.get("conv_id")
    if new_id:
        conv = await s.db.get_conversation(new_id)
        if conv:
            websocket_manager.update_session_data(ws_id, {"conv_id": new_id})
            logger.info(f"[{ws_id}] Switched to conversation {new_id}")

            # ── Cluster: touch session (marks it active, reads context) ──
            cm = getattr(s, "cluster_manager", None)
            if cm and cm.is_active:
                try:
                    await cm.working_memory.touch_session(new_id)
                except Exception:
                    pass
            await websocket_manager.send_to_client(
                ws_id,
                {
                    "type": "conversation_set",
                    "conv_id": new_id,
                    "title": conv["title"],
                },
            )
        else:
            logger.warning(f"[{ws_id}] Conversation {new_id} not found, creating new")
            conv_id = f"conv-{uuid.uuid4().hex[:8]}"
            await s.db.create_conversation(conv_id, title="New Conversation")
            websocket_manager.update_session_data(ws_id, {"conv_id": conv_id})
            await websocket_manager.send_to_client(
                ws_id,
                {
                    "type": "conversation_set",
                    "conv_id": conv_id,
                    "title": "New Conversation",
                },
            )
    else:
        conv_id = f"conv-{uuid.uuid4().hex[:8]}"
        await s.db.create_conversation(conv_id, title="New Conversation")
        websocket_manager.update_session_data(ws_id, {"conv_id": conv_id})
        logger.info(f"[{ws_id}] Created new conversation {conv_id}")
        await websocket_manager.send_to_client(
            ws_id,
            {
                "type": "conversation_set",
                "conv_id": conv_id,
                "title": "New Conversation",
            },
        )


async def _handle_user_message(
    ws_id: str,
    text: str,
    conv_id: str,
    force_model: str | None,
    s: Any,
) -> AgentRunner:
    """Save user message, run AgentRunner, save assistant response.

    Returns the runner so the caller can set abort if needed.
    """
    await s.db.add_message(conv_id, "user", text)

    # Auto-title after first message
    msg_count = await s.db.get_message_count(conv_id)
    if msg_count == 1:
        title = text[:60].strip()
        if len(text) > 60:
            title = title.rsplit(" ", 1)[0] + "..."
        await s.db.rename_conversation(conv_id, title)
        await websocket_manager.send_to_client(
            ws_id,
            {
                "type": "conversation_renamed",
                "conv_id": conv_id,
                "title": title,
            },
        )

    # ── Cluster: claim work + store session ──
    cm = getattr(s, "cluster_manager", None)
    if cm and cm.is_active:
        try:
            await cm.working_memory.claim_work(conv_id, task_type="conversation")
            await cm.store_session(conv_id, {
                "ws_id": ws_id,
                "message_count": msg_count,
                "force_model": force_model,
                "last_user_message": text[:200],
            })
        except Exception as e:
            logger.debug(f"Cluster session write failed (non-blocking): {e}")

    # Run the agent
    runner = AgentRunner(s, ws_id, conv_id, text, force_model)
    final_response = ""
    try:
        final_response = await runner.run()
        await s.db.add_message(conv_id, "assistant", final_response, model_used="agent")
    except Exception as e:
        # Even on error, capture any partial response for memory hooks
        final_response = getattr(runner, "_last_response", "") or ""
        logger.warning(f"Agent run failed (memory hooks will still fire): {e}")
        raise
    finally:
        # ── Post-response hooks (always run, even on error) ──

        # Cluster: update session + release work
        if cm and cm.is_active:
            try:
                new_count = await s.db.get_message_count(conv_id)
                await cm.working_memory.update_session(conv_id, {
                    "message_count": new_count,
                    "last_model": getattr(runner, "_last_model", "unknown"),
                    "last_response_len": len(final_response),
                })
                await cm.working_memory.release_work(conv_id)
            except Exception as e2:
                logger.debug(f"Cluster session update failed (non-blocking): {e2}")

        # Only run memory hooks if we have a meaningful response
        if final_response and len(final_response) > 20:
            # Run all memory hooks in a single sequenced background task.
            # This prevents 4 parallel embedding calls from competing with
            # the user's next inference request on the Ollama slot.
            passive_mem = getattr(s, "passive_memory", None)
            rag_pipeline = getattr(s, "rag_pipeline", None)
            knowledge_graph = getattr(s, "knowledge_graph", None)
            auto_ingest = s.cfg.get_bool("RAG_AUTO_INGEST", True) if s.cfg else True
            attempt = getattr(runner, "_attempt", None)
            web_results = getattr(attempt, "web_results", []) if attempt else []

            asyncio.create_task(
                _run_memory_hooks_sequenced(
                    passive_mem=passive_mem,
                    rag_pipeline=rag_pipeline if auto_ingest else None,
                    knowledge_graph=knowledge_graph,
                    conv_id=conv_id,
                    text=text,
                    final_response=final_response,
                    web_results=web_results,
                    model_router=state.model_router,
                )
            )
        else:
            logger.info(f"Memory hooks skipped: response too short ({len(final_response)} chars)")

    return runner


async def _run_memory_hooks_sequenced(
    passive_mem,
    rag_pipeline,
    knowledge_graph,
    conv_id: str,
    text: str,
    final_response: str,
    web_results: list,
    model_router=None,
):
    """Run all post-response memory hooks sequentially with delays.

    Previously these ran as 4 parallel tasks, all hitting Ollama's embedding
    endpoint at once and competing with the user's next inference request.
    Now they run one at a time with a 2-second initial delay so the next
    user prompt gets priority on the Ollama slot.
    """
    # Wait 2s before starting — let user's next prompt claim the Ollama slot first
    await asyncio.sleep(2)

    # 1. Passive memory (regex only, no LLM/embedding — fast)
    if passive_mem:
        await _extract_passive_memory(passive_mem, conv_id, text, final_response)

    # 2. RAG ingest (calls embedding service — one Ollama round-trip)
    if rag_pipeline and rag_pipeline.is_active:
        await _rag_ingest(rag_pipeline, conv_id, text, final_response)
        # Small gap so embedding model can unload before next call
        await asyncio.sleep(0.5)

    # 3. Web content memory (calls embedding service if web results exist)
    if rag_pipeline and rag_pipeline.is_active and web_results:
        await _web_memory_ingest(rag_pipeline, conv_id, text, web_results)
        await asyncio.sleep(0.5)

    # 4. Knowledge graph (regex or LLM extraction)
    if knowledge_graph:
        await _kg_extract(knowledge_graph, conv_id, text, final_response, model_router)


async def _extract_passive_memory(extractor, conv_id: str, user_msg: str, assistant_msg: str):
    """Background task: extract learnings from the conversation exchange."""
    try:
        learned = await extractor.extract_and_store(conv_id, user_msg, assistant_msg)
        total = sum(len(v) for v in learned.values())
        if total > 0:
            logger.info(f"Passive memory: learned {total} items from {conv_id[:8]}")
    except Exception as e:
        logger.warning(f"Passive memory extraction failed: {e}")


async def _rag_ingest(rag_pipeline, conv_id: str, user_msg: str, assistant_msg: str):
    """Background task: ingest conversation turn into RAG memory index."""
    try:
        memory_id = await rag_pipeline.ingest_conversation(
            conv_id=conv_id,
            user_message=user_msg,
            assistant_response=assistant_msg,
        )
        if memory_id:
            logger.info(f"RAG ingested: {memory_id} from {conv_id[:8]}")
        else:
            logger.info(f"RAG ingest skipped for {conv_id[:8]} (too short or command)")
    except Exception as e:
        logger.warning(f"RAG ingest failed: {e}", exc_info=True)


async def _web_memory_ingest(rag_pipeline, conv_id: str, user_msg: str, web_results: list):
    """Background task: ingest condensed web search results into RAG memory."""
    try:
        memory_id = await rag_pipeline.ingest_web_content(
            user_query=user_msg,
            web_results=web_results,
            conv_id=conv_id,
        )
        if memory_id:
            logger.info(f"Web memory ingested: {memory_id} ({len(web_results)} web results from {conv_id[:8]})")
    except Exception as e:
        logger.warning(f"Web memory ingest failed: {e}", exc_info=True)


async def _kg_extract(knowledge_graph, conv_id: str, user_msg: str, assistant_msg: str, model_router=None):
    """Background task: extract entities and relationships into knowledge graph.

    Uses LLM-assisted extraction for rich content (>200 chars) and falls back
    to regex for short/simple messages. LLM extraction also detects Contradicts
    edges (superseded facts).
    """
    try:
        combined = f"{user_msg}\n\n{assistant_msg}"

        # Use LLM extraction for rich content when model_router is available
        if model_router and len(combined.strip()) > 200:
            result = await knowledge_graph.extract_with_llm(
                text=combined,
                model_router=model_router,
                source_conv=conv_id,
            )
        else:
            result = await knowledge_graph.extract_and_store(
                text=combined,
                source_conv=conv_id,
            )

        entity_count = len(result.get("entities", []))
        rel_count = len(result.get("relationships", []))
        method = result.get("method", "regex")
        if entity_count > 0:
            logger.info(
                f"KG extracted ({method}): {entity_count} entities, {rel_count} relationships "
                f"from {conv_id[:8]}"
            )
    except Exception as e:
        logger.warning(f"KG extraction failed: {e}", exc_info=True)
