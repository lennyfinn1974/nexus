"""User management — CRUD, whitelist, role management."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("nexus.auth.users")


class UserManager:
    """Manage users and email whitelist."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    # ── Users ────────────────────────────────────────────────────

    async def find_or_create_user(self, email: str, name: str = "", picture: str = "", ip: str = "") -> dict:
        """Find existing user by email, or create a new one.

        First user is auto-promoted to admin.
        """
        from storage.models import User

        async with self._sf() as session:
            result = await session.execute(select(User).where(User.email == email))
            user_obj = result.scalar_one_or_none()

            if user_obj:
                now = datetime.now(timezone.utc)
                user_obj.last_login = now
                user_obj.last_ip = ip
                if name:
                    user_obj.name = name
                if picture:
                    user_obj.picture = picture
                await session.commit()
                return {
                    "id": user_obj.id, "email": user_obj.email, "name": user_obj.name,
                    "picture": user_obj.picture, "role": user_obj.role, "active": user_obj.active,
                    "created_at": user_obj.created_at.isoformat() if user_obj.created_at else None,
                    "last_login": now.isoformat(), "last_ip": ip,
                }

            # New user — check if first user (auto-admin)
            count_result = await session.execute(select(func.count()).select_from(User))
            is_first = count_result.scalar_one() == 0

            user_id = uuid.uuid4().hex
            now = datetime.now(timezone.utc)
            role = "admin" if is_first else "user"

            user_obj = User(
                id=user_id, email=email, name=name, picture=picture,
                role=role, active=True, created_at=now, last_login=now, last_ip=ip,
            )
            session.add(user_obj)
            await session.commit()

            if is_first:
                logger.info(f"First user {email} auto-promoted to admin")

            return {
                "id": user_id, "email": email, "name": name, "picture": picture,
                "role": role, "active": True, "created_at": now.isoformat(),
                "last_login": now.isoformat(), "last_ip": ip,
            }

    async def get_user(self, user_id: str) -> dict | None:
        from storage.models import User

        async with self._sf() as session:
            user_obj = await session.get(User, user_id)
            if not user_obj:
                return None
            return self._to_dict(user_obj)

    async def get_user_by_email(self, email: str) -> dict | None:
        from storage.models import User

        async with self._sf() as session:
            result = await session.execute(select(User).where(User.email == email))
            user_obj = result.scalar_one_or_none()
            return self._to_dict(user_obj) if user_obj else None

    async def list_users(self) -> list:
        from storage.models import User

        async with self._sf() as session:
            result = await session.execute(select(User).order_by(User.created_at.desc()))
            return [self._to_dict(r) for r in result.scalars().all()]

    async def update_user_role(self, user_id: str, role: str) -> bool:
        from storage.models import User

        if role not in ("user", "admin"):
            return False
        async with self._sf() as session:
            await session.execute(update(User).where(User.id == user_id).values(role=role))
            await session.commit()
        return True

    async def deactivate_user(self, user_id: str):
        from storage.models import User

        async with self._sf() as session:
            await session.execute(update(User).where(User.id == user_id).values(active=False))
            await session.commit()

    async def activate_user(self, user_id: str):
        from storage.models import User

        async with self._sf() as session:
            await session.execute(update(User).where(User.id == user_id).values(active=True))
            await session.commit()

    async def update_last_login(self, user_id: str, ip: str = ""):
        from storage.models import User

        now = datetime.now(timezone.utc)
        async with self._sf() as session:
            await session.execute(
                update(User).where(User.id == user_id).values(last_login=now, last_ip=ip)
            )
            await session.commit()

    @staticmethod
    def _to_dict(user_obj) -> dict:
        return {
            "id": user_obj.id, "email": user_obj.email, "name": user_obj.name,
            "picture": user_obj.picture, "role": user_obj.role, "active": user_obj.active,
            "created_at": user_obj.created_at.isoformat() if user_obj.created_at else None,
            "last_login": user_obj.last_login.isoformat() if user_obj.last_login else None,
            "last_ip": user_obj.last_ip,
        }

    # ── Whitelist ────────────────────────────────────────────────

    async def is_whitelisted(self, email: str, mode: str = "open") -> bool:
        from storage.models import Whitelist

        if mode == "open":
            return True
        async with self._sf() as session:
            result = await session.execute(select(Whitelist).where(Whitelist.email == email))
            return result.scalar_one_or_none() is not None

    async def add_to_whitelist(self, email: str, added_by: str = "") -> bool:
        from storage.models import Whitelist

        now = datetime.now(timezone.utc)
        async with self._sf() as session:
            # Check if already exists
            existing = await session.execute(select(Whitelist).where(Whitelist.email == email))
            if existing.scalar_one_or_none():
                return False
            session.add(Whitelist(email=email, added_by=added_by, added_at=now))
            await session.commit()
        return True

    async def remove_from_whitelist(self, email: str):
        from storage.models import Whitelist

        async with self._sf() as session:
            await session.execute(delete(Whitelist).where(Whitelist.email == email))
            await session.commit()

    async def list_whitelist(self) -> list:
        from storage.models import Whitelist

        async with self._sf() as session:
            result = await session.execute(select(Whitelist).order_by(Whitelist.added_at.desc()))
            return [{
                "id": r.id, "email": r.email, "added_by": r.added_by,
                "added_at": r.added_at.isoformat() if r.added_at else None,
            } for r in result.scalars().all()]
