Memory Admin API for Nexus"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse, FileResponse
import logging

logger = logging.getLogger("nexus.admin.memory")
router = APIRouter(prefix="/admin/memory