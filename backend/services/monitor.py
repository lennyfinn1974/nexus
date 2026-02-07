"""Service Health Monitor — checks health of all platform services."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import aiohttp

logger = logging.getLogger("nexus.services.monitor")


@dataclass
class ServiceStatus:
    """Status of a monitored service."""
    name: str
    url: str
    healthy: bool = False
    last_check: Optional[float] = None
    last_healthy: Optional[float] = None
    response_ms: float = 0
    error: str = ""
    consecutive_failures: int = 0


class ServiceMonitor:
    """Monitor health of all platform services.

    Checks:
    - Nexus (self, port 8081)
    - Sovereign-core (port 8090)
    - Kanban (port 5174)
    - Trading (port 3000)
    - Ollama (port 11434)
    """

    DEFAULT_SERVICES = {
        "nexus": "http://localhost:8081/health",
        "sovereign-core": "http://localhost:8090/health",
        "kanban": "http://localhost:5174",
        "trading": "http://localhost:3000",
        "ollama": "http://localhost:11434/api/tags",
    }

    def __init__(self, services: Optional[Dict[str, str]] = None, interval: float = 60):
        self._services: Dict[str, ServiceStatus] = {}
        service_map = services or self.DEFAULT_SERVICES
        for name, url in service_map.items():
            self._services[name] = ServiceStatus(name=name, url=url)
        self._interval = interval
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the monitoring loop."""
        self._session = aiohttp.ClientSession()
        self._running = True
        # Do initial check
        await self.check_all()
        # Start background loop
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Service monitor started ({len(self._services)} services, {self._interval}s interval)")

    async def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()

    async def _monitor_loop(self):
        while self._running:
            await asyncio.sleep(self._interval)
            await self.check_all()

    async def check_all(self):
        """Check health of all services concurrently."""
        tasks = [self._check_service(svc) for svc in self._services.values()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_service(self, svc: ServiceStatus):
        """Check a single service's health."""
        start = time.time()
        try:
            async with self._session.get(
                svc.url,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                elapsed = (time.time() - start) * 1000
                svc.response_ms = elapsed
                svc.last_check = time.time()

                if resp.status < 500:
                    svc.healthy = True
                    svc.last_healthy = time.time()
                    svc.error = ""
                    svc.consecutive_failures = 0
                else:
                    svc.healthy = False
                    svc.error = f"HTTP {resp.status}"
                    svc.consecutive_failures += 1
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            svc.response_ms = elapsed
            svc.last_check = time.time()
            svc.healthy = False
            svc.error = str(e)
            svc.consecutive_failures += 1

    def get_status(self) -> Dict[str, dict]:
        """Get status of all services."""
        result = {}
        for name, svc in self._services.items():
            result[name] = {
                "healthy": svc.healthy,
                "url": svc.url,
                "response_ms": round(svc.response_ms, 1),
                "last_check": svc.last_check,
                "error": svc.error,
                "consecutive_failures": svc.consecutive_failures,
            }
        return result

    def get_summary(self) -> str:
        """Get a formatted summary string."""
        lines = ["**Platform Services:**"]
        for name, svc in self._services.items():
            icon = "OK" if svc.healthy else "DOWN"
            ms = f"{svc.response_ms:.0f}ms" if svc.response_ms > 0 else "N/A"
            error_str = f" ({svc.error})" if svc.error else ""
            lines.append(f"- {name}: [{icon}] {ms}{error_str}")
        return "\n".join(lines)

    @property
    def all_healthy(self) -> bool:
        return all(svc.healthy for svc in self._services.values())
