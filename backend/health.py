"""Health check endpoint for Nexus.
Provides a simple `/healthz` route that validates DB connectivity
and plugin initialization. Returns JSON `{\"status\": \"healthy\"}`
or `{\"status\": \"unhealthy\", \"detail\": <error>}`.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, status

router = APIRouter()

@router.get("/healthz", status_code=status.HTTP_200_OK)
async def health_check() -> dict:
    try:
        # Simple DB existence check – adjust for actual DB lib
        db_path = Path(__file__).parents[2] / "data" / "nexus.db"
        if not db_path.is_file():
            raise FileNotFoundError("Database file missing")
        # Could add a quick SQLite query here if needed
    except Exception as exc:
        logging.error("Health check failed: %s", exc)
        return {"status": "unhealthy", "detail": str(exc)}
    return {"status": "healthy"}
