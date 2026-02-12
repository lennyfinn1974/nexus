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
from storage.models import (
    Conversation, ConversationSummary, Message, PairingCode, Skill, Task, TelegramPairing,
)

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
_SKILL_COLS = [
    "id",
    "name",
    "description",
    "domain",
    "file_path",
    "created_at",
    "updated_at",
    "usage_count",
    "last_used_at",
]
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
            result = await session.execute(select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit))
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
            # Subquery: get IDs of the most recent `limit` messages
            subq = (
                select(Message.id)
                .where(Message.conversation_id == conv_id)
                .order_by(Message.created_at.desc())
                .limit(limit)
            ).subquery()
            # Main query: fetch those messages in chronological order
            result = await session.execute(
                select(Message)
                .where(Message.id.in_(select(subq.c.id)))
                .order_by(Message.created_at.asc())
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
            await session.execute(update(Conversation).where(Conversation.id == conv_id).values(updated_at=now))
            await session.commit()
            await session.refresh(msg)
        return {"id": msg.id, "role": role, "content": content, "model_used": model_used}

    # ── Conversation Summaries ──

    async def get_conversation_summary(self, conv_id: str) -> Optional[str]:
        """Get the most recent conversation summary."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationSummary)
                .where(ConversationSummary.conversation_id == conv_id)
                .order_by(ConversationSummary.created_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return row.summary_text if row else None

    async def get_conversation_summary_detail(self, conv_id: str) -> Optional[dict]:
        """Get summary with metadata (messages_covered, created_at)."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationSummary)
                .where(ConversationSummary.conversation_id == conv_id)
                .order_by(ConversationSummary.created_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "summary_text": row.summary_text,
                "messages_covered": row.messages_covered,
                "created_at": _dt_to_iso(row.created_at),
            }

    async def save_conversation_summary(self, conv_id: str, summary: str, messages_covered: int) -> None:
        """Save a conversation summary (appends new row — latest is always used)."""
        async with self._session_factory() as session:
            session.add(ConversationSummary(
                conversation_id=conv_id,
                summary_text=summary,
                messages_covered=messages_covered,
            ))
            await session.commit()

    async def ensure_summary_table(self) -> None:
        """Create the conversation_summaries table if it doesn't exist."""
        async with self._session_factory() as session:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id SERIAL PRIMARY KEY,
                    conversation_id VARCHAR NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    summary_text TEXT NOT NULL,
                    messages_covered INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_conv_summaries_conv
                ON conversation_summaries (conversation_id)
            """))
            await session.commit()
        logger.info("Ensured conversation_summaries table exists")

    async def delete_conversation(self, conv_id: str):
        async with self._session_factory() as session:
            await session.execute(delete(Message).where(Message.conversation_id == conv_id))
            await session.execute(delete(Conversation).where(Conversation.id == conv_id))
            await session.commit()

    async def rename_conversation(self, conv_id: str, title: str):
        async with self._session_factory() as session:
            await session.execute(update(Conversation).where(Conversation.id == conv_id).values(title=title))
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
                session.add(
                    Skill(
                        id=skill_id,
                        name=name,
                        description=description,
                        domain=domain,
                        file_path=file_path,
                        created_at=now,
                        updated_at=now,
                    )
                )
            await session.commit()
        return {"id": skill_id, "name": name, "domain": domain}

    async def list_skills(self) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(select(Skill).order_by(Skill.usage_count.desc()))
            return [_row_to_dict(r, _SKILL_COLS) for r in result.scalars().all()]

    async def find_skills_by_domain(self, domain: str) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Skill).where(Skill.domain.ilike(f"%{domain}%")).order_by(Skill.usage_count.desc())
            )
            return [_row_to_dict(r, _SKILL_COLS) for r in result.scalars().all()]

    async def increment_skill_usage(self, skill_id: str):
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            await session.execute(
                update(Skill).where(Skill.id == skill_id).values(usage_count=Skill.usage_count + 1, last_used_at=now)
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
            session.add(
                Task(
                    id=task_id,
                    type=task_type,
                    payload=json.dumps(payload) if payload else None,
                    created_at=now,
                )
            )
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
            await session.execute(update(Task).where(Task.id == task_id).values(**values))
            await session.commit()

    async def list_tasks(self, status: str = None, limit: int = 50) -> list[dict]:
        async with self._session_factory() as session:
            stmt = select(Task)
            if status:
                stmt = stmt.where(Task.status == status)
            stmt = stmt.order_by(Task.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return [_row_to_dict(r, _TASK_COLS) for r in result.scalars().all()]

    # ── Work Items ─────────────────────────────────────────────────

    async def ensure_work_items_table(self) -> None:
        """Create the work_items table if it doesn't exist."""
        async with self._session_factory() as session:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS work_items (
                    id VARCHAR PRIMARY KEY,
                    kind VARCHAR NOT NULL,
                    title VARCHAR NOT NULL,
                    status VARCHAR NOT NULL DEFAULT 'pending',
                    parent_id VARCHAR,
                    conv_id VARCHAR,
                    model VARCHAR,
                    metadata JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ
                )
            """))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items (status, created_at)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_work_items_parent ON work_items (parent_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_work_items_conv ON work_items (conv_id)"
            ))
            await session.commit()
        logger.info("Ensured work_items table exists")

    async def upsert_work_item(
        self,
        item_id: str,
        kind: str,
        title: str,
        status: str = "pending",
        parent_id: str = None,
        conv_id: str = None,
        model: str = None,
        metadata: dict = None,
    ) -> dict:
        """Insert or update a work item."""
        now = datetime.now(timezone.utc)
        meta_json = json.dumps(metadata) if metadata else None
        async with self._session_factory() as session:
            await session.execute(text("""
                INSERT INTO work_items (id, kind, title, status, parent_id, conv_id, model, metadata, created_at, started_at)
                VALUES (:id, :kind, :title, :status, :parent_id, :conv_id, :model, :metadata::jsonb, :now,
                        CASE WHEN :status = 'running' THEN :now ELSE NULL END)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    status = EXCLUDED.status,
                    parent_id = COALESCE(EXCLUDED.parent_id, work_items.parent_id),
                    model = COALESCE(EXCLUDED.model, work_items.model),
                    metadata = COALESCE(EXCLUDED.metadata, work_items.metadata),
                    started_at = CASE WHEN EXCLUDED.status = 'running' AND work_items.started_at IS NULL
                                      THEN :now ELSE work_items.started_at END,
                    completed_at = CASE WHEN EXCLUDED.status IN ('completed', 'failed', 'cancelled')
                                        THEN :now ELSE work_items.completed_at END
            """), {
                "id": item_id, "kind": kind, "title": title, "status": status,
                "parent_id": parent_id, "conv_id": conv_id, "model": model,
                "metadata": meta_json, "now": now,
            })
            await session.commit()
        return {"id": item_id, "kind": kind, "status": status}

    async def update_work_item_status(
        self, item_id: str, status: str, metadata_patch: dict = None
    ) -> None:
        """Update just the status (and optionally metadata) of a work item."""
        now = datetime.now(timezone.utc)
        if metadata_patch:
            meta_json = json.dumps(metadata_patch)
            sql = """
                UPDATE work_items SET
                    status = :status,
                    started_at = CASE WHEN :status = 'running' AND started_at IS NULL THEN :now ELSE started_at END,
                    completed_at = CASE WHEN :status IN ('completed', 'failed', 'cancelled') THEN :now ELSE completed_at END,
                    metadata = COALESCE(metadata, '{}'::jsonb) || :patch::jsonb
                WHERE id = :id
            """
            params = {"id": item_id, "status": status, "now": now, "patch": meta_json}
        else:
            sql = """
                UPDATE work_items SET
                    status = :status,
                    started_at = CASE WHEN :status = 'running' AND started_at IS NULL THEN :now ELSE started_at END,
                    completed_at = CASE WHEN :status IN ('completed', 'failed', 'cancelled') THEN :now ELSE completed_at END
                WHERE id = :id
            """
            params = {"id": item_id, "status": status, "now": now}
        async with self._session_factory() as session:
            await session.execute(text(sql), params)
            await session.commit()

    async def list_work_items(
        self, status: str = None, kind: str = None, parent_id: str = None, limit: int = 100
    ) -> list[dict]:
        """List work items with optional filters."""
        conditions = []
        params: dict[str, Any] = {"limit": limit}
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if kind:
            conditions.append("kind = :kind")
            params["kind"] = kind
        if parent_id:
            conditions.append("parent_id = :parent_id")
            params["parent_id"] = parent_id
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        async with self._session_factory() as session:
            result = await session.execute(
                text(f"SELECT * FROM work_items{where} ORDER BY created_at DESC LIMIT :limit"),
                params,
            )
            rows = result.mappings().all()
            items = []
            for r in rows:
                d = dict(r)
                # Convert datetimes to ISO strings
                for key in ("created_at", "started_at", "completed_at"):
                    if d.get(key) and hasattr(d[key], "isoformat"):
                        d[key] = d[key].isoformat()
                items.append(d)
            return items

    async def cleanup_old_work_items(self, days: int = 7) -> int:
        """Delete work items older than N days that are in terminal state."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    DELETE FROM work_items
                    WHERE status IN ('completed', 'failed', 'cancelled')
                      AND created_at < NOW() - INTERVAL ':days days'
                """),
                {"days": days},
            )
            await session.commit()
            return result.rowcount

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

    # ── Search ─────────────────────────────────────────────────────

    async def search_messages(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across all messages using PostgreSQL tsvector.

        Returns messages ranked by relevance with conversation context.
        """
        if not query or not query.strip():
            return []

        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT
                        m.id,
                        m.conversation_id,
                        m.role,
                        m.content,
                        m.model_used,
                        m.created_at,
                        c.title as conversation_title,
                        ts_rank(m.search_vector, plainto_tsquery('english', :query)) as rank,
                        ts_headline('english', m.content, plainto_tsquery('english', :query),
                            'StartSel=**, StopSel=**, MaxWords=40, MinWords=20') as headline
                    FROM messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE m.search_vector @@ plainto_tsquery('english', :query)
                    ORDER BY rank DESC
                    LIMIT :limit
                """),
                {"query": query.strip(), "limit": limit},
            )
            rows = result.fetchall()
            return [
                {
                    "id": row[0],
                    "conversation_id": row[1],
                    "role": row[2],
                    "content": row[3][:500] if row[3] else "",
                    "model_used": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                    "conversation_title": row[6],
                    "rank": round(float(row[7]), 4),
                    "headline": row[8],
                }
                for row in rows
            ]

    # ── Telegram Pairing ─────────────────────────────────────────

    async def create_pairing_code(self, code: str, expires_at: datetime) -> dict:
        async with self._session_factory() as session:
            session.add(PairingCode(code=code, expires_at=expires_at))
            await session.commit()
        return {"code": code, "expires_at": expires_at.isoformat()}

    async def validate_pairing_code(self, code: str) -> Optional[dict]:
        """Check if a code exists, is not expired, and not yet used."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            result = await session.execute(
                select(PairingCode).where(
                    PairingCode.code == code,
                    PairingCode.used == False,
                    PairingCode.expires_at > now,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {"code": row.code, "expires_at": _dt_to_iso(row.expires_at)}

    async def consume_pairing_code(self, code: str, telegram_user_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(PairingCode)
                .where(PairingCode.code == code)
                .values(used=True, used_by_telegram_id=telegram_user_id)
            )
            await session.commit()

    async def add_telegram_pairing(
        self, telegram_user_id: str, username: str = None, first_name: str = None,
    ) -> dict:
        """Upsert a Telegram pairing (reactivates if previously revoked)."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            result = await session.execute(
                select(TelegramPairing).where(TelegramPairing.telegram_user_id == telegram_user_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.telegram_username = username
                existing.telegram_first_name = first_name
                existing.active = True
                existing.paired_at = now
                existing.last_active = now
            else:
                session.add(TelegramPairing(
                    telegram_user_id=telegram_user_id,
                    telegram_username=username,
                    telegram_first_name=first_name,
                    paired_at=now,
                    last_active=now,
                    active=True,
                ))
            await session.commit()
        return {"telegram_user_id": telegram_user_id, "username": username, "active": True}

    async def get_telegram_pairing(self, telegram_user_id: str) -> Optional[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TelegramPairing).where(
                    TelegramPairing.telegram_user_id == telegram_user_id,
                    TelegramPairing.active == True,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.id,
                "telegram_user_id": row.telegram_user_id,
                "telegram_username": row.telegram_username,
                "telegram_first_name": row.telegram_first_name,
                "conversation_id": row.conversation_id,
                "paired_at": _dt_to_iso(row.paired_at),
                "last_active": _dt_to_iso(row.last_active),
                "active": row.active,
            }

    async def list_telegram_pairings(self) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TelegramPairing).order_by(TelegramPairing.paired_at.desc())
            )
            rows = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "telegram_user_id": r.telegram_user_id,
                    "telegram_username": r.telegram_username,
                    "telegram_first_name": r.telegram_first_name,
                    "conversation_id": r.conversation_id,
                    "paired_at": _dt_to_iso(r.paired_at),
                    "last_active": _dt_to_iso(r.last_active),
                    "active": r.active,
                }
                for r in rows
            ]

    async def revoke_telegram_pairing(self, telegram_user_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(TelegramPairing)
                .where(TelegramPairing.telegram_user_id == telegram_user_id)
                .values(active=False)
            )
            await session.commit()

    async def update_telegram_conversation(self, telegram_user_id: str, conv_id: str) -> None:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            await session.execute(
                update(TelegramPairing)
                .where(TelegramPairing.telegram_user_id == telegram_user_id)
                .values(conversation_id=conv_id, last_active=now)
            )
            await session.commit()

    async def get_telegram_conversation(self, telegram_user_id: str) -> Optional[str]:
        """Get the sticky conversation ID for a Telegram user."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(TelegramPairing.conversation_id).where(
                    TelegramPairing.telegram_user_id == telegram_user_id,
                    TelegramPairing.active == True,
                )
            )
            row = result.scalar_one_or_none()
            return row if row else None

    async def cleanup_expired_codes(self) -> int:
        """Delete pairing codes older than 1 hour."""
        cutoff = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            result = await session.execute(
                delete(PairingCode).where(PairingCode.expires_at < cutoff)
            )
            await session.commit()
            return result.rowcount

    # ── Utility ───────────────────────────────────────────────────

    async def execute_query(self, query: str) -> Any:
        """Execute a raw SQL query and return all rows. Used by health checks."""
        async with self._session_factory() as session:
            result = await session.execute(text(query))
            return result.fetchall()
