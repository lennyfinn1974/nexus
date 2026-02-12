"""Public REST API endpoints."""

from __future__ import annotations

import json
import logging
import os
import secrets
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from core.exceptions import PathAccessDeniedError
from core.security import validate_path
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from schemas.api import (
    ConversationCreate,
    ConversationUpdate,
    StatusResponse,
)
from skills.ingest import scan_directory

logger = logging.getLogger("nexus.api")

router = APIRouter(prefix="/api", tags=["api"])


def _state(request: Request) -> Any:
    """Access AppState from the request."""
    return request.app.state.nexus


# ── Setup (unauthenticated — needed for first-boot wizard) ──


@router.get("/setup/status")
async def api_setup_status(request: Request):
    """Check whether initial setup is complete. No auth required."""
    s = _state(request)
    cfg = s.cfg
    has_admin_key = bool(cfg.admin_access_key) or bool(os.environ.get("ADMIN_API_KEY", "").replace("change-me-to-a-random-secret", ""))
    has_model = bool(cfg.anthropic_api_key and cfg.anthropic_api_key != "sk-ant-your-key-here") or bool(cfg.ollama_base_url)
    return JSONResponse({
        "setup_complete": cfg.setup_complete,
        "has_admin_key": has_admin_key,
        "has_model": has_model,
        "has_telegram": cfg.has_telegram,
    })


# ── Status & Health ──


@router.get("/status", response_model=StatusResponse)
async def api_status(request: Request):
    s = _state(request)
    return StatusResponse(
        models=s.model_router.status,
        tasks_active=s.task_queue.active_count,
        skills_count=len(await s.skills_engine.list_skills()),
        plugins=s.plugin_manager.status,
    )


@router.get("/health")
async def api_health(request: Request):
    """Comprehensive health check endpoint."""
    s = _state(request)
    health_status: dict[str, Any] = {"healthy": True, "timestamp": time.time(), "checks": {}}

    # Database
    try:
        await s.db.execute_query("SELECT 1")
        health_status["checks"]["database"] = {"status": "healthy", "details": "Connection successful"}
    except Exception as e:
        health_status["checks"]["database"] = {"status": "unhealthy", "details": f"Database error: {e}"}
        health_status["healthy"] = False

    # Models
    if s.model_router:
        ms = s.model_router.status
        claude_ok = ms.get("claude_available", False)
        ollama_ok = ms.get("ollama_available", False)
        health_status["checks"]["models"] = {
            "status": "healthy" if (claude_ok or ollama_ok) else "unhealthy",
            "claude": "available" if claude_ok else "unavailable",
            "ollama": "available" if ollama_ok else "unavailable",
        }
        if not (claude_ok or ollama_ok):
            health_status["healthy"] = False
    else:
        health_status["checks"]["models"] = {"status": "unhealthy", "details": "Model router not initialized"}
        health_status["healthy"] = False

    # Plugins
    plugin_errors = 0
    for _name, plugin in s.plugin_manager.plugins.items():
        if hasattr(plugin, "health_check"):
            try:
                plugin_health = await plugin.health_check()
                if plugin_health.get("status") != "ok":
                    plugin_errors += 1
            except Exception:
                plugin_errors += 1

    health_status["checks"]["plugins"] = {
        "status": "healthy" if plugin_errors == 0 else "degraded",
        "total": len(s.plugin_manager.plugins),
        "errors": plugin_errors,
    }

    # Filesystem
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=True) as f:
            f.write("test")
            f.flush()
        health_status["checks"]["filesystem"] = {"status": "healthy", "details": "Read/write successful"}
    except Exception as e:
        health_status["checks"]["filesystem"] = {"status": "unhealthy", "details": f"File system error: {e}"}
        health_status["healthy"] = False

    # Memory
    try:
        import psutil

        memory = psutil.virtual_memory()
        pct = memory.percent
        health_status["checks"]["memory"] = {
            "status": "healthy" if pct < 90 else "warning" if pct < 95 else "critical",
            "usage_percent": pct,
            "available_mb": memory.available / (1024 * 1024),
        }
        if pct > 95:
            health_status["healthy"] = False
    except Exception as e:
        health_status["checks"]["memory"] = {"status": "unhealthy", "details": f"Memory check error: {e}"}

    return JSONResponse(health_status, status_code=200 if health_status["healthy"] else 503)


