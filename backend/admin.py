"""Admin API — settings, plugins, system management, and log streaming."""

import asyncio
import ipaddress
import json
import logging
import os
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

    # Legacy fallback: ADMIN_API_KEY bearer token
    expected = os.environ.get("ADMIN_API_KEY", "")
    if expected and credentials and credentials.credentials == expected:
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
):
    """Called from app.py during startup."""
    global _cfg, _plugins, _models, _db, _task_queue, _skills
    global _jwt_manager, _user_manager, _ip_security, _audit_log
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


# URL-type settings that must pass SSRF validation on save
_URL_SETTINGS = {"OLLAMA_BASE_URL"}


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
        # Validate URL-type settings against SSRF
        if key in _URL_SETTINGS and value:
            try:
                validate_url(str(value))
            except ValueError as e:
                return JSONResponse({"error": f"Invalid URL for {key}: {e}"}, status_code=400)
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
            base_url = validate_url(_cfg.ollama_base_url)
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
            "complexity_threshold": _cfg.complexity_threshold,
        }
    )


@router.get("/models/ollama-list")
async def list_ollama_models():
    """Fetch available models from the connected Ollama instance."""
    try:
        base_url = validate_url(_cfg.ollama_base_url)
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


@router.post("/backup")
async def create_backup():
    return JSONResponse(
        {
            "error": "Backup is managed by Supabase. Use the Supabase dashboard " "or pg_dump for PostgreSQL backups.",
        },
        status_code=400,
    )


@router.get("/backups")
async def list_backups():
    backup_dir = os.path.join(_cfg.data_dir, "backups")
    if not os.path.isdir(backup_dir):
        return JSONResponse([])
    backups = []
    for f in sorted(os.listdir(backup_dir), reverse=True):
        if f.endswith(".db"):
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
