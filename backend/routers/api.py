"""Public REST API endpoints."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from core.exceptions import PathAccessDeniedError
from core.security import validate_path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
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
        with tempfile.NamedTemporaryFile(mode='w', delete=True) as f:
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


@router.delete("/conversations/{conv_id}")
async def api_delete_conversation(conv_id: str, request: Request):
    s = _state(request)
    await s.db.delete_conversation(conv_id)
    return JSONResponse({"deleted": conv_id})


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


# ── Partner Agents (Phase 6 — Aries integration) ──

@router.get("/partners")
async def api_partners(request: Request):
    s = _state(request)
    if not hasattr(s, 'partner_registry') or s.partner_registry is None:
        return JSONResponse({"partners": []})
    agents = await s.partner_registry.list_agents()
    return JSONResponse({"partners": [a.model_dump() for a in agents]})


@router.post("/partners/register")
async def api_register_partner(request: Request):
    s = _state(request)
    if not hasattr(s, 'partner_registry') or s.partner_registry is None:
        raise HTTPException(503, "Partner registry not initialized")
    body = await request.json()
    from schemas.partnerships import PartnerAgent
    agent = PartnerAgent(**body)
    await s.partner_registry.register(agent)
    return JSONResponse({"registered": agent.name})


@router.post("/partners/{name}/message")
async def api_partner_message(name: str, request: Request):
    s = _state(request)
    if not hasattr(s, 'partner_registry') or s.partner_registry is None:
        raise HTTPException(503, "Partner registry not initialized")
    body = await request.json()
    from schemas.partnerships import AgentMessage
    msg = AgentMessage(**body)
    response = await s.partner_registry.send_message(msg)
    return JSONResponse(response.model_dump(mode="json"))
