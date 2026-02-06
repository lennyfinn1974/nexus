"""PostgreSQL storage for conversations, skills, and tasks.

Uses SQLAlchemy async sessions (one session per method call).
Public API is identical to the original aiosqlite version — all methods
return plain dicts with ISO-formatted datetime strings.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from storage.models import Conversation, Message, Skill, Task

logger = logging.getLogger("nexus.storage")


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert a datetime to ISO string, matching the old SQLite format."""
    if dt is None:
        return None
    return dt.isoformat()


def _row_to_dict(obj, columns: list[str]) -> dict:
    """Convert an ORM object to a dict with ISO datetime strings."""
    d = {}
    for col in columns:
        val = getattr(obj, col)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col] = val
    return d


_CONV_COLS = ["id", "title", "created_at", "updated_at"]
_MSG_COLS = ["id", "conversation_id", "role", "content", "model_used", "tokens_in", "tokens_out", "created_at"]
_SKILL_COLS = ["id", "name", "description", "domain", "file_path", "created_at", "updated_at", "usage_count", "last_used_at"]
_TASK_COLS = ["id", "type", "status", "payload", "result", "error", "created_at", "started_at", "completed_at"]


class Database:
    """Async PostgreSQL storage using SQLAlchemy sessions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    # ── Lifecycle (no-ops — engine lifecycle is external) ─────────

    async def connect(self):
        """No-op. Kept for API compatibility."""
        pass

    async def close(self):
        """No-op. Engine disposal is handled externally."""
        pass

    # ── Conversations ────────────────────────────────────────────

    async def create_conversation(self, conv_id: str, title: str = "New Conversation") -> dict:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            conv = Conversation(id=conv_id, title=title, created_at=now, updated_at=now)
            session.add(conv)
            await session.commit()
        return {"id": conv_id, "title": title, "created_at": now.isoformat()}

    async def list_conversations(self, limit: int = 50) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
            )
            rows = result.scalars().all()
            return [_row_to_dict(r, _CONV_COLS) for r in rows]

    async def get_conversation(self, conv_id: str) -> Optional[dict]:
        async with self._session_factory() as session:
            conv = await session.get(Conversation, conv_id)
            if conv is None:
                return None
            return _row_to_dict(conv, _CONV_COLS)

    async def get_conversation_messages(self, conv_id: str, limit: int = 100) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Message)
                .where(Message.conversation_id == conv_id)
                .order_by(Message.created_at.asc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [_row_to_dict(r, _MSG_COLS) for r in rows]

    async def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        model_used: str = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> dict:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            msg = Message(
                conversation_id=conv_id,
                role=role,
                content=content,
                model_used=model_used,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                created_at=now,
            )
            session.add(msg)
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conv_id)
                .values(updated_at=now)
            )
            await session.commit()
            await session.refresh(msg)
        return {"id": msg.id, "role": role, "content": content, "model_used": model_used}

    async def delete_conversation(self, conv_id: str):
        async with self._session_factory() as session:
            await session.execute(delete(Message).where(Message.conversation_id == conv_id))
            await session.execute(delete(Conversation).where(Conversation.id == conv_id))
            await session.commit()

    async def rename_conversation(self, conv_id: str, title: str):
        async with self._session_factory() as session:
            await session.execute(
                update(Conversation).where(Conversation.id == conv_id).values(title=title)
            )
            await session.commit()

    # ── Skills ───────────────────────────────────────────────────

    async def save_skill(self, skill_id: str, name: str, description: str, domain: str, file_path: str) -> dict:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            existing = await session.get(Skill, skill_id)
            if existing:
                existing.name = name
                existing.description = description
                existing.domain = domain
                existing.file_path = file_path
                existing.updated_at = now
            else:
                session.add(Skill(
                    id=skill_id, name=name, description=description,
                    domain=domain, file_path=file_path, created_at=now, updated_at=now,
                ))
            await session.commit()
        return {"id": skill_id, "name": name, "domain": domain}

    async def list_skills(self) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Skill).order_by(Skill.usage_count.desc())
            )
            return [_row_to_dict(r, _SKILL_COLS) for r in result.scalars().all()]

    async def find_skills_by_domain(self, domain: str) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Skill)
                .where(Skill.domain.ilike(f"%{domain}%"))
                .order_by(Skill.usage_count.desc())
            )
            return [_row_to_dict(r, _SKILL_COLS) for r in result.scalars().all()]

    async def increment_skill_usage(self, skill_id: str):
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            await session.execute(
                update(Skill)
                .where(Skill.id == skill_id)
                .values(usage_count=Skill.usage_count + 1, last_used_at=now)
            )
            await session.commit()

    async def delete_skill(self, skill_id: str):
        async with self._session_factory() as session:
            await session.execute(delete(Skill).where(Skill.id == skill_id))
            await session.commit()

    # ── Tasks ────────────────────────────────────────────────────

    async def create_task(self, task_id: str, task_type: str, payload: dict = None) -> dict:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            session.add(Task(
                id=task_id,
                type=task_type,
                payload=json.dumps(payload) if payload else None,
                created_at=now,
            ))
            await session.commit()
        return {"id": task_id, "type": task_type, "status": "pending"}

    async def update_task(self, task_id: str, status: str, result: str = None, error: str = None):
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {"status": status}

        if status == "running":
            values["started_at"] = now
        elif status in ("completed", "failed"):
            values["completed_at"] = now

        if result is not None:
            values["result"] = result
        if error is not None:
            values["error"] = error

        async with self._session_factory() as session:
            await session.execute(
                update(Task).where(Task.id == task_id).values(**values)
            )
            await session.commit()

    async def list_tasks(self, status: str = None, limit: int = 50) -> list[dict]:
        async with self._session_factory() as session:
            stmt = select(Task)
            if status:
                stmt = stmt.where(Task.status == status)
            stmt = stmt.order_by(Task.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return [_row_to_dict(r, _TASK_COLS) for r in result.scalars().all()]

    # ── New Encapsulated Methods (used by admin.py) ──────────────

    async def get_usage_stats(self) -> dict:
        """Token usage statistics grouped by model and day."""
        async with self._session_factory() as session:
            # Daily breakdown
            daily_result = await session.execute(text("""
                SELECT
                    model_used,
                    COUNT(*) as message_count,
                    COALESCE(SUM(tokens_in), 0) as total_tokens_in,
                    COALESCE(SUM(tokens_out), 0) as total_tokens_out,
                    CAST(created_at AS DATE) as day
                FROM messages
                WHERE role = 'assistant' AND model_used IS NOT NULL
                GROUP BY model_used, CAST(created_at AS DATE)
                ORDER BY day DESC
                LIMIT 60
            """))
            daily = [dict(r._mapping) for r in daily_result]
            # Convert date objects to strings
            for row in daily:
                if hasattr(row.get("day"), "isoformat"):
                    row["day"] = row["day"].isoformat()

            # Totals per model
            totals_result = await session.execute(text("""
                SELECT
                    model_used,
                    COUNT(*) as message_count,
                    COALESCE(SUM(tokens_in), 0) as total_tokens_in,
                    COALESCE(SUM(tokens_out), 0) as total_tokens_out
                FROM messages
                WHERE role = 'assistant' AND model_used IS NOT NULL
                GROUP BY model_used
            """))
            totals = [dict(r._mapping) for r in totals_result]

        return {"daily": daily, "totals": totals}

    async def get_message_count(self, conv_id: str) -> int:
        """Return the number of messages in a conversation."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count()).select_from(Message).where(Message.conversation_id == conv_id)
            )
            return result.scalar_one()

    async def execute_query(self, query: str) -> Any:
        """Execute a raw SQL query and return all rows. Used by health checks."""
        async with self._session_factory() as session:
            result = await session.execute(text(query))
            return result.fetchall()
