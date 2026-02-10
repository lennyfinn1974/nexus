"""IP validation & brute-force protection."""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("nexus.auth.ip")


class IPSecurity:
    """Permanent IP blocks (DB) + temporary lockouts (in-memory) for brute-force protection."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], max_attempts: int = 5, lockout_window: int = 300
    ):
        self._sf = session_factory
        self._max_attempts = max_attempts
        self._lockout_window = lockout_window  # seconds
        # In-memory: {ip: [timestamp, ...]}
        self._attempts: dict[str, list[float]] = {}
        self._blocked_ips: set[str] = set()

    async def load_blocked_ips(self):
        """Load permanent blocks from DB on startup."""
        from storage.models import BlockedIP

        async with self._sf() as session:
            result = await session.execute(select(BlockedIP.ip_address))
            self._blocked_ips = {r[0] for r in result.all()}
        if self._blocked_ips:
            logger.info(f"Loaded {len(self._blocked_ips)} blocked IPs")

    def is_blocked(self, ip: str) -> bool:
        """Check if IP is permanently blocked or temporarily locked out."""
        if ip in self._blocked_ips:
            return True
        # Check temp lockout
        attempts = self._attempts.get(ip, [])
        now = time.time()
        recent = [t for t in attempts if now - t < self._lockout_window]
        self._attempts[ip] = recent
        return len(recent) >= self._max_attempts

    def record_failed_attempt(self, ip: str):
        if ip not in self._attempts:
            self._attempts[ip] = []
        self._attempts[ip].append(time.time())

    def record_successful_login(self, ip: str):
        self._attempts.pop(ip, None)

    async def block_ip(self, ip: str, reason: str = "", blocked_by: str = ""):
        from storage.models import BlockedIP

        now = datetime.now(timezone.utc)
        async with self._sf() as session:
            # Check if already blocked
            existing = await session.execute(select(BlockedIP).where(BlockedIP.ip_address == ip))
            if existing.scalar_one_or_none():
                return
            session.add(BlockedIP(ip_address=ip, reason=reason, blocked_by=blocked_by, blocked_at=now))
            await session.commit()
        self._blocked_ips.add(ip)

    async def unblock_ip(self, ip: str):
        from storage.models import BlockedIP

        async with self._sf() as session:
            await session.execute(sa_delete(BlockedIP).where(BlockedIP.ip_address == ip))
            await session.commit()
        self._blocked_ips.discard(ip)
        self._attempts.pop(ip, None)

    async def list_blocked_ips(self) -> list:
        from storage.models import BlockedIP

        async with self._sf() as session:
            result = await session.execute(select(BlockedIP).order_by(BlockedIP.blocked_at.desc()))
            return [
                {
                    "id": r.id,
                    "ip_address": r.ip_address,
                    "reason": r.reason,
                    "blocked_by": r.blocked_by,
                    "blocked_at": r.blocked_at.isoformat() if r.blocked_at else None,
                }
                for r in result.scalars().all()
            ]
