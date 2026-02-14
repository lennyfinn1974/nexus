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
    """Return the React chat SPA."""
    spa_path = os.path.join(BASE_DIR, "frontend", "chat-build", "index.html")
    if os.path.exists(spa_path):
        with open(spa_path) as f:
            return HTMLResponse(f.read(), headers=_NO_CACHE)
    return HTMLResponse(
        "<h1>Nexus</h1><p>Chat UI not built. Run: <code>cd chat-ui && npm run build</code></p>"
    )


@router.get("/", response_class=HTMLResponse)
async def serve_ui():
    return _serve_chat_spa()


@router.get("/favicon.svg")
async def serve_favicon():
    """Serve the Nexus favicon."""
    for build_dir in ("chat-build", "admin-build"):
        path = os.path.join(BASE_DIR, "frontend", build_dir, "favicon.svg")
        if os.path.isfile(path):
            return FileResponse(path, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})
    # Inline fallback — the N logo
    return HTMLResponse(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#f97316"/><text x="16" y="23" text-anchor="middle" font-family="DM Sans,sans-serif" font-weight="700" font-size="20" fill="white">N</text></svg>',
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


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


def _serve_admin_spa():
    """Return the React admin SPA."""
    spa_path = os.path.join(BASE_DIR, "frontend", "admin-build", "index.html")
    if os.path.exists(spa_path):
        with open(spa_path) as f:
            return HTMLResponse(f.read(), headers=_NO_CACHE)
    return HTMLResponse(
        "<h1>Admin panel not built. Run: <code>cd admin-ui && npm run build</code></h1>"
    )


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
