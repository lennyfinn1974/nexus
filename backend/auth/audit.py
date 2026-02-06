"""Security audit trail for authentication events."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("nexus.auth.audit")


class AuthAuditLog:
    """Write and query the auth_audit table."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def log_event(
        self,
        event_type: str,
        user_id: str = "",
        email: str = "",
        ip_address: str = "",
        details: str = "",
        success: bool = True,
    ):
        from storage.models import AuthAudit

        now = datetime.now(timezone.utc)
        try:
            async with self._sf() as session:
                session.add(AuthAudit(
                    event_type=event_type, user_id=user_id, email=email,
                    ip_address=ip_address, details=details, success=success, created_at=now,
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"Audit log failed: {e}")

    async def get_recent_events(self, limit: int = 100, event_type: str = None) -> list:
        from storage.models import AuthAudit

        async with self._sf() as session:
            stmt = select(AuthAudit)
            if event_type:
                stmt = stmt.where(AuthAudit.event_type == event_type)
            stmt = stmt.order_by(AuthAudit.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return [{
                "id": r.id, "event_type": r.event_type, "user_id": r.user_id,
                "email": r.email, "ip_address": r.ip_address, "details": r.details,
                "success": r.success,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            } for r in result.scalars().all()]

    async def get_failed_logins(self, ip: str = None, limit: int = 50) -> list:
        from storage.models import AuthAudit

        async with self._sf() as session:
            stmt = select(AuthAudit).where(AuthAudit.event_type == "login_failed")
            if ip:
                stmt = stmt.where(AuthAudit.ip_address == ip)
            stmt = stmt.order_by(AuthAudit.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return [{
                "id": r.id, "event_type": r.event_type, "email": r.email,
                "ip_address": r.ip_address, "details": r.details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            } for r in result.scalars().all()]

    async def cleanup_old_events(self, days: int = 90) -> int:
        from storage.models import AuthAudit

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with self._sf() as session:
            result = await session.execute(
                sa_delete(AuthAudit).where(AuthAudit.created_at < cutoff)
            )
            await session.commit()
            return result.rowcount
