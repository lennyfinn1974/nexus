"""Frontend static file serving — / and /admin (React SPA)."""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse

router = APIRouter(tags=["frontend"])

# Resolved at import time — BASE_DIR is set by app.py before routers are included
BASE_DIR: str = ""

_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def init(base_dir: str) -> None:
    global BASE_DIR
    BASE_DIR = base_dir


@router.get("/", response_class=HTMLResponse)
async def serve_ui():
    frontend_path = os.path.join(BASE_DIR, "frontend", "index.html")
    if os.path.exists(frontend_path):
        with open(frontend_path) as f:
            return HTMLResponse(f.read(), headers=_NO_CACHE)
    return HTMLResponse("<h1>Nexus</h1><p>Frontend not found.</p>")


def _serve_admin_spa():
    """Return the React SPA index.html, falling back to legacy admin.html."""
    # React SPA build (production)
    spa_path = os.path.join(BASE_DIR, "frontend", "admin-build", "index.html")
    if os.path.exists(spa_path):
        with open(spa_path) as f:
            return HTMLResponse(f.read(), headers=_NO_CACHE)
    # Fallback to legacy admin.html
    legacy_path = os.path.join(BASE_DIR, "frontend", "admin.html")
    if os.path.exists(legacy_path):
        with open(legacy_path) as f:
            return HTMLResponse(f.read(), headers=_NO_CACHE)
    return HTMLResponse("<h1>Admin panel not found</h1>")


@router.get("/admin", response_class=HTMLResponse)
async def serve_admin():
    return _serve_admin_spa()


@router.get("/admin/{path:path}")
async def serve_admin_spa(path: str):
    """Serve React SPA assets or fall through to index.html for client-side routing."""
    # Serve static assets from the build directory
    asset_path = os.path.join(BASE_DIR, "frontend", "admin-build", path)
    if os.path.isfile(asset_path):
        return FileResponse(asset_path)
    # All other paths → SPA index.html (client-side routing)
    return _serve_admin_spa()