# ── Plugins ──


@router.get("/plugins")
async def api_plugins(request: Request):
    s = _state(request)
    return JSONResponse({"plugins": s.plugin_manager.status, "commands": s.plugin_manager.list_commands()})


# ── Skills ──


@router.get("/skills")
async def api_skills(request: Request):
    s = _state(request)
    return JSONResponse(await s.skills_engine.list_skills())


@router.delete("/skills/{skill_id}")
async def api_delete_skill(skill_id: str, request: Request):
    s = _state(request)
    await s.skills_engine.delete_skill(skill_id)
    return JSONResponse({"deleted": skill_id})


# ── Tasks ──


@router.get("/tasks")
async def api_tasks(request: Request):
    s = _state(request)
    return JSONResponse(await s.task_queue.list_tasks())


# ── Conversations ──


@router.get("/conversations/search")
async def api_search_conversations(request: Request, q: str = "", limit: int = 20):
    """Full-text search across all conversation messages."""
    s = _state(request)
    if not q.strip():
        raise HTTPException(400, "Query parameter 'q' is required")
    results = await s.db.search_messages(q, limit=min(limit, 50))
    return JSONResponse({"query": q, "count": len(results), "results": results})


@router.get("/conversations")
async def api_conversations(request: Request):
    s = _state(request)
    return JSONResponse(await s.db.list_conversations())


@router.post("/conversations")
async def api_create_conversation(body: ConversationCreate, request: Request):
    s = _state(request)
    conv_id = f"conv-{uuid.uuid4().hex[:8]}"
    conv = await s.db.create_conversation(conv_id, title=body.title)
    return JSONResponse(conv)


@router.get("/conversations/{conv_id}/messages")
async def api_conversation_messages(conv_id: str, request: Request):
    s = _state(request)
    conv = await s.db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    messages = await s.db.get_conversation_messages(conv_id, limit=200)
    return JSONResponse({"conversation": conv, "messages": messages})


@router.put("/conversations/{conv_id}")
async def api_rename_conversation(conv_id: str, body: ConversationUpdate, request: Request):
    s = _state(request)
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "Title required")
    await s.db.rename_conversation(conv_id, title)
    return JSONResponse({"id": conv_id, "title": title})


@router.get("/conversations/{conv_id}/export")
async def api_export_conversation(conv_id: str, request: Request, format: str = "markdown"):
    """Export a conversation as Markdown or JSON download."""
    s = _state(request)
    conv = await s.db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    messages = await s.db.get_conversation_messages(conv_id, limit=9999)
    summary = await s.db.get_conversation_summary(conv_id)

    if format == "json":
        export_data = {
            "conversation": conv,
            "summary": summary,
            "messages": messages,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        content = json.dumps(export_data, indent=2, default=str)
        filename = f"{conv_id}.json"
        media_type = "application/json"
    else:
        lines = [f"# {conv.get('title', 'Untitled Conversation')}\n"]
        lines.append(f"**ID:** {conv_id}  ")
        lines.append(f"**Created:** {conv.get('created_at', 'N/A')}  ")
        lines.append(f"**Updated:** {conv.get('updated_at', 'N/A')}\n")
        if summary:
            lines.append("## Summary\n")
            lines.append(f"{summary}\n")
        lines.append("## Messages\n")
        for msg in messages:
            role = msg.get("role", "unknown").capitalize()
            model = msg.get("model_used", "")
            ts = msg.get("created_at", "")
            model_tag = f" *({model})*" if model else ""
            lines.append(f"### {role}{model_tag}")
            lines.append(f"*{ts}*\n")
            lines.append(f"{msg.get('content', '')}\n")
            lines.append("---\n")
        content = "\n".join(lines)
        filename = f"{conv_id}.md"
        media_type = "text/markdown"

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/conversations/{conv_id}")
async def api_delete_conversation(conv_id: str, request: Request):
    s = _state(request)
    await s.db.delete_conversation(conv_id)
    return JSONResponse({"deleted": conv_id})


# ── File Uploads ──

import mimetypes

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Max 50MB
MAX_UPLOAD_SIZE = 50 * 1024 * 1024

ALLOWED_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml",
    "application/pdf",
    "text/plain", "text/markdown", "text/csv",
    "application/json",
    "application/zip",
}


