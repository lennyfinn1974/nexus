"""Admin API — settings, plugins, system management, and log streaming."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import shutil
import subprocess
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("nexus.admin")

_bearer_scheme = HTTPBearer(auto_error=False)

# Auth components (injected at startup)
_jwt_manager = None
_user_manager = None
_ip_security = None
_audit_log = None


async def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
) -> None:
    """Validate admin access via JWT (with legacy API key fallback).

    When auth is enabled: requires JWT with role=admin.
    When auth is disabled: falls back to ADMIN_API_KEY bearer token.
    """
    # Check JWT from middleware first (set by auth_middleware in main.py)
    user = getattr(request.state, "user", None)
    if user and user.get("role") == "admin":
        return

    # Legacy fallback: ADMIN_API_KEY bearer token (env var)
    env_key = os.environ.get("ADMIN_API_KEY", "")
    if env_key and credentials and credentials.credentials == env_key:
        return

    # DB-backed admin access key (set via Admin Console settings)
    db_key = ""
    if _cfg:
        db_key = _cfg.admin_access_key if hasattr(_cfg, "admin_access_key") else ""
    if db_key and credentials and credentials.credentials == db_key:
        return

    # If auth is enabled, also try JWT from bearer header directly
    if _jwt_manager and credentials and credentials.credentials:
        claims = _jwt_manager.verify_access_token(credentials.credentials)
        if claims and claims.get("role") == "admin":
            request.state.user = claims
            return

    # Check JWT cookie as last resort
    if _jwt_manager:
        token = request.cookies.get("nexus_access_token")
        if token:
            claims = _jwt_manager.verify_access_token(token)
            if claims and claims.get("role") == "admin":
                request.state.user = claims
                return

    # Open access: if no auth keys are configured at all, allow access.
    # This handles first-boot / local-only setups where no key has been set yet.
    auth_enabled = _cfg.auth_enabled if _cfg else False
    if not auth_enabled and not env_key and not db_key:
        return

    raise HTTPException(status_code=401, detail="Admin access required")


router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

# Injected at startup
_cfg = None  # ConfigManager
_plugins = None  # PluginManager
_models = None  # ModelRouter
_skills = None  # SkillsEngine
_db = None  # Database
_task_queue = None  # TaskQueue
_catalog = None  # SkillCatalog
_work_registry = None  # WorkRegistry

# In-memory log buffer for streaming
_log_buffer: deque = deque(maxlen=500)
_log_subscribers: list = []


# ── Log capture handler ─────────────────────────────────────────


class AdminLogHandler(logging.Handler):
    """Captures log records for the admin log viewer."""

    def emit(self, record):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "msg": self.format(record),
        }
        _log_buffer.append(entry)
        for q in list(_log_subscribers):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass


def init(
    config_manager,
    plugin_manager,
    model_router,
    database,
    task_queue,
    skills_engine=None,
    jwt_manager=None,
    user_manager=None,
    ip_security=None,
    audit_log=None,
    skill_catalog=None,
    work_registry=None,
):
    """Called from app.py during startup."""
    global _cfg, _plugins, _models, _db, _task_queue, _skills
    global _jwt_manager, _user_manager, _ip_security, _audit_log, _catalog, _work_registry
    _cfg = config_manager
    _plugins = plugin_manager
    _models = model_router
    _db = database
    _task_queue = task_queue
    _skills = skills_engine
    _jwt_manager = jwt_manager
    _user_manager = user_manager
    _ip_security = ip_security
    _audit_log = audit_log
    _catalog = skill_catalog
    _work_registry = work_registry

    # Attach log handler to root logger
    handler = AdminLogHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)


# ── SSRF Protection ─────────────────────────────────────────────


def validate_url(url: str) -> str:
    """Validate a URL is safe to request (not targeting internal networks).

    Returns the validated URL string.
    Raises ValueError if the URL is invalid or targets a blocked address.
    """
    import socket

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got '{parsed.scheme}'")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    # Block localhost variations
    blocked_hostnames = {"localhost", "localhost.localdomain", "0.0.0.0"}
    if hostname.lower() in blocked_hostnames:
        raise ValueError(f"Requests to '{hostname}' are blocked (internal address)")

    # Resolve hostname to IP and check against blocked ranges
    try:
        resolved_ips = socket.getaddrinfo(hostname, parsed.port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError(f"Could not resolve hostname '{hostname}'")

    for _family, _type, _proto, _canonname, sockaddr in resolved_ips:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if addr.is_loopback:
            raise ValueError(f"Requests to loopback address '{ip_str}' are blocked")
        if addr.is_private:
            raise ValueError(f"Requests to private address '{ip_str}' are blocked")
        if addr.is_link_local:
            raise ValueError(f"Requests to link-local address '{ip_str}' are blocked")
        if addr.is_reserved:
            raise ValueError(f"Requests to reserved address '{ip_str}' are blocked")
        # Block IPv4-mapped IPv6 loopback/private (e.g. ::ffff:127.0.0.1)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            mapped = addr.ipv4_mapped
            if mapped.is_loopback or mapped.is_private or mapped.is_link_local:
                raise ValueError(f"Requests to mapped private address '{ip_str}' are blocked")

    return url


# URL-type settings that must pass SSRF validation on save (external services only)
_URL_SETTINGS: set[str] = set()  # Add external URL settings here if needed

# URL settings that allow localhost/private addresses (local services like Ollama)
_LOCAL_URL_SETTINGS = {"OLLAMA_BASE_URL"}


# ── Settings ────────────────────────────────────────────────────


@router.get("/settings")
async def get_settings():
    return JSONResponse({"settings": _cfg.get_all_for_api()})


@router.post("/settings")
async def update_settings(request: Request):
    body = await request.json()
    updates = body.get("updates", {})
    if not updates:
        return JSONResponse({"error": "No updates provided"}, status_code=400)

    # Don't overwrite secrets with masked values or empty strings
    clean = {}
    for key, value in updates.items():
        if "..." in str(value):
            continue  # masked — user didn't change it
        # Validate external URL-type settings against SSRF
        if key in _URL_SETTINGS and value:
            try:
                validate_url(str(value))
            except ValueError as e:
                return JSONResponse({"error": f"Invalid URL for {key}: {e}"}, status_code=400)
        # Validate local URL settings (lighter check — allow localhost/private)
        if key in _LOCAL_URL_SETTINGS and value:
            parsed = urlparse(str(value))
            if parsed.scheme not in ("http", "https"):
                return JSONResponse(
                    {"error": f"Invalid URL for {key}: scheme must be http or https"},
                    status_code=400,
                )
            if not parsed.hostname:
                return JSONResponse(
                    {"error": f"Invalid URL for {key}: no hostname"},
                    status_code=400,
                )
        clean[key] = value

    changed = await _cfg.set_many(clean, changed_by="admin")

    return JSONResponse(
        {
            "updated": changed,
            "count": len(changed),
            "message": f"Saved {len(changed)} setting(s)." if changed else "No changes detected.",
        }
    )


@router.post("/settings/test/{key}")
async def test_setting(key: str):
    """Test a connection associated with a setting."""
    if key == "ANTHROPIC_API_KEY":
        api_key = _cfg.anthropic_api_key
        if not api_key:
            return JSONResponse({"success": False, "error": "No API key set"})
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=api_key)
            resp = await client.messages.create(
                model=_cfg.claude_model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            await client.close()
            return JSONResponse({"success": True, "message": f"Connected — model: {_cfg.claude_model}"})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})

    elif key == "OLLAMA_BASE_URL":
        try:
            base_url = _cfg.ollama_base_url  # Local service — skip SSRF check
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url}/api/tags")
                models = resp.json().get("models", [])
                names = [m["name"] for m in models[:5]]
                return JSONResponse(
                    {"success": True, "message": f"Connected — {len(models)} models: {', '.join(names)}"}
                )
        except ValueError as e:
            return JSONResponse({"success": False, "error": f"URL blocked: {e}"})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})

    elif key == "GITHUB_TOKEN":
        token = _cfg.github_token
        if not token:
            return JSONResponse({"success": False, "error": "No token set"})
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.github.com/user",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                )
                if resp.status_code == 200:
                    user = resp.json().get("login", "unknown")
                    return JSONResponse({"success": True, "message": f"Authenticated as {user}"})
                return JSONResponse({"success": False, "error": f"GitHub returned {resp.status_code}"})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})

    return JSONResponse({"success": False, "error": f"No test available for {key}"})


@router.get("/models")
async def get_models():
    """Get current model configuration and status."""
    status = _models.status
    return JSONResponse(
        {
            "ollama_model": _cfg.ollama_model,
            "ollama_base_url": _cfg.ollama_base_url,
            "ollama_available": status["ollama_available"],
            "claude_model": _cfg.claude_model,
            "claude_available": status["claude_available"],
            "claude_code_available": status.get("claude_code_available", False),
            "claude_code_model": status.get("claude_code_model"),
            "claude_code_enabled": _cfg.get_bool("CLAUDE_CODE_ENABLED", False),
            "complexity_threshold": _cfg.complexity_threshold,
            # Sub-agent settings
            "sub_agent_enabled": _cfg.get_bool("SUB_AGENT_ENABLED", True),
            "sub_agent_auto_enabled": _cfg.get_bool("SUB_AGENT_AUTO_ENABLED", False),
            "sub_agent_max_concurrent": _cfg.get_int("SUB_AGENT_MAX_CONCURRENT", 4),
            "sub_agent_cc_concurrent": _cfg.get_int("SUB_AGENT_CLAUDE_CODE_CONCURRENT", 2),
            "sub_agent_builder_model": _cfg.get("SUB_AGENT_BUILDER_MODEL") or "",
            "sub_agent_reviewer_model": _cfg.get("SUB_AGENT_REVIEWER_MODEL") or "claude",
            "sub_agent_timeout": _cfg.get_int("SUB_AGENT_TIMEOUT", 120),
        }
    )


@router.get("/models/ollama-list")
async def list_ollama_models():
    """Fetch available models from the connected Ollama instance."""
    try:
        base_url = _cfg.ollama_base_url  # Local service — skip SSRF check
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                return JSONResponse(
                    {
                        "success": True,
                        "models": [
                            {"name": m["name"], "size": m.get("size", 0), "modified": m.get("modified_at", "")}
                            for m in models
                        ],
                    }
                )
            return JSONResponse({"success": False, "models": [], "error": f"Ollama returned {resp.status_code}"})
    except ValueError as e:
        return JSONResponse({"success": False, "models": [], "error": f"URL blocked: {e}"})
    except Exception as e:
        return JSONResponse({"success": False, "models": [], "error": str(e)})


# ── Plugins ─────────────────────────────────────────────────────


@router.get("/plugins")
async def get_plugins():
    active = []
    for name, plugin in _plugins.plugins.items():
        health = {"status": "ok"}
        if hasattr(plugin, "health_check"):
            try:
                health = await plugin.health_check()
            except Exception as e:
                health = {"status": "error", "message": str(e)}

        active.append(
            {
                "name": name,
                "description": plugin.description,
                "version": plugin.version,
                "enabled": plugin.enabled,
                "health": health,
                "tools": [
                    {"name": t.name, "description": t.description, "parameters": t.parameters} for t in plugin.tools
                ],
                "commands": [
                    {"command": f"/{cmd}", "description": info["description"]} for cmd, info in plugin.commands.items()
                ],
                "required_settings": getattr(plugin, "required_settings", {}),
                "pip_requires": getattr(plugin, "pip_requires", []),
            }
        )

    # Discover available-but-not-loaded plugins
    plugins_dir = os.path.join(_cfg.base_dir, "backend", "plugins")
    available = []
    if os.path.isdir(plugins_dir):
        for f in sorted(os.listdir(plugins_dir)):
            if f.endswith("_plugin.py"):
                pname = f.replace("_plugin.py", "")
                if pname not in _plugins.plugins:
                    available.append(
                        {"name": pname, "file": f, "enabled": False, "reason": "Dependencies not met or config missing"}
                    )

    return JSONResponse({"active": active, "available": available})


@router.post("/plugins/{name}/reload")
async def reload_plugin(name: str):
    """Reload a single plugin (works for both active and inactive plugins)."""
    try:
        plugin = await _plugins.reload_plugin(name, _cfg, _db, _models)
        return JSONResponse(
            {
                "success": True,
                "message": f"Plugin '{plugin.name}' loaded — {len(plugin.tools)} tools, {len(plugin.commands)} commands",
            }
        )
    except Exception as e:
        logger.error(f"Plugin reload failed for '{name}': {e}")
        return JSONResponse({"success": False, "error": str(e)})


@router.post("/plugins/reload-all")
async def reload_all_plugins():
    """Shut down and reload all plugins."""
    try:
        await _plugins.reload_all(_cfg, _db, _models)
        count = len(_plugins.plugins)
        tools = len(_plugins.all_tools)
        return JSONResponse(
            {
                "success": True,
                "message": f"Reloaded all plugins — {count} active, {tools} tools",
            }
        )
    except Exception as e:
        logger.error(f"Reload-all failed: {e}")
        return JSONResponse({"success": False, "error": str(e)})


# ── Server Restart ──────────────────────────────────────────────


@router.post("/restart")
async def restart_server():
    """Gracefully restart the Nexus server process."""
    import sys

    logger.info("Server restart requested from admin UI")

    async def _do_restart():
        await asyncio.sleep(0.5)  # Let the response get sent first
        logger.info("Restarting now...")
        # Replace current process with a fresh one
        os.execv(sys.executable, [sys.executable] + sys.argv)

    asyncio.create_task(_do_restart())
    return JSONResponse({"success": True, "message": "Server is restarting... page will reload in a few seconds."})


# ── System Prompt ───────────────────────────────────────────────


@router.get("/system-prompt")
async def get_system_prompt():
    from core.system_prompt import build_system_prompt

    prompt = build_system_prompt(_cfg, _plugins)
    plugin_additions = _plugins.get_system_prompt_additions() if _plugins else ""
    return JSONResponse(
        {
            "base_prompt": prompt,
            "plugin_additions": plugin_additions,
            "full_prompt": prompt + plugin_additions,
        }
    )


# ── Usage Tracking ──────────────────────────────────────────────


@router.get("/usage")
async def get_usage():
    """Token usage statistics."""
    stats = await _db.get_usage_stats()
    return JSONResponse(stats)


# ── Conversations ───────────────────────────────────────────────


@router.get("/conversations")
async def list_conversations():
    convs = await _db.list_conversations(limit=200)
    for c in convs:
        c["message_count"] = await _db.get_message_count(c["id"])
    return JSONResponse(convs)


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    await _db.delete_conversation(conv_id)
    return JSONResponse({"deleted": conv_id})


@router.delete("/conversations")
async def delete_all_conversations(request: Request):
    convs = await _db.list_conversations(limit=9999)
    count = 0
    for c in convs:
        await _db.delete_conversation(c["id"])
        count += 1
    return JSONResponse({"deleted": count})


# ── Conversation Export ───────────────────────────────────────


@router.get("/conversations/{conv_id}/export")
async def export_conversation(conv_id: str, format: str = "markdown"):
    """Export a single conversation as Markdown or JSON.

    Query params:
        format: "markdown" (default) or "json"
    """
    conv = await _db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    messages = await _db.get_conversation_messages(conv_id, limit=9999)
    summary = await _db.get_conversation_summary(conv_id)

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
        # Markdown format
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


@router.get("/conversations/export-all")
async def export_all_conversations(format: str = "json"):
    """Export all conversations as a single JSON file.

    Returns a downloadable JSON with all conversations, their messages,
    and summaries bundled together.
    """
    convs = await _db.list_conversations(limit=9999)
    all_data = []
    for conv in convs:
        messages = await _db.get_conversation_messages(conv["id"], limit=9999)
        summary = await _db.get_conversation_summary(conv["id"])
        all_data.append({
            "conversation": conv,
            "summary": summary,
            "message_count": len(messages),
            "messages": messages,
        })

    export = {
        "nexus_export": True,
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "conversation_count": len(all_data),
        "conversations": all_data,
    }
    content = json.dumps(export, indent=2, default=str)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="nexus_export_{ts}.json"'},
    )


# ── Logs (SSE stream) ──────────────────────────────────────────


@router.get("/logs")
async def get_logs():
    return JSONResponse(list(_log_buffer))


@router.get("/logs/stream")
async def stream_logs():
    """Server-Sent Events endpoint for live log streaming."""
    queue = asyncio.Queue(maxsize=100)
    _log_subscribers.append(queue)

    async def event_generator():
        try:
            while True:
                entry = await queue.get()
                yield f"data: {json.dumps(entry)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _log_subscribers:
                _log_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Work Streams ──────────────────────────────────────────────────


@router.get("/workstreams")
async def list_workstreams(status: str = None, kind: str = None):
    """List work items with optional filters."""
    items = []
    if _work_registry:
        active = _work_registry.get_all_active()
        if status or kind:
            items = [
                i for i in active
                if (not status or i.get("status") == status)
                and (not kind or i.get("kind") == kind)
            ]
        else:
            items = list(active)

    # Also fetch recent terminal items from DB for the "done" columns
    if _db and not status:
        try:
            db_items = await _db.list_work_items(limit=50)
            active_ids = {i["id"] for i in items}
            for di in db_items:
                if di["id"] not in active_ids:
                    items.append(di)
        except Exception:
            pass

    return JSONResponse(items)


@router.get("/workstreams/counts")
async def workstream_counts():
    """Get summary counts by status."""
    if _work_registry:
        counts = _work_registry.get_counts()
    else:
        counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0, "total": 0}
    return JSONResponse(counts)


@router.get("/workstreams/stream")
async def stream_workstreams():
    """SSE endpoint for real-time work item updates."""
    if not _work_registry:
        return JSONResponse({"error": "Work registry not initialized"}, status_code=500)

    queue = _work_registry.subscribe_sse()

    async def event_generator():
        try:
            # Send initial snapshot of all active items
            initial = _work_registry.get_all_active()
            yield f"data: {json.dumps({'type': 'snapshot', 'items': initial})}\n\n"
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _work_registry.unsubscribe_sse(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/workstreams/{item_id}")
async def get_workstream(item_id: str):
    """Get a single work item with children."""
    item = _work_registry.get(item_id) if _work_registry else None
    if not item and _db:
        try:
            db_items = await _db.list_work_items(limit=1)
            item = next((i for i in db_items if i["id"] == item_id), None)
        except Exception:
            pass
    if not item:
        return JSONResponse({"error": "Work item not found"}, status_code=404)
    children = _work_registry.get_children(item_id) if _work_registry else []
    return JSONResponse({"item": item, "children": children})


# ── System ──────────────────────────────────────────────────────


@router.get("/system")
async def get_system_info():
    import platform
    import sys

    # Get database size from PostgreSQL
    db_size_mb = 0.0
    try:
        rows = await _db.execute_query("SELECT pg_database_size(current_database()) as size")
        if rows:
            db_size_mb = round(rows[0][0] / 1048576, 2)
    except Exception:
        pass

    skills_count = 0
    if os.path.isdir(_cfg.skills_dir):
        skills_count = len([f for f in os.listdir(_cfg.skills_dir) if f.endswith(".md")])

    return JSONResponse(
        {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "base_dir": _cfg.base_dir,
            "skills_dir": _cfg.skills_dir,
            "docs_dir": _cfg.docs_dir,
            "data_dir": _cfg.data_dir,
            "db_backend": "postgresql",
            "db_size_mb": db_size_mb,
            "skills_count": skills_count,
        }
    )


def _find_pg_dump() -> str | None:
    """Locate the pg_dump binary."""
    # Check PATH first
    pg_dump = shutil.which("pg_dump")
    if pg_dump:
        return pg_dump
    # Well-known Homebrew locations
    for candidate in [
        "/opt/homebrew/opt/postgresql@17/bin/pg_dump",
        "/opt/homebrew/opt/postgresql@16/bin/pg_dump",
        "/opt/homebrew/opt/postgresql@15/bin/pg_dump",
        "/opt/homebrew/bin/pg_dump",
        "/usr/local/bin/pg_dump",
    ]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _parse_db_url() -> dict:
    """Parse DATABASE_URL into components for pg_dump."""
    url = os.getenv("DATABASE_URL", "")
    # Strip asyncpg driver prefix: postgresql+asyncpg://... -> postgresql://...
    url = url.replace("+asyncpg", "").replace("+psycopg2", "")
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "",
        "dbname": parsed.path.lstrip("/") or "nexus",
        "password": parsed.password or "",
    }


@router.post("/backup")
async def create_backup():
    pg_dump = _find_pg_dump()
    if not pg_dump:
        raise HTTPException(500, "pg_dump not found. Install PostgreSQL client tools.")

    backup_dir = os.path.join(_cfg.data_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"nexus_backup_{timestamp}.sql"
    filepath = os.path.join(backup_dir, filename)

    db_info = _parse_db_url()

    cmd = [
        pg_dump,
        "-h", db_info["host"],
        "-p", db_info["port"],
        "-d", db_info["dbname"],
        "--no-owner",
        "--no-privileges",
        "-f", filepath,
    ]
    if db_info["user"]:
        cmd.extend(["-U", db_info["user"]])

    env = dict(os.environ)
    if db_info["password"]:
        env["PGPASSWORD"] = db_info["password"]

    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=120, env=env,
        )
        if result.returncode != 0:
            # Clean up failed backup file
            if os.path.exists(filepath):
                os.remove(filepath)
            logger.error(f"pg_dump failed: {result.stderr}")
            raise HTTPException(500, f"pg_dump failed: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        if os.path.exists(filepath):
            os.remove(filepath)
        raise HTTPException(500, "Backup timed out after 120 seconds.")

    size_mb = round(os.path.getsize(filepath) / 1048576, 2)
    logger.info(f"Backup created: {filename} ({size_mb} MB)")

    return JSONResponse({
        "path": filepath,
        "size_mb": size_mb,
        "timestamp": timestamp,
    })


@router.get("/backups")
async def list_backups():
    backup_dir = os.path.join(_cfg.data_dir, "backups")
    if not os.path.isdir(backup_dir):
        return JSONResponse([])
    backups = []
    for f in sorted(os.listdir(backup_dir), reverse=True):
        if f.endswith((".sql", ".db")):
            path = os.path.join(backup_dir, f)
            backups.append(
                {
                    "file": f,
                    "size_mb": round(os.path.getsize(path) / 1048576, 2),
                    "created": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
                }
            )
    return JSONResponse(backups)


@router.get("/audit")
async def get_audit_log():
    entries = await _cfg.get_audit_log(limit=100)
    return JSONResponse(entries)


# ── Skills Management ────────────────────────────────────────────


@router.get("/skills")
async def list_skills_admin():
    """List all skills with config status."""
    if not _skills:
        return JSONResponse([])
    return JSONResponse(await _skills.list_skills())


@router.get("/skills/packs")
async def list_available_packs():
    """List installable skill packs from the skill-packs directory."""
    packs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skill-packs")
    if not os.path.isdir(packs_dir):
        return JSONResponse([])

    packs = []
    for item in sorted(os.listdir(packs_dir)):
        if item.startswith("_"):
            continue
        pack_path = os.path.join(packs_dir, item)
        manifest_path = os.path.join(pack_path, "skill.yaml")
        if os.path.isdir(pack_path) and os.path.exists(manifest_path):
            try:
                import yaml

                with open(manifest_path) as f:
                    manifest = yaml.safe_load(f) or {}
                installed = item in (_skills.skills if _skills else {})
                packs.append(
                    {
                        "id": manifest.get("id", item),
                        "name": manifest.get("name", item),
                        "type": manifest.get("type", "knowledge"),
                        "description": manifest.get("description", ""),
                        "domain": manifest.get("domain", ""),
                        "version": manifest.get("version", "1.0"),
                        "config_keys": list(manifest.get("config", {}).keys()),
                        "installed": installed,
                    }
                )
            except Exception as e:
                logger.error(f"Error reading pack {item}: {e}")
    return JSONResponse(packs)


@router.post("/skills/install/{pack_id}")
async def install_skill_pack(pack_id: str):
    """Install a skill pack from the skill-packs directory."""
    if not _skills:
        return JSONResponse({"error": "Skills engine not loaded"}, status_code=500)

    packs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skill-packs")
    pack_path = os.path.join(packs_dir, pack_id)

    if not os.path.isdir(pack_path) or not os.path.exists(os.path.join(pack_path, "skill.yaml")):
        return JSONResponse({"error": f"Pack '{pack_id}' not found"}, status_code=404)

    try:
        result = await _skills.install_skill_pack(pack_path)
        return JSONResponse({"success": True, "skill": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/skills/{skill_id}")
async def delete_skill_admin(skill_id: str):
    """Delete a skill."""
    if not _skills:
        return JSONResponse({"error": "Skills engine not loaded"}, status_code=500)
    await _skills.delete_skill(skill_id)
    return JSONResponse({"deleted": skill_id})


@router.get("/skills/{skill_id}/config")
async def get_skill_config(skill_id: str):
    """Get config status for a skill."""
    if not _skills or skill_id not in _skills.skills:
        return JSONResponse({"error": "Skill not found"}, status_code=404)
    skill = _skills.skills[skill_id]
    return JSONResponse(
        {
            "skill": skill.to_dict(),
            "config_status": skill.get_config_status(_cfg) if _cfg else {},
            "configured": skill.is_configured(_cfg) if _cfg else True,
        }
    )


# ── Skill Catalog ──────────────────────────────────────────────


@router.get("/catalog/search")
async def catalog_search(q: str = "", category: str = "", limit: int = 20):
    """Search the skill catalog (anti-gravity, etc.)."""
    if not _catalog:
        return JSONResponse({"results": [], "total": 0})
    results = _catalog.search(q, category=category or None, limit=limit)
    return JSONResponse({"results": results, "total": len(results)})


@router.get("/catalog/categories")
async def catalog_categories():
    """List skill catalog categories with counts."""
    if not _catalog:
        return JSONResponse([])
    return JSONResponse(_catalog.list_categories())


@router.get("/catalog/stats")
async def catalog_stats():
    """Get catalog summary statistics."""
    if not _catalog:
        return JSONResponse({"total": 0, "sources": 0, "categories": 0})
    return JSONResponse({
        "total": len(_catalog.index),
        "sources": len(_catalog.sources),
        "categories": len(_catalog.list_categories()),
        "source_dirs": _catalog.sources,
    })


@router.get("/catalog/{skill_id}")
async def catalog_detail(skill_id: str):
    """Get full detail for a catalog skill."""
    if not _catalog:
        raise HTTPException(404, "Catalog not available")
    detail = _catalog.get_skill_detail(skill_id)
    if not detail:
        raise HTTPException(404, f"Skill '{skill_id}' not found in catalog")
    return JSONResponse(detail)


@router.post("/catalog/{skill_id}/install")
async def catalog_install(skill_id: str):
    """Install a skill from the catalog into Nexus."""
    if not _catalog or not _skills:
        raise HTTPException(500, "Catalog or skills engine not available")

    entry = _catalog.get_by_id(skill_id)
    if not entry:
        raise HTTPException(404, f"Skill '{skill_id}' not found in catalog")

    if entry.get("installed"):
        return JSONResponse({"success": True, "message": f"Skill '{skill_id}' is already installed"})

    try:
        from skills.converter import convert_antigravity_skill

        dest_dir = os.path.join(_skills.skills_dir, skill_id)
        manifest = convert_antigravity_skill(
            source_dir=entry["source_path"],
            dest_dir=dest_dir,
            category=entry.get("category", "general"),
            skill_id=skill_id,
        )

        # Hot-load the new skill
        from skills.engine import Skill

        skill = Skill(dest_dir, manifest)
        _skills._load_actions(skill)
        _skills.skills[skill_id] = skill

        # Save to DB
        await _db.save_skill(
            skill_id,
            manifest["name"],
            manifest.get("description", ""),
            manifest.get("domain", "general"),
            os.path.join(dest_dir, "knowledge.md"),
        )

        # Update catalog installed status
        _catalog.refresh_installed()

        return JSONResponse({
            "success": True,
            "message": f"Installed skill: {manifest['name']}",
            "skill": manifest,
        })
    except Exception as e:
        logger.error(f"Failed to install catalog skill '{skill_id}': {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ── User Management ──────────────────────────────────────────


@router.get("/users")
async def list_users():
    if not _user_manager:
        return JSONResponse([])
    users = await _user_manager.list_users()
    return JSONResponse(users)


@router.put("/users/{user_id}/role")
async def update_user_role(user_id: str, request: Request):
    if not _user_manager:
        raise HTTPException(500, "Auth not initialized")
    body = await request.json()
    role = body.get("role", "")
    ok = await _user_manager.update_user_role(user_id, role)
    if not ok:
        raise HTTPException(400, "Invalid role")
    getattr(request.state, "user", None)
    if _audit_log:
        await _audit_log.log_event(
            "user_role_change",
            user_id=user_id,
            details=f"role={role}",
            ip_address=request.client.host if request.client else "",
        )
    return JSONResponse({"ok": True, "user_id": user_id, "role": role})


@router.put("/users/{user_id}/deactivate")
async def deactivate_user(user_id: str, request: Request):
    if not _user_manager:
        raise HTTPException(500, "Auth not initialized")
    await _user_manager.deactivate_user(user_id)
    if _jwt_manager:
        await _jwt_manager.revoke_all_user_sessions(user_id)
    return JSONResponse({"ok": True, "user_id": user_id, "active": False})


@router.put("/users/{user_id}/activate")
async def activate_user(user_id: str):
    if not _user_manager:
        raise HTTPException(500, "Auth not initialized")
    await _user_manager.activate_user(user_id)
    return JSONResponse({"ok": True, "user_id": user_id, "active": True})


# ── Whitelist Management ─────────────────────────────────────


@router.get("/whitelist")
async def list_whitelist():
    if not _user_manager:
        return JSONResponse([])
    return JSONResponse(await _user_manager.list_whitelist())


@router.post("/whitelist")
async def add_to_whitelist(request: Request):
    if not _user_manager:
        raise HTTPException(500, "Auth not initialized")
    body = await request.json()
    email = body.get("email", "").strip().lower()
    if not email:
        raise HTTPException(400, "Email required")
    admin_user = getattr(request.state, "user", None)
    added_by = admin_user.get("email", "") if admin_user else ""
    ok = await _user_manager.add_to_whitelist(email, added_by)
    if _audit_log:
        await _audit_log.log_event(
            "whitelist_add",
            email=email,
            details=f"added_by={added_by}",
            ip_address=request.client.host if request.client else "",
        )
    return JSONResponse({"ok": ok, "email": email})


@router.delete("/whitelist/{email}")
async def remove_from_whitelist(email: str, request: Request):
    if not _user_manager:
        raise HTTPException(500, "Auth not initialized")
    await _user_manager.remove_from_whitelist(email)
    if _audit_log:
        await _audit_log.log_event(
            "whitelist_remove", email=email, ip_address=request.client.host if request.client else ""
        )
    return JSONResponse({"ok": True, "email": email})


# ── IP Security Management ───────────────────────────────────


@router.get("/blocked-ips")
async def list_blocked_ips():
    if not _ip_security:
        return JSONResponse([])
    return JSONResponse(await _ip_security.list_blocked_ips())


@router.post("/blocked-ips")
async def block_ip(request: Request):
    if not _ip_security:
        raise HTTPException(500, "Auth not initialized")
    body = await request.json()
    ip = body.get("ip", "").strip()
    reason = body.get("reason", "")
    if not ip:
        raise HTTPException(400, "IP address required")
    admin_user = getattr(request.state, "user", None)
    blocked_by = admin_user.get("email", "") if admin_user else ""
    await _ip_security.block_ip(ip, reason, blocked_by)
    if _audit_log:
        await _audit_log.log_event(
            "ip_blocked", details=f"ip={ip} reason={reason}", ip_address=request.client.host if request.client else ""
        )
    return JSONResponse({"ok": True, "ip": ip})


@router.delete("/blocked-ips/{ip}")
async def unblock_ip(ip: str, request: Request):
    if not _ip_security:
        raise HTTPException(500, "Auth not initialized")
    await _ip_security.unblock_ip(ip)
    if _audit_log:
        await _audit_log.log_event(
            "ip_unblocked", details=f"ip={ip}", ip_address=request.client.host if request.client else ""
        )
    return JSONResponse({"ok": True, "ip": ip})


# ── Auth Audit Log ───────────────────────────────────────────


@router.get("/auth-audit")
async def get_auth_audit(event_type: str = None, limit: int = 100):
    if not _audit_log:
        return JSONResponse([])
    return JSONResponse(await _audit_log.get_recent_events(limit=limit, event_type=event_type))


# ── Session Management ───────────────────────────────────────


@router.get("/sessions/{user_id}")
async def list_sessions(user_id: str):
    if not _jwt_manager:
        return JSONResponse([])
    return JSONResponse(await _jwt_manager.list_user_sessions(user_id))


@router.post("/setup/complete")
async def complete_setup(request: Request):
    """Mark initial setup as complete.

    Called at the end of the onboarding wizard after admin key and
    at least one model have been configured.
    """
    body = await request.json()
    admin_key = body.get("admin_key", "")
    if not admin_key:
        return JSONResponse({"error": "admin_key is required"}, status_code=400)

    # Save the admin access key
    await _cfg.set_many(
        {"ADMIN_ACCESS_KEY": admin_key, "SETUP_COMPLETE": "true"},
        changed_by="setup-wizard",
    )
    logger.info("Setup wizard completed — admin key set, SETUP_COMPLETE=true")
    agent_name = _cfg.agent_name if _cfg else "Nexus"
    return JSONResponse({"success": True, "message": f"Setup complete. Welcome to {agent_name}!"})


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str, request: Request):
    if not _jwt_manager:
        raise HTTPException(500, "Auth not initialized")
    await _jwt_manager.revoke_session(session_id)
    if _audit_log:
        await _audit_log.log_event(
            "token_revoked", details=f"session={session_id}", ip_address=request.client.host if request.client else ""
        )
    return JSONResponse({"ok": True, "session_id": session_id})
