"""Sovereign Command Client — REST client for sovereign-core on port 8090."""

import logging
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger("nexus.sovereign")


class SovereignClient:
    """Lightweight client for the sovereign-core command engine.

    Endpoints:
    - POST /cmd — execute a sovereign command
    - GET /cmd/list — list available commands
    - GET /health — health check
    - GET /status — system status
    """

    def __init__(self, base_url: str = "http://localhost:8090"):
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self._available = False

    async def connect(self):
        """Create HTTP session and check availability."""
        self._session = aiohttp.ClientSession()
        try:
            async with self._session.get(
                f"{self.base_url}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    self._available = True
                    logger.info(f"Sovereign-core connected at {self.base_url}")
                else:
                    logger.info(f"Sovereign-core returned {resp.status} — unavailable")
        except Exception as e:
            logger.info(f"Sovereign-core not available: {e}")
            self._available = False

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def is_available(self) -> bool:
        return self._available

    async def execute(self, command: str, context: str = "") -> Dict[str, Any]:
        """Execute a sovereign command (e.g. 'BLD:APP', 'SYS:STATUS').

        Returns dict with: content, tier, model, duration_ms, or error.
        """
        if not self._session or not self._available:
            return {"error": "Sovereign-core not available"}

        try:
            payload = {"command": command}
            if context:
                payload["context"] = context

            async with self._session.post(
                f"{self.base_url}/cmd",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    text = await resp.text()
                    return {"error": f"HTTP {resp.status}: {text}"}
        except Exception as e:
            return {"error": str(e)}

    async def list_commands(self) -> Dict[str, Any]:
        """Get list of available sovereign commands."""
        if not self._session or not self._available:
            return {"error": "Sovereign-core not available"}

        try:
            async with self._session.get(
                f"{self.base_url}/cmd/list",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"error": str(e)}

    async def health(self) -> Dict[str, Any]:
        """Check sovereign-core health."""
        if not self._session:
            return {"status": "disconnected"}

        try:
            async with self._session.get(
                f"{self.base_url}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    self._available = True
                    return await resp.json()
                self._available = False
                return {"status": "error", "code": resp.status}
        except Exception as e:
            self._available = False
            return {"status": "error", "message": str(e)}

    async def status(self) -> Dict[str, Any]:
        """Get sovereign-core system status."""
        if not self._session or not self._available:
            return {"error": "Sovereign-core not available"}

        try:
            async with self._session.get(
                f"{self.base_url}/status",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"error": str(e)}
