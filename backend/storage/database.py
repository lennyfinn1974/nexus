"""PostgreSQL storage for conversations, skills, and tasks.

Uses SQLAlchemy async sessions (one session per method call).
Public API is identical to the original aiosqlite version — all methods
return plain dicts with ISO-formatted datetime strings.

Multi-tenant: Most methods accept an optional `org_id` parameter
(defaults to "default" for single-tenant backward compatibility).
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

DEFAULT_ORG = "default"


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

    async def create_conversation(self, conv_id: str, title: str = "New Conversation", org_id: str = DEFAULT_ORG) -> dict:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            conv = Conversation(id=conv_id, title=title, org_id=org_id, created_at=now, updated_at=now)
            session.add(conv)
            await session.commit()
        return {"id": conv_id, "title": title, "created_at": now.isoformat()}

    async def list_conversations(self, limit: int = 50, org_id: str = DEFAULT_ORG) -> list[dict]:
        async with self._session_factory() as session:
            stmt = select(Conversation).where(Conversation.org_id == org_id).order_by(Conversation.updated_at.desc()).limit(limit)
            result = await session.execute(stmt)
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
                    org_id VARCHAR(64) NOT NULL DEFAULT 'default',
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
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_work_items_org ON work_items (org_id, status)"
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
        org_id: str = DEFAULT_ORG,
    ) -> dict:
        """Insert or update a work item.

        Uses separate named params for every column to avoid asyncpg type
        ambiguity:
          - :created_ts / :started_ts / :completed_ts for timestamptz columns
          - :status / :status_chk for varchar columns
          - CAST(:metadata AS jsonb) instead of ::jsonb
        """
        now = datetime.now(timezone.utc)
        meta_json = json.dumps(metadata) if metadata else None
        started_ts = now if status == "running" else None
        async with self._session_factory() as session:
            await session.execute(text("""
                INSERT INTO work_items (id, org_id, kind, title, status, parent_id, conv_id, model, metadata, created_at, started_at)
                VALUES (:id, :org_id, :kind, :title, :status, :parent_id, :conv_id, :model,
                        CAST(:metadata AS jsonb), :created_ts, :started_ts)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    status = EXCLUDED.status,
                    parent_id = COALESCE(EXCLUDED.parent_id, work_items.parent_id),
                    model = COALESCE(EXCLUDED.model, work_items.model),
                    metadata = COALESCE(EXCLUDED.metadata, work_items.metadata),
                    started_at = CASE WHEN EXCLUDED.status = 'running' AND work_items.started_at IS NULL
                                      THEN :upsert_now ELSE work_items.started_at END,
                    completed_at = CASE WHEN EXCLUDED.status IN ('completed', 'failed', 'cancelled')
                                        THEN :upsert_now ELSE work_items.completed_at END
            """), {
                "id": item_id, "org_id": org_id, "kind": kind, "title": title, "status": status,
                "parent_id": parent_id, "conv_id": conv_id,
                "model": model, "metadata": meta_json,
                "created_ts": now, "started_ts": started_ts, "upsert_now": now,
            })
            await session.commit()
        return {"id": item_id, "kind": kind, "status": status}

    async def update_work_item_status(
        self, item_id: str, status: str, metadata_patch: dict = None
    ) -> None:
        """Update just the status (and optionally metadata) of a work item.

        Pre-computes started_at/completed_at in Python to avoid asyncpg type
        ambiguity from mixing timestamptz and varchar in CASE expressions.
        """
        now = datetime.now(timezone.utc)
        started_ts = now if status == "running" else None
        completed_ts = now if status in ("completed", "failed", "cancelled") else None

        if metadata_patch:
            meta_json = json.dumps(metadata_patch)
            sql = """
                UPDATE work_items SET
                    status = :status,
                    started_at = COALESCE(started_at, :started_ts),
                    completed_at = COALESCE(:completed_ts, completed_at),
                    metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:patch AS jsonb)
                WHERE id = :id
            """
            params = {"id": item_id, "status": status, "started_ts": started_ts, "completed_ts": completed_ts, "patch": meta_json}
        else:
            sql = """
                UPDATE work_items SET
                    status = :status,
                    started_at = COALESCE(started_at, :started_ts),
                    completed_at = COALESCE(:completed_ts, completed_at)
                WHERE id = :id
            """
            params = {"id": item_id, "status": status, "started_ts": started_ts, "completed_ts": completed_ts}
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

    async def clear_all_work_items(self) -> int:
        """Delete ALL work items from the database."""
        async with self._session_factory() as session:
            result = await session.execute(text("DELETE FROM work_items"))
            await session.commit()
            return result.rowcount

    async def cleanup_old_work_items(self, days: int = 7) -> int:
        """Delete work items older than N days that are in terminal state."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    DELETE FROM work_items
                    WHERE status IN ('completed', 'failed', 'cancelled')
                      AND created_at < NOW() - MAKE_INTERVAL(days => :days)
                """),
                {"days": days},
            )
            await session.commit()
            return result.rowcount

    async def fix_stale_work_items(self) -> int:
        """Mark stale 'pending' and 'running' work items as completed/failed.

        Tasks stuck in pending for >15 minutes are likely completed via Redis
        Stream but never synced back to PostgreSQL. Other work items stuck
        for >1 hour are likely orphaned from server restarts.
        """
        total = 0
        async with self._session_factory() as session:
            # Tasks: shorter threshold (15 min) — they run fast via Redis Streams
            result = await session.execute(
                text("""
                    UPDATE work_items
                    SET status = 'completed',
                        completed_at = NOW(),
                        metadata = COALESCE(metadata, '{}'::jsonb) || '{"auto_fixed": "stale_sync"}'::jsonb
                    WHERE status = 'pending'
                      AND kind = 'task'
                      AND created_at < NOW() - INTERVAL '15 minutes'
                """),
            )
            total += result.rowcount

            # Running tasks that have been running for >30 min — likely failed
            result = await session.execute(
                text("""
                    UPDATE work_items
                    SET status = 'failed',
                        completed_at = NOW(),
                        metadata = COALESCE(metadata, '{}'::jsonb) || '{"auto_failed": "stale_cleanup"}'::jsonb
                    WHERE status = 'running'
                      AND kind = 'task'
                      AND created_at < NOW() - INTERVAL '30 minutes'
                """),
            )
            total += result.rowcount

            # Other work types (agents, orchestrations): 1 hour threshold
            result = await session.execute(
                text("""
                    UPDATE work_items
                    SET status = 'failed',
                        completed_at = NOW(),
                        metadata = COALESCE(metadata, '{}'::jsonb) || '{"auto_failed": "stale_cleanup"}'::jsonb
                    WHERE status IN ('pending', 'running')
                      AND kind != 'task'
                      AND created_at < NOW() - INTERVAL '1 hour'
                """),
            )
            total += result.rowcount

            await session.commit()
            return total

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

    # ── Channel Identities ───────────────────────────────────────────

    async def ensure_channel_identities_table(self) -> None:
        """Create the channel_identities table if it doesn't exist.

        Links external channel user IDs (Telegram, WhatsApp, SMS, etc.)
        to a Nexus user identity for cross-channel conversation continuity.
        """
        async with self._session_factory() as session:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS channel_identities (
                    id SERIAL PRIMARY KEY,
                    nexus_user_id VARCHAR(128) NOT NULL,
                    channel VARCHAR(20) NOT NULL,
                    channel_user_id VARCHAR(128) NOT NULL,
                    display_name VARCHAR(200),
                    conversation_id VARCHAR(128),
                    org_id VARCHAR(64) NOT NULL DEFAULT 'default',
                    paired_at TIMESTAMPTZ DEFAULT NOW(),
                    last_active TIMESTAMPTZ DEFAULT NOW(),
                    metadata JSONB,
                    UNIQUE(channel, channel_user_id)
                )
            """))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_channel_ident_user "
                "ON channel_identities (nexus_user_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_channel_ident_channel "
                "ON channel_identities (channel, channel_user_id)"
            ))
            await session.commit()
        logger.info("Ensured channel_identities table exists")

    async def upsert_channel_identity(
        self,
        nexus_user_id: str,
        channel: str,
        channel_user_id: str,
        display_name: str = "",
        org_id: str = DEFAULT_ORG,
    ) -> dict:
        """Create or update a channel identity link."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            await session.execute(text("""
                INSERT INTO channel_identities
                    (nexus_user_id, channel, channel_user_id, display_name, org_id, paired_at, last_active)
                VALUES (:nexus_user_id, :channel, :channel_user_id, :display_name, :org_id, :now, :now)
                ON CONFLICT (channel, channel_user_id) DO UPDATE SET
                    nexus_user_id = EXCLUDED.nexus_user_id,
                    display_name = COALESCE(EXCLUDED.display_name, channel_identities.display_name),
                    last_active = :now
            """), {
                "nexus_user_id": nexus_user_id,
                "channel": channel,
                "channel_user_id": channel_user_id,
                "display_name": display_name or None,
                "org_id": org_id,
                "now": now,
            })
            await session.commit()
        return {
            "nexus_user_id": nexus_user_id,
            "channel": channel,
            "channel_user_id": channel_user_id,
        }

    async def get_channel_identity(
        self, channel: str, channel_user_id: str
    ) -> Optional[dict]:
        """Look up a channel identity by channel type and channel-specific user ID."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                SELECT nexus_user_id, channel, channel_user_id, display_name,
                       conversation_id, org_id, paired_at, last_active
                FROM channel_identities
                WHERE channel = :channel AND channel_user_id = :channel_user_id
            """), {"channel": channel, "channel_user_id": channel_user_id})
            row = result.mappings().first()
            return dict(row) if row else None

    async def get_user_channel_identities(self, nexus_user_id: str) -> list[dict]:
        """Get all channel identities linked to a Nexus user."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                SELECT nexus_user_id, channel, channel_user_id, display_name,
                       conversation_id, org_id, paired_at, last_active
                FROM channel_identities
                WHERE nexus_user_id = :nexus_user_id
                ORDER BY last_active DESC
            """), {"nexus_user_id": nexus_user_id})
            return [dict(r) for r in result.mappings().all()]

    async def get_channel_conversation(
        self, channel: str, channel_user_id: str
    ) -> Optional[str]:
        """Get the active conversation ID for a channel user."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                SELECT conversation_id FROM channel_identities
                WHERE channel = :channel AND channel_user_id = :channel_user_id
            """), {"channel": channel, "channel_user_id": channel_user_id})
            row = result.scalar_one_or_none()
            return row if row else None

    async def set_channel_conversation(
        self, channel: str, channel_user_id: str, conv_id: str
    ) -> None:
        """Set the active conversation for a channel user."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            await session.execute(text("""
                UPDATE channel_identities
                SET conversation_id = :conv_id, last_active = :now
                WHERE channel = :channel AND channel_user_id = :channel_user_id
            """), {
                "conv_id": conv_id,
                "channel": channel,
                "channel_user_id": channel_user_id,
                "now": now,
            })
            await session.commit()

    async def remove_channel_identity(
        self, channel: str, channel_user_id: str
    ) -> bool:
        """Remove a channel identity link. Returns True if a row was deleted."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                DELETE FROM channel_identities
                WHERE channel = :channel AND channel_user_id = :channel_user_id
            """), {"channel": channel, "channel_user_id": channel_user_id})
            await session.commit()
            return result.rowcount > 0

    # ── Marketing Tables ─────────────────────────────────────────────

    async def ensure_marketing_tables(self) -> None:
        """Create all marketing tables if they don't exist.

        Tables: brand_profiles, campaigns, content_items, calendar_events,
        marketing_metrics, platform_connections.
        """
        async with self._session_factory() as session:
            # Brand voice profiles
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS brand_profiles (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    tone VARCHAR(50),
                    vocabulary_rules JSONB,
                    examples JSONB,
                    platform_guidelines JSONB,
                    is_default BOOLEAN DEFAULT FALSE,
                    org_id VARCHAR(64) NOT NULL DEFAULT 'default',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))

            # Marketing campaigns
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id VARCHAR(128) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    status VARCHAR(20) DEFAULT 'planning',
                    campaign_type VARCHAR(30),
                    budget_usd DECIMAL(10,2),
                    spent_usd DECIMAL(10,2) DEFAULT 0,
                    start_date DATE,
                    end_date DATE,
                    goals JSONB,
                    strategy TEXT,
                    brand_profile_id INTEGER,
                    org_id VARCHAR(64) NOT NULL DEFAULT 'default',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_campaigns_status "
                "ON campaigns (status)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_campaigns_org "
                "ON campaigns (org_id)"
            ))

            # Content items (posts, emails, ads)
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS content_items (
                    id VARCHAR(128) PRIMARY KEY,
                    campaign_id VARCHAR(128),
                    content_type VARCHAR(30) NOT NULL,
                    platform VARCHAR(30),
                    status VARCHAR(20) DEFAULT 'draft',
                    title VARCHAR(200),
                    body TEXT,
                    media_urls JSONB,
                    scheduled_at TIMESTAMPTZ,
                    published_at TIMESTAMPTZ,
                    external_id VARCHAR(100),
                    metrics JSONB,
                    brand_profile_id INTEGER,
                    created_by VARCHAR(50),
                    approved_by VARCHAR(50),
                    org_id VARCHAR(64) NOT NULL DEFAULT 'default',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_content_items_status "
                "ON content_items (status)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_content_items_campaign "
                "ON content_items (campaign_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_content_items_scheduled "
                "ON content_items (scheduled_at) WHERE status = 'scheduled'"
            ))

            # Calendar events (unified content calendar)
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS calendar_events (
                    id SERIAL PRIMARY KEY,
                    campaign_id VARCHAR(128),
                    content_item_id VARCHAR(128),
                    event_type VARCHAR(20) NOT NULL,
                    title VARCHAR(200),
                    scheduled_at TIMESTAMPTZ NOT NULL,
                    completed_at TIMESTAMPTZ,
                    org_id VARCHAR(64) NOT NULL DEFAULT 'default'
                )
            """))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_calendar_events_date "
                "ON calendar_events (scheduled_at)"
            ))

            # Marketing metrics (time-series)
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS marketing_metrics (
                    id SERIAL PRIMARY KEY,
                    source VARCHAR(30) NOT NULL,
                    metric_name VARCHAR(50) NOT NULL,
                    metric_value DECIMAL(12,4),
                    dimensions JSONB,
                    recorded_at TIMESTAMPTZ NOT NULL,
                    org_id VARCHAR(64) NOT NULL DEFAULT 'default'
                )
            """))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_marketing_metrics_source "
                "ON marketing_metrics (source, metric_name)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_marketing_metrics_time "
                "ON marketing_metrics (recorded_at)"
            ))

            # Platform connections (OAuth tokens for Ayrshare, Mailchimp, etc.)
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS platform_connections (
                    id SERIAL PRIMARY KEY,
                    platform VARCHAR(30) NOT NULL,
                    account_name VARCHAR(100),
                    credentials_encrypted TEXT,
                    scopes JSONB,
                    status VARCHAR(20) DEFAULT 'active',
                    last_refreshed_at TIMESTAMPTZ,
                    org_id VARCHAR(64) NOT NULL DEFAULT 'default',
                    connected_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))

            await session.commit()
        logger.info("Ensured marketing tables exist (6 tables)")

    # ── Brand Profile CRUD ───────────────────────────────────────────

    async def get_brand_profiles(self, org_id: str = DEFAULT_ORG) -> list[dict]:
        """Get all brand voice profiles."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                SELECT id, name, tone, vocabulary_rules, examples,
                       platform_guidelines, is_default, org_id,
                       created_at, updated_at
                FROM brand_profiles
                WHERE org_id = :org_id
                ORDER BY is_default DESC, name
            """), {"org_id": org_id})
            return [dict(r) for r in result.mappings().all()]

    async def create_brand_profile(self, data: dict, org_id: str = DEFAULT_ORG) -> dict:
        """Create a new brand voice profile. Returns the created row."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            # If this is set as default, unset others first
            if data.get("is_default"):
                await session.execute(text("""
                    UPDATE brand_profiles SET is_default = FALSE
                    WHERE org_id = :org_id AND is_default = TRUE
                """), {"org_id": org_id})

            result = await session.execute(text("""
                INSERT INTO brand_profiles
                    (name, tone, vocabulary_rules, examples, platform_guidelines,
                     is_default, org_id, created_at, updated_at)
                VALUES
                    (:name, :tone, :vocabulary_rules, :examples, :platform_guidelines,
                     :is_default, :org_id, :now, :now)
                RETURNING id, name, tone, vocabulary_rules, examples,
                          platform_guidelines, is_default, org_id,
                          created_at, updated_at
            """), {
                "name": data.get("name", ""),
                "tone": data.get("tone", ""),
                "vocabulary_rules": json.dumps(data.get("vocabulary_rules", {})),
                "examples": json.dumps(data.get("examples", [])),
                "platform_guidelines": json.dumps(data.get("platform_guidelines", {})),
                "is_default": data.get("is_default", False),
                "org_id": org_id,
                "now": now,
            })
            row = result.mappings().first()
            await session.commit()
            return dict(row) if row else {}

    async def update_brand_profile(
        self, profile_id: int, data: dict, org_id: str = DEFAULT_ORG
    ) -> Optional[dict]:
        """Update a brand voice profile. Returns the updated row or None."""
        now = datetime.now(timezone.utc)
        # Build SET clause dynamically from provided fields
        allowed = {"name", "tone", "vocabulary_rules", "examples",
                   "platform_guidelines", "is_default"}
        sets = []
        params: dict[str, Any] = {"id": profile_id, "org_id": org_id, "now": now}

        for key in allowed:
            if key in data:
                val = data[key]
                if key in ("vocabulary_rules", "examples", "platform_guidelines"):
                    val = json.dumps(val) if not isinstance(val, str) else val
                sets.append(f"{key} = :{key}")
                params[key] = val

        if not sets:
            return None

        sets.append("updated_at = :now")

        async with self._session_factory() as session:
            # If setting as default, unset others first
            if data.get("is_default"):
                await session.execute(text("""
                    UPDATE brand_profiles SET is_default = FALSE
                    WHERE org_id = :org_id AND is_default = TRUE AND id != :id
                """), {"org_id": org_id, "id": profile_id})

            result = await session.execute(text(f"""
                UPDATE brand_profiles SET {', '.join(sets)}
                WHERE id = :id AND org_id = :org_id
                RETURNING id, name, tone, vocabulary_rules, examples,
                          platform_guidelines, is_default, org_id,
                          created_at, updated_at
            """), params)
            row = result.mappings().first()
            await session.commit()
            return dict(row) if row else None

    async def delete_brand_profile(
        self, profile_id: int, org_id: str = DEFAULT_ORG
    ) -> bool:
        """Delete a brand profile. Returns True if a row was deleted."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                DELETE FROM brand_profiles
                WHERE id = :id AND org_id = :org_id
            """), {"id": profile_id, "org_id": org_id})
            await session.commit()
            return result.rowcount > 0

    # ── Campaign CRUD ────────────────────────────────────────────────

    @staticmethod
    def _parse_date(val) -> Optional[Any]:
        """Convert a date string (YYYY-MM-DD) to a date object, or pass through."""
        if val is None:
            return None
        if isinstance(val, str) and val:
            from datetime import date as date_type
            try:
                return date_type.fromisoformat(val)
            except ValueError:
                return None
        return val

    async def create_campaign(self, data: dict, org_id: str = DEFAULT_ORG) -> dict:
        """Create a new marketing campaign. Returns the created row."""
        import uuid
        now = datetime.now(timezone.utc)
        campaign_id = data.get("id") or str(uuid.uuid4())

        async with self._session_factory() as session:
            result = await session.execute(text("""
                INSERT INTO campaigns
                    (id, name, status, campaign_type, budget_usd, spent_usd,
                     start_date, end_date, goals, strategy,
                     brand_profile_id, org_id, created_at, updated_at)
                VALUES
                    (:id, :name, :status, :campaign_type, :budget_usd, :spent_usd,
                     :start_date, :end_date, :goals, :strategy,
                     :brand_profile_id, :org_id, :now, :now)
                RETURNING *
            """), {
                "id": campaign_id,
                "name": data.get("name", ""),
                "status": data.get("status", "planning"),
                "campaign_type": data.get("campaign_type", ""),
                "budget_usd": data.get("budget_usd"),
                "spent_usd": data.get("spent_usd", 0),
                "start_date": self._parse_date(data.get("start_date")),
                "end_date": self._parse_date(data.get("end_date")),
                "goals": json.dumps(data.get("goals", {})),
                "strategy": data.get("strategy", ""),
                "brand_profile_id": data.get("brand_profile_id"),
                "org_id": org_id,
                "now": now,
            })
            row = result.mappings().first()
            await session.commit()
            return dict(row) if row else {}

    async def get_campaign(
        self, campaign_id: str, org_id: str = DEFAULT_ORG
    ) -> Optional[dict]:
        """Get a single campaign by ID."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                SELECT * FROM campaigns
                WHERE id = :id AND org_id = :org_id
            """), {"id": campaign_id, "org_id": org_id})
            row = result.mappings().first()
            return dict(row) if row else None

    async def update_campaign(
        self, campaign_id: str, data: dict, org_id: str = DEFAULT_ORG
    ) -> Optional[dict]:
        """Update campaign fields. Returns the updated row or None."""
        now = datetime.now(timezone.utc)
        allowed = {"name", "status", "campaign_type", "budget_usd", "spent_usd",
                   "start_date", "end_date", "goals", "strategy", "brand_profile_id"}
        sets = []
        params: dict[str, Any] = {"id": campaign_id, "org_id": org_id, "now": now}

        for key in allowed:
            if key in data:
                val = data[key]
                if key == "goals" and not isinstance(val, str):
                    val = json.dumps(val)
                if key in ("start_date", "end_date"):
                    val = self._parse_date(val)
                sets.append(f"{key} = :{key}")
                params[key] = val

        if not sets:
            return None

        sets.append("updated_at = :now")

        async with self._session_factory() as session:
            result = await session.execute(text(f"""
                UPDATE campaigns SET {', '.join(sets)}
                WHERE id = :id AND org_id = :org_id
                RETURNING *
            """), params)
            row = result.mappings().first()
            await session.commit()
            return dict(row) if row else None

    async def list_campaigns(
        self,
        status: Optional[str] = None,
        campaign_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        org_id: str = DEFAULT_ORG,
    ) -> list[dict]:
        """List campaigns with optional filters."""
        wheres = ["org_id = :org_id"]
        params: dict[str, Any] = {"org_id": org_id, "limit": limit, "offset": offset}

        if status:
            wheres.append("status = :status")
            params["status"] = status
        if campaign_type:
            wheres.append("campaign_type = :campaign_type")
            params["campaign_type"] = campaign_type

        where_clause = " AND ".join(wheres)

        async with self._session_factory() as session:
            result = await session.execute(text(f"""
                SELECT * FROM campaigns
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """), params)
            return [dict(r) for r in result.mappings().all()]

    async def get_campaign_content_counts(
        self, campaign_id: str, org_id: str = DEFAULT_ORG
    ) -> dict:
        """Get content item counts per status for a campaign."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                SELECT status, COUNT(*) as count
                FROM content_items
                WHERE campaign_id = :campaign_id AND org_id = :org_id
                GROUP BY status
            """), {"campaign_id": campaign_id, "org_id": org_id})
            counts = {}
            for row in result.mappings().all():
                counts[row["status"]] = row["count"]
            return counts

    # ── Content Item CRUD ────────────────────────────────────────────

    async def create_content_item(self, data: dict, org_id: str = DEFAULT_ORG) -> dict:
        """Create a new content item in draft state. Returns the created row."""
        import uuid
        now = datetime.now(timezone.utc)
        content_id = data.get("id") or str(uuid.uuid4())

        async with self._session_factory() as session:
            result = await session.execute(text("""
                INSERT INTO content_items
                    (id, campaign_id, content_type, platform, status,
                     title, body, media_urls, brand_profile_id,
                     created_by, org_id, created_at, updated_at)
                VALUES
                    (:id, :campaign_id, :content_type, :platform, 'draft',
                     :title, :body, :media_urls, :brand_profile_id,
                     :created_by, :org_id, :now, :now)
                RETURNING *
            """), {
                "id": content_id,
                "campaign_id": data.get("campaign_id"),
                "content_type": data.get("content_type", "social_post"),
                "platform": data.get("platform", ""),
                "title": data.get("title", ""),
                "body": data.get("body", ""),
                "media_urls": json.dumps(data.get("media_urls", [])),
                "brand_profile_id": data.get("brand_profile_id"),
                "created_by": data.get("created_by", "agent"),
                "org_id": org_id,
                "now": now,
            })
            row = result.mappings().first()
            await session.commit()
            return dict(row) if row else {}

    async def get_content_item(
        self, content_id: str, org_id: str = DEFAULT_ORG
    ) -> Optional[dict]:
        """Get a single content item by ID."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                SELECT * FROM content_items
                WHERE id = :id AND org_id = :org_id
            """), {"id": content_id, "org_id": org_id})
            row = result.mappings().first()
            return dict(row) if row else None

    async def update_content_item(
        self, content_id: str, data: dict, org_id: str = DEFAULT_ORG
    ) -> Optional[dict]:
        """Update content item fields. Returns the updated row or None."""
        now = datetime.now(timezone.utc)
        allowed = {"campaign_id", "content_type", "platform", "status",
                   "title", "body", "media_urls", "scheduled_at", "published_at",
                   "external_id", "metrics", "brand_profile_id",
                   "created_by", "approved_by"}
        sets = []
        params: dict[str, Any] = {"id": content_id, "org_id": org_id, "now": now}

        for key in allowed:
            if key in data:
                val = data[key]
                if key in ("media_urls", "metrics") and not isinstance(val, str):
                    val = json.dumps(val)
                sets.append(f"{key} = :{key}")
                params[key] = val

        if not sets:
            return None

        sets.append("updated_at = :now")

        async with self._session_factory() as session:
            result = await session.execute(text(f"""
                UPDATE content_items SET {', '.join(sets)}
                WHERE id = :id AND org_id = :org_id
                RETURNING *
            """), params)
            row = result.mappings().first()
            await session.commit()
            return dict(row) if row else None

    async def list_content_items(
        self,
        campaign_id: Optional[str] = None,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        org_id: str = DEFAULT_ORG,
    ) -> list[dict]:
        """List content items with optional filters."""
        wheres = ["org_id = :org_id"]
        params: dict[str, Any] = {"org_id": org_id, "limit": limit, "offset": offset}

        if campaign_id:
            wheres.append("campaign_id = :campaign_id")
            params["campaign_id"] = campaign_id
        if status:
            wheres.append("status = :status")
            params["status"] = status
        if platform:
            wheres.append("platform = :platform")
            params["platform"] = platform
        if content_type:
            wheres.append("content_type = :content_type")
            params["content_type"] = content_type

        where_clause = " AND ".join(wheres)

        async with self._session_factory() as session:
            result = await session.execute(text(f"""
                SELECT * FROM content_items
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """), params)
            return [dict(r) for r in result.mappings().all()]

    # ── Calendar Events ──────────────────────────────────────────────

    async def get_calendar_events(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        org_id: str = DEFAULT_ORG,
    ) -> list[dict]:
        """Get calendar events for a date range."""
        wheres = ["org_id = :org_id"]
        params: dict[str, Any] = {"org_id": org_id}

        if start_date:
            wheres.append("scheduled_at >= :start_date")
            params["start_date"] = start_date
        if end_date:
            wheres.append("scheduled_at <= :end_date")
            params["end_date"] = end_date

        where_clause = " AND ".join(wheres)

        async with self._session_factory() as session:
            result = await session.execute(text(f"""
                SELECT id, campaign_id, content_item_id, event_type,
                       title, scheduled_at, completed_at, org_id
                FROM calendar_events
                WHERE {where_clause}
                ORDER BY scheduled_at ASC
            """), params)
            return [dict(r) for r in result.mappings().all()]

    async def create_calendar_event(
        self, data: dict, org_id: str = DEFAULT_ORG
    ) -> dict:
        """Create a calendar event. Returns the created row."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                INSERT INTO calendar_events
                    (campaign_id, content_item_id, event_type, title,
                     scheduled_at, org_id)
                VALUES
                    (:campaign_id, :content_item_id, :event_type, :title,
                     :scheduled_at, :org_id)
                RETURNING *
            """), {
                "campaign_id": data.get("campaign_id"),
                "content_item_id": data.get("content_item_id"),
                "event_type": data.get("event_type", "publish"),
                "title": data.get("title", ""),
                "scheduled_at": self._parse_timestamp(data.get("scheduled_at")),
                "org_id": org_id,
            })
            row = result.mappings().first()
            await session.commit()
            return dict(row) if row else {}

    @staticmethod
    def _parse_timestamp(val) -> Optional[datetime]:
        """Convert a timestamp string to a datetime object, or pass through."""
        if val is None:
            return None
        if isinstance(val, str) and val:
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                return None
        return val

    # ── Marketing Metrics ────────────────────────────────────────────

    async def get_marketing_metrics(
        self,
        source: Optional[str] = None,
        days: int = 30,
        org_id: str = DEFAULT_ORG,
    ) -> dict:
        """Get aggregated marketing metrics.

        Returns grouped metrics by source and metric_name for the given period.
        """
        wheres = ["org_id = :org_id",
                   "recorded_at >= NOW() - INTERVAL ':days days'"]
        params: dict[str, Any] = {"org_id": org_id, "days": days}

        if source:
            wheres.append("source = :source")
            params["source"] = source

        # Use explicit interval construction to avoid parameter interpolation issue
        async with self._session_factory() as session:
            result = await session.execute(text(f"""
                SELECT source, metric_name,
                       SUM(metric_value) as total,
                       AVG(metric_value) as average,
                       COUNT(*) as data_points
                FROM marketing_metrics
                WHERE org_id = :org_id
                  AND recorded_at >= NOW() - make_interval(days => :days)
                  {"AND source = :source" if source else ""}
                GROUP BY source, metric_name
                ORDER BY source, metric_name
            """), params)
            metrics = {}
            for row in result.mappings().all():
                src = row["source"]
                if src not in metrics:
                    metrics[src] = {}
                metrics[src][row["metric_name"]] = {
                    "total": float(row["total"]) if row["total"] else 0,
                    "average": float(row["average"]) if row["average"] else 0,
                    "data_points": row["data_points"],
                }
            return metrics

    async def record_marketing_metric(
        self,
        source: str,
        metric_name: str,
        metric_value: float,
        dimensions: Optional[dict] = None,
        org_id: str = DEFAULT_ORG,
    ) -> dict:
        """Record a marketing metric data point."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            result = await session.execute(text("""
                INSERT INTO marketing_metrics
                    (source, metric_name, metric_value, dimensions,
                     recorded_at, org_id)
                VALUES
                    (:source, :metric_name, :metric_value, :dimensions,
                     :recorded_at, :org_id)
                RETURNING *
            """), {
                "source": source,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "dimensions": json.dumps(dimensions or {}),
                "recorded_at": now,
                "org_id": org_id,
            })
            row = result.mappings().first()
            await session.commit()
            return dict(row) if row else {}

    # ── Platform Connections ─────────────────────────────────────────

    async def get_platform_connections(
        self, org_id: str = DEFAULT_ORG
    ) -> list[dict]:
        """Get all connected marketing platforms."""
        async with self._session_factory() as session:
            result = await session.execute(text("""
                SELECT id, platform, account_name, scopes, status,
                       last_refreshed_at, org_id, connected_at
                FROM platform_connections
                WHERE org_id = :org_id
                ORDER BY connected_at DESC
            """), {"org_id": org_id})
            # Note: credentials_encrypted intentionally excluded from results
            return [dict(r) for r in result.mappings().all()]

    # ── Tenant Migration ────────────────────────────────────────────

    async def ensure_org_id_columns(self) -> None:
        """Add org_id columns to existing tables for multi-tenant support.

        Safe to call repeatedly — uses IF NOT EXISTS / column existence checks.
        All org_id columns default to 'default' for backward compatibility.
        """
        tables_needing_org_id = [
            "conversations", "user_preferences", "project_contexts",
            "interaction_patterns", "session_contexts", "knowledge_associations",
            "kg_entities", "kg_relationships", "user_goals", "archived_memories",
            "settings", "work_items",
        ]
        async with self._session_factory() as session:
            for table in tables_needing_org_id:
                # Check if column exists first
                result = await session.execute(text("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = :table AND column_name = 'org_id'
                """), {"table": table})
                if result.scalar_one_or_none():
                    continue
                # Add the column
                await session.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN org_id VARCHAR(64) NOT NULL DEFAULT 'default'"
                ))
                # Add composite index
                idx_name = f"idx_{table}_org"
                await session.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} (org_id)"
                ))
                logger.info(f"Added org_id column to {table}")
            await session.commit()
        logger.info("Tenant migration complete — all tables have org_id")

    # ── Utility ───────────────────────────────────────────────────

    async def execute_query(self, query: str) -> Any:
        """Execute a raw SQL query and return all rows. Used by health checks."""
        async with self._session_factory() as session:
            result = await session.execute(text(query))
            return result.fetchall()
