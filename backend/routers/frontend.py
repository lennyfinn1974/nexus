"""Frontend static file serving — / and /admin (React SPA)."""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["frontend"])

# Resolved at import time — BASE_DIR is set by app.py before routers are included
BASE_DIR: str = ""

_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _asset_cache_headers(path: str) -> dict:
    """Return appropriate cache headers for static assets.

    Vite-hashed filenames (e.g. index-abc123.js) are immutable and can be
    cached forever.  Everything else gets no-cache to ensure freshness.
    """
    import re
    if re.search(r'-[a-zA-Z0-9]{6,}\.(js|css)$', path):
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return _NO_CACHE


def init(base_dir: str) -> None:
    global BASE_DIR
    BASE_DIR = base_dir


def _serve_chat_spa():
    """Return the React chat SPA, falling back to vanilla index.html."""
    # React SPA build (production)
    spa_path = os.path.join(BASE_DIR, "frontend", "chat-build", "index.html")
    if os.path.exists(spa_path):
        with open(spa_path) as f:
            return HTMLResponse(f.read(), headers=_NO_CACHE)
    # Fallback to vanilla index.html
    legacy_path = os.path.join(BASE_DIR, "frontend", "index.html")
    if os.path.exists(legacy_path):
        with open(legacy_path) as f:
            return HTMLResponse(f.read(), headers=_NO_CACHE)
    return HTMLResponse("<h1>Nexus</h1><p>Frontend not found.</p>")


@router.get("/", response_class=HTMLResponse)
async def serve_ui():
    return _serve_chat_spa()


@router.get("/chat/{path:path}")
async def serve_chat_assets(path: str):
    """Serve React chat SPA assets."""
    asset_path = os.path.join(BASE_DIR, "frontend", "chat-build", path)
    if os.path.isfile(asset_path):
        return FileResponse(asset_path)
    return _serve_chat_spa()


@router.get("/assets/{path:path}")
async def serve_root_assets(path: str):
    """Serve Vite build assets from /assets/ path (used by both SPAs).

    Hashed filenames (index-abc123.js) get long-lived cache headers.
    Non-hashed assets get no-cache to ensure freshness.
    """
    # Try chat-build first
    chat_asset = os.path.join(BASE_DIR, "frontend", "chat-build", "assets", path)
    if os.path.isfile(chat_asset):
        return FileResponse(chat_asset, headers=_asset_cache_headers(path))
    # Then admin-build
    admin_asset = os.path.join(BASE_DIR, "frontend", "admin-build", "assets", path)
    if os.path.isfile(admin_asset):
        return FileResponse(admin_asset, headers=_asset_cache_headers(path))
    return HTMLResponse("Not found", status_code=404)


@router.get("/classic", response_class=HTMLResponse)
async def serve_classic_ui():
    """Serve the original vanilla JS chat UI."""
    legacy_path = os.path.join(BASE_DIR, "frontend", "index.html")
    if os.path.exists(legacy_path):
        with open(legacy_path) as f:
            return HTMLResponse(f.read(), headers=_NO_CACHE)
    return HTMLResponse("<h1>Classic UI not found</h1>")


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