@router.post("/upload")
async def api_upload_file(request: Request, file: UploadFile = File(...)):
    """Upload a file. Returns file metadata and URL for referencing in chat."""
    # Validate content type
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"File type not allowed: {content_type}")

    # Read and check size
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File too large. Max {MAX_UPLOAD_SIZE // (1024*1024)}MB")

    # Generate unique filename
    ext = os.path.splitext(file.filename or "file")[1] or ".bin"
    file_id = f"{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(UPLOAD_DIR, file_id)

    with open(file_path, "wb") as f:
        f.write(content)

    logger.info(f"File uploaded: {file.filename} -> {file_id} ({len(content)} bytes)")

    return JSONResponse({
        "id": file_id,
        "filename": file.filename,
        "content_type": content_type,
        "size": len(content),
        "url": f"/api/uploads/{file_id}",
    })


@router.get("/uploads/{file_id}")
async def api_get_upload(file_id: str):
    """Serve an uploaded file."""
    file_path = os.path.join(UPLOAD_DIR, file_id)
    if not os.path.isfile(file_path):
        raise HTTPException(404, "File not found")

    content_type = mimetypes.guess_type(file_id)[0] or "application/octet-stream"
    from fastapi.responses import FileResponse
    return FileResponse(file_path, media_type=content_type)


# ── Plans ──


class PlanCreateRequest(BaseModel):
    request: str
    conv_id: str = ""


class PlanActionRequest(BaseModel):
    step_id: str = ""
    result: str = ""
    error: str = ""


@router.post("/plans")
async def api_create_plan(body: PlanCreateRequest, request: Request):
    """Create a new execution plan from a user request."""
    from core.planner import PlanExecutor
    s = _state(request)
    executor = PlanExecutor(model_router=s.model_router, task_queue=s.task_queue)
    plan = await executor.create_plan(body.request, conv_id=body.conv_id)
    return JSONResponse(plan.to_dict())


@router.get("/plans")
async def api_list_plans(request: Request, conv_id: str = ""):
    """List all plans, optionally filtered by conversation."""
    from core.planner import PlanExecutor
    executor = PlanExecutor()
    return JSONResponse(executor.list_plans(conv_id=conv_id))


@router.get("/plans/{plan_id}")
async def api_get_plan(plan_id: str):
    """Get a specific plan with its current status."""
    from core.planner import PlanExecutor
    executor = PlanExecutor()
    plan = executor.get_plan(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    return JSONResponse(plan.to_dict())


@router.post("/plans/{plan_id}/approve")
async def api_approve_plan(plan_id: str):
    """Approve a draft plan for execution."""
    from core.planner import PlanExecutor
    executor = PlanExecutor()
    try:
        plan = await executor.approve_plan(plan_id)
        return JSONResponse(plan.to_dict())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/plans/{plan_id}/cancel")
async def api_cancel_plan(plan_id: str):
    """Cancel a plan."""
    from core.planner import PlanExecutor
    executor = PlanExecutor()
    try:
        plan = await executor.cancel_plan(plan_id)
        return JSONResponse(plan.to_dict())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/plans/{plan_id}/steps/{step_id}/start")
async def api_start_step(plan_id: str, step_id: str):
    """Mark a plan step as running."""
    from core.planner import PlanExecutor
    executor = PlanExecutor()
    try:
        step = await executor.start_step(plan_id, step_id)
        return JSONResponse(step.to_dict())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/plans/{plan_id}/steps/{step_id}/complete")
async def api_complete_step(plan_id: str, step_id: str, body: PlanActionRequest):
    """Mark a plan step as completed with result."""
    from core.planner import PlanExecutor
    executor = PlanExecutor()
    try:
        step = await executor.complete_step(plan_id, step_id, result=body.result)
        return JSONResponse(step.to_dict())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/plans/{plan_id}/steps/{step_id}/fail")
async def api_fail_step(plan_id: str, step_id: str, body: PlanActionRequest):
    """Mark a plan step as failed with error."""
    from core.planner import PlanExecutor
    executor = PlanExecutor()
    try:
        step = await executor.fail_step(plan_id, step_id, error=body.error)
        return JSONResponse(step.to_dict())
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Telegram Pairing ──


def _generate_pairing_code() -> str:
    """Generate a 6-character alphanumeric pairing code (uppercase, no ambiguous chars)."""
    alphabet = string.ascii_uppercase + string.digits
    # Remove ambiguous characters: 0/O, 1/I/L
    alphabet = alphabet.replace("0", "").replace("O", "").replace("1", "").replace("I", "").replace("L", "")
    return "".join(secrets.choice(alphabet) for _ in range(6))


@router.post("/telegram/generate-code")
async def api_generate_pairing_code(request: Request):
    """Generate a short-lived pairing code for Telegram linking."""
    s = _state(request)
    code = _generate_pairing_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await s.db.create_pairing_code(code, expires_at)
    # Cleanup old codes in the background
    await s.db.cleanup_expired_codes()
    return JSONResponse({
        "code": code,
        "expires_at": expires_at.isoformat(),
        "ttl_seconds": 300,
        "instructions": "Send /pair " + code + " to the Nexus Telegram bot",
    })


@router.get("/telegram/pairings")
async def api_list_pairings(request: Request):
    """List all Telegram pairings."""
    s = _state(request)
    pairings = await s.db.list_telegram_pairings()
    return JSONResponse({"pairings": pairings, "count": len(pairings)})


@router.delete("/telegram/pairings/{telegram_user_id}")
async def api_revoke_pairing(telegram_user_id: str, request: Request):
    """Revoke a Telegram pairing."""
    s = _state(request)
    await s.db.revoke_telegram_pairing(telegram_user_id)
    # Force the bot's in-memory cache to refresh immediately
    if s.telegram_channel:
        await s.telegram_channel._refresh_cache()
    return JSONResponse({"revoked": telegram_user_id})


@router.post("/telegram/pair-direct")
async def api_pair_direct(request: Request):
    """Directly pair a Telegram user by ID — no code needed.

    Body: {"telegram_user_id": "123456789"}

    This is an admin action that bypasses the code flow.  The user must have
    sent /start to the bot first (so the bot can message them).
    """
    s = _state(request)
    body = await request.json()
    telegram_user_id = str(body.get("telegram_user_id", "")).strip()
    if not telegram_user_id:
        return JSONResponse({"error": "telegram_user_id is required"}, status_code=400)

    # Create or reactivate the pairing
    await s.db.add_telegram_pairing(telegram_user_id=telegram_user_id)

    # Refresh bot cache immediately
    if s.telegram_channel:
        await s.telegram_channel._refresh_cache()
        # Notify the user on Telegram
        agent_name = s.cfg.agent_name if s.cfg else "Nexus"
        await s.telegram_channel.send_message(
            telegram_user_id,
            f"Your account has been linked by an admin.\n\n"
            f"You can now chat with {agent_name} directly here. "
            f"Send any message to get started!",
        )

    return JSONResponse({
        "success": True,
        "telegram_user_id": telegram_user_id,
        "message": f"Telegram user {telegram_user_id} paired successfully",
    })


@router.get("/telegram/bot-info")
async def api_telegram_bot_info(request: Request):
    """Get Telegram bot username and link (so user knows which bot to /start)."""
    s = _state(request)
    if not s.telegram_channel:
        return JSONResponse({"available": False, "error": "Telegram bot not running"})
    info = await s.telegram_channel.get_bot_info()
    if not info:
        return JSONResponse({"available": False, "error": "Could not reach Telegram API"})
    return JSONResponse({"available": True, **info})


@router.post("/telegram/send-pairing")
async def api_send_pairing_code(request: Request):
    """Generate a pairing code and send it directly to a Telegram user via the bot.

    Body: {"telegram_user_id": "123456789"}

    The user must have already sent /start to the bot (Telegram requires this
    before a bot can message a user).  If no user_id is provided, the code is
    generated and returned — the caller can display it in the UI.
    """
    s = _state(request)
    body = await request.json()
    telegram_user_id = str(body.get("telegram_user_id", "")).strip()

    # Generate code
    code = _generate_pairing_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await s.db.create_pairing_code(code, expires_at)
    await s.db.cleanup_expired_codes()

    result = {
        "code": code,
        "expires_at": expires_at.isoformat(),
        "ttl_seconds": 300,
    }

    if not telegram_user_id:
        # No user ID — just return the code (same as generate-code)
        result["sent"] = False
        result["instructions"] = f"Send /pair {code} to the Nexus Telegram bot"
        return JSONResponse(result)

    # Check if bot is running
    if not s.telegram_channel:
        result["sent"] = False
        result["error"] = "Telegram bot is not running. Restart the server after adding the bot token."
        return JSONResponse(result)

    # Try to send the code to the user
    message = (
        f"Your Nexus pairing code:\n\n"
        f"`{code}`\n\n"
        f"Reply with: `/pair {code}`\n\n"
        f"_This code expires in 5 minutes._"
    )
    sent = await s.telegram_channel.send_message(telegram_user_id, message)

    if sent:
        result["sent"] = True
        result["message"] = f"Pairing code sent to Telegram user {telegram_user_id}"
    else:
        result["sent"] = False
        result["error"] = (
            "Failed to send message. Make sure the user has sent /start to the bot first. "
            "Telegram bots can only message users who have initiated a conversation."
        )

    return JSONResponse(result)


# ── Documents ──


@router.get("/docs")
async def api_docs(request: Request):
    s = _state(request)
    files = scan_directory(s.cfg.docs_dir)
    return JSONResponse({"docs_dir": s.cfg.docs_dir, "files": files})


@router.post("/docs/ingest/{filename}")
async def api_ingest_file(filename: str, request: Request):
    s = _state(request)
    files = scan_directory(s.cfg.docs_dir)
    match = next((f for f in files if filename.lower() in f["name"].lower()), None)
    if not match:
        raise HTTPException(404, f"File not found: {filename}")
    try:
        validate_path(match["path"])
    except PathAccessDeniedError as exc:
        raise HTTPException(403, str(exc))
    task = await s.task_queue.submit("ingest", {"path": match["path"], "name": match["name"]})
    return JSONResponse({"task": task, "file": match["name"]})


@router.post("/docs/ingest-all")
async def api_ingest_all(request: Request):
    s = _state(request)
    files = scan_directory(s.cfg.docs_dir)
    if not files:
        raise HTTPException(404, "No documents found")
    tasks = []
    for f in files:
        try:
            validate_path(f["path"])
        except (PathAccessDeniedError, ValueError):
            continue
        task = await s.task_queue.submit("ingest", {"path": f["path"], "name": f["name"]})
        tasks.append({"task_id": task["id"], "file": f["name"]})
    return JSONResponse({"queued": len(tasks), "tasks": tasks})


# ── MCP Bridge API ──────────────────────────────────────────────
# These endpoints are called by the Nexus MCP server to expose tools
# to Claude Code via the Model Context Protocol.


@router.get("/tools")
async def api_tools(request: Request):
    """List all available tools in a format suitable for MCP discovery."""
    s = _state(request)
    tools = []

    # Plugin tools
    if s.plugin_manager:
        for plugin_name, plugin in s.plugin_manager.plugins.items():
            for tool in plugin.tools:
                tools.append({
                    "name": f"{plugin_name}__{tool.name}",
                    "description": tool.description,
                    "parameters": {k: str(v) for k, v in tool.parameters.items()},
                    "plugin": plugin_name,
                    "category": getattr(tool, "category", "general"),
                })

    # Skill actions
    if s.skills_engine:
        for skill in s.skills_engine.skills.values():
            configured = skill.is_configured(s.skills_engine.config) if s.skills_engine.config else True
            if not configured:
                continue
            for action in skill.actions:
                tools.append({
                    "name": action.name,
                    "description": action.description,
                    "parameters": {k: str(v) for k, v in action.parameters.items()},
                    "plugin": f"skill_{skill.id}",
                    "category": skill.domain,
                })

    return JSONResponse({"tools": tools, "count": len(tools)})


class MCPExecuteRequest(BaseModel):
    tool_name: str
    arguments: dict = {}


@router.post("/mcp/execute")
async def api_mcp_execute(body: MCPExecuteRequest, request: Request):
    """Execute a tool via the MCP bridge.

    Handles both plugin tools (name format: ``plugin__tool_name``)
    and skill actions (direct action names).
    """
    s = _state(request)
    tool_name = body.tool_name
    arguments = body.arguments

    logger.info(f"MCP execute: {tool_name} (args: {list(arguments.keys())})")

    # Try as plugin tool first (format: plugin__tool_name)
    if "__" in tool_name and s.tool_executor:
        from schemas.tools import ToolCall

        parts = tool_name.split("__", 1)
        tc = ToolCall(
            id=f"mcp_{uuid.uuid4().hex[:8]}",
            name=parts[1],
            plugin=parts[0],
            parameters=arguments,
        )
        result = await s.tool_executor.execute(tc)
        return JSONResponse({
            "success": result.success,
            "result": result.result if result.success else None,
            "error": result.error if not result.success else None,
        })

    # Try as skill action
    if s.skills_engine:
        try:
            result = await s.skills_engine.execute_action(tool_name, arguments)
            return JSONResponse({
                "success": True,
                "result": result,
            })
        except Exception as e:
            # Not a known skill action — fall through
            if "not found" not in str(e).lower():
                return JSONResponse({
                    "success": False,
                    "error": str(e),
                })

    # Special meta-tools
    if tool_name == "nexus_execute" and s.tool_executor:
        inner_name = arguments.get("tool_name", "")
        inner_params = arguments.get("params", "{}")
        if isinstance(inner_params, str):
            try:
                inner_params = json.loads(inner_params)
            except json.JSONDecodeError:
                inner_params = {}
        # Recurse with the inner tool
        return await api_mcp_execute(
            MCPExecuteRequest(tool_name=inner_name, arguments=inner_params),
            request,
        )

    if tool_name == "nexus_skill_list" and s.skills_engine:
        actions = []
        for skill in s.skills_engine.skills.values():
            for action in skill.actions:
                actions.append({
                    "name": action.name,
                    "description": action.description,
                    "skill": skill.id,
                    "parameters": dict(action.parameters),
                })
        return JSONResponse({"success": True, "result": json.dumps(actions, indent=2)})

    raise HTTPException(404, f"Tool '{tool_name}' not found")

