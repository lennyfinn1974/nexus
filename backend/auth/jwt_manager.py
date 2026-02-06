"""JWT token lifecycle — access tokens, refresh tokens, session management."""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone, timedelta

import jwt
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("nexus.auth.jwt")


class JWTManager:
    """Create and verify JWTs; manage refresh-token sessions in the DB."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], nexus_secret: bytes,
                 access_ttl: int = 1800, refresh_ttl: int = 604800):
        self._sf = session_factory
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        # Derive signing key from the existing .nexus_secret
        self._key = hashlib.sha256(b"nexus-jwt:" + nexus_secret).hexdigest()

    # ── Access Tokens ────────────────────────────────────────────

    def create_access_token(self, user: dict) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user["id"],
            "email": user["email"],
            "name": user.get("name", ""),
            "role": user.get("role", "user"),
            "jti": uuid.uuid4().hex,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(seconds=self._access_ttl),
        }
        return jwt.encode(payload, self._key, algorithm="HS256")

    def verify_access_token(self, token: str) -> dict | None:
        try:
            payload = jwt.decode(token, self._key, algorithms=["HS256"])
            if payload.get("type") != "access":
                return None
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    # ── Refresh Tokens ───────────────────────────────────────────

    async def create_refresh_token(self, user: dict, ip: str = "", user_agent: str = "") -> tuple[str, str]:
        """Return (raw_token, session_id). Hash is stored in DB."""
        from storage.models import ActiveSession

        raw = uuid.uuid4().hex + uuid.uuid4().hex
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        session_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self._refresh_ttl)

        async with self._sf() as session:
            session.add(ActiveSession(
                id=session_id,
                user_id=user["id"],
                refresh_token_hash=token_hash,
                ip_address=ip,
                user_agent=user_agent,
                created_at=now,
                expires_at=expires,
            ))
            await session.commit()
        return raw, session_id

    async def refresh_tokens(self, raw_token: str, ip: str = "", user_agent: str = "") -> dict | None:
        """Rotate refresh token: verify old, issue new access + refresh.

        Returns dict with access_token, refresh_token, session_id, user — or None.
        """
        from storage.models import ActiveSession, User

        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        now = datetime.now(timezone.utc)

        async with self._sf() as session:
            result = await session.execute(
                select(ActiveSession, User)
                .join(User, ActiveSession.user_id == User.id)
                .where(
                    ActiveSession.refresh_token_hash == token_hash,
                    ActiveSession.revoked == False,
                    ActiveSession.expires_at > now,
                )
            )
            row = result.first()
            if not row:
                return None

            sess_obj, user_obj = row
            if not user_obj.active:
                return None

            user = {
                "id": user_obj.id,
                "email": user_obj.email,
                "name": user_obj.name or "",
                "role": user_obj.role,
            }

            # Revoke old session
            sess_obj.revoked = True
            await session.commit()

        # Issue new tokens
        access = self.create_access_token(user)
        refresh, new_session_id = await self.create_refresh_token(user, ip, user_agent)

        return {
            "access_token": access,
            "refresh_token": refresh,
            "session_id": new_session_id,
            "user": user,
        }

    # ── Session Management ───────────────────────────────────────

    async def revoke_session(self, session_id: str):
        from storage.models import ActiveSession

        async with self._sf() as session:
            await session.execute(
                update(ActiveSession).where(ActiveSession.id == session_id).values(revoked=True)
            )
            await session.commit()

    async def revoke_all_user_sessions(self, user_id: str):
        from storage.models import ActiveSession

        async with self._sf() as session:
            await session.execute(
                update(ActiveSession).where(ActiveSession.user_id == user_id).values(revoked=True)
            )
            await session.commit()

    async def cleanup_expired_sessions(self) -> int:
        from storage.models import ActiveSession

        now = datetime.now(timezone.utc)
        async with self._sf() as session:
            result = await session.execute(
                delete(ActiveSession).where(
                    (ActiveSession.expires_at < now) | (ActiveSession.revoked == True)
                )
            )
            await session.commit()
            return result.rowcount

    async def list_user_sessions(self, user_id: str) -> list:
        from storage.models import ActiveSession

        async with self._sf() as session:
            result = await session.execute(
                select(ActiveSession)
                .where(ActiveSession.user_id == user_id)
                .order_by(ActiveSession.created_at.desc())
            )
            rows = result.scalars().all()
            return [{
                "id": r.id,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "revoked": r.revoked,
            } for r in rows]

    # ── Short-lived WS Token ─────────────────────────────────────

    def create_ws_token(self, user: dict) -> str:
        """60-second single-use token for WebSocket handshake."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user["id"],
            "email": user["email"],
            "name": user.get("name", ""),
            "role": user.get("role", "user"),
            "jti": uuid.uuid4().hex,
            "type": "ws",
            "iat": now,
            "exp": now + timedelta(seconds=60),
        }
        return jwt.encode(payload, self._key, algorithm="HS256")

    def verify_ws_token(self, token: str) -> dict | None:
        try:
            payload = jwt.decode(token, self._key, algorithms=["HS256"])
            if payload.get("type") != "ws":
                return None
            return payload
        except jwt.InvalidTokenError:
            return None
