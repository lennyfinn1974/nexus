#!/usr/bin/env python3
"""One-time migration: SQLite -> PostgreSQL.

Reads all rows from the legacy SQLite database and bulk-inserts them
into PostgreSQL via SQLAlchemy ORM.  Handles type conversions:
  - ISO datetime strings  -> datetime objects
  - INTEGER 0/1           -> Boolean
  - TEXT JSON              -> parsed dicts/lists (for JSONB columns)
  - Resets auto-increment sequences after insert

Usage:
    DATABASE_URL=postgresql+asyncpg://... \
    python -m scripts.migrate_sqlite_to_pg [--sqlite-path data/nexus.db] [--batch-size 500]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from sqlalchemy import text

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.engine import dispose_engine, get_session_factory, init_engine
from storage.models import (
    ActiveSession,
    AuthAudit,
    Base,
    BlockedIP,
    Conversation,
    InteractionPatternModel,
    KnowledgeAssociation,
    Message,
    ProjectContextModel,
    SessionContextModel,
    Setting,
    SettingsAudit,
    Skill,
    Task,
    User,
    UserGoal,
    UserPreferenceModel,
    Whitelist,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate")

# ── Type conversion helpers ────────────────────────────────────

def _parse_dt(val) -> datetime | None:
    """Parse ISO datetime string to a tz-aware datetime object."""
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(val))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_bool(val) -> bool:
    """SQLite stores booleans as 0/1 integers."""
    if val is None:
        return False
    return bool(int(val))


def _parse_json(val):
    """Parse TEXT JSON to a Python object (for JSONB columns)."""
    if val is None or val == "":
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


# ── Table migration specs ──────────────────────────────────────
# (sqlite_table, orm_class, column_converters)
# column_converters: {column_name: converter_function}

MIGRATION_SPECS = [
    ("conversations", Conversation, {
        "created_at": _parse_dt,
        "updated_at": _parse_dt,
    }),
    ("messages", Message, {
        "created_at": _parse_dt,
    }),
    ("skills", Skill, {
        "created_at": _parse_dt,
        "updated_at": _parse_dt,
        "last_used_at": _parse_dt,
    }),
    ("tasks", Task, {
        "created_at": _parse_dt,
        "started_at": _parse_dt,
        "completed_at": _parse_dt,
    }),
    ("settings", Setting, {
        "encrypted": _parse_bool,
        "updated_at": _parse_dt,
    }),
    ("settings_audit", SettingsAudit, {
        "changed_at": _parse_dt,
    }),
    ("user_preferences", UserPreferenceModel, {
        "first_learned": _parse_dt,
        "last_updated": _parse_dt,
    }),
    ("project_contexts", ProjectContextModel, {
        "tags": _parse_json,
        "files_involved": _parse_json,
        "created_at": _parse_dt,
        "last_worked": _parse_dt,
        "metadata": _parse_json,
    }),
    ("interaction_patterns", InteractionPatternModel, {
        "triggers": _parse_json,
        "first_seen": _parse_dt,
        "last_seen": _parse_dt,
        "metadata": _parse_json,
    }),
    ("session_contexts", SessionContextModel, {
        "start_time": _parse_dt,
        "end_time": _parse_dt,
        "projects_worked": _parse_json,
        "tools_used": _parse_json,
        "skills_used": _parse_json,
        "topics_discussed": _parse_json,
        "key_achievements": _parse_json,
        "challenges_faced": _parse_json,
    }),
    ("knowledge_associations", KnowledgeAssociation, {
        "created_at": _parse_dt,
    }),
    ("user_goals", UserGoal, {
        "target_date": _parse_dt,
        "created_at": _parse_dt,
        "last_updated": _parse_dt,
        "milestones": _parse_json,
        "success_criteria": _parse_json,
        "related_projects": _parse_json,
    }),
    ("users", User, {
        "active": _parse_bool,
        "created_at": _parse_dt,
        "last_login": _parse_dt,
    }),
    ("whitelist", Whitelist, {
        "added_at": _parse_dt,
    }),
    ("sessions", ActiveSession, {
        "created_at": _parse_dt,
        "expires_at": _parse_dt,
        "revoked": _parse_bool,
    }),
    ("blocked_ips", BlockedIP, {
        "blocked_at": _parse_dt,
    }),
    ("auth_audit", AuthAudit, {
        "success": _parse_bool,
        "created_at": _parse_dt,
    }),
]

# Tables with auto-increment sequences that need resetting
_SEQUENCE_TABLES = [
    ("messages", "messages_id_seq"),
    ("settings_audit", "settings_audit_id_seq"),
    ("session_contexts", "session_contexts_id_seq"),
    ("knowledge_associations", "knowledge_associations_id_seq"),
    ("whitelist", "whitelist_id_seq"),
    ("blocked_ips", "blocked_ips_id_seq"),
    ("auth_audit", "auth_audit_id_seq"),
]


async def read_sqlite_table(db_path: str, table: str) -> list[dict]:
    """Read all rows from a SQLite table. Returns list of dicts."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        try:
            cursor = await db.execute(f"SELECT * FROM {table}")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"Table '{table}' not found or empty in SQLite: {e}")
            return []


def convert_row(row: dict, converters: dict, orm_class) -> dict:
    """Apply type converters and handle column name mapping."""
    result = {}
    for key, val in row.items():
        # Handle the metadata -> metadata_ mapping for ProjectContextModel and InteractionPatternModel
        attr_name = key
        if key == "metadata" and hasattr(orm_class, "metadata_"):
            attr_name = "metadata_"

        if key in converters:
            result[attr_name] = converters[key](val)
        else:
            result[attr_name] = val
    return result


async def migrate_table(
    session_factory,
    sqlite_path: str,
    table_name: str,
    orm_class,
    converters: dict,
    batch_size: int,
) -> int:
    """Migrate one table from SQLite to PostgreSQL. Returns row count."""
    rows = await read_sqlite_table(sqlite_path, table_name)
    if not rows:
        logger.info(f"  {table_name}: 0 rows (skipped)")
        return 0

    converted = [convert_row(r, converters, orm_class) for r in rows]

    # Bulk insert in batches
    total = 0
    for i in range(0, len(converted), batch_size):
        batch = converted[i : i + batch_size]
        async with session_factory() as session:
            for row_data in batch:
                obj = orm_class(**row_data)
                session.add(obj)
            await session.commit()
        total += len(batch)

    logger.info(f"  {table_name}: {total} rows migrated")
    return total


async def reset_sequences(session_factory):
    """Reset auto-increment sequences to max(id) + 1."""
    async with session_factory() as session:
        for table, seq in _SEQUENCE_TABLES:
            try:
                result = await session.execute(
                    text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
                )
                max_id = result.scalar_one()
                if max_id > 0:
                    await session.execute(
                        text(f"SELECT setval('{seq}', {max_id})")
                    )
                    logger.info(f"  Sequence {seq} reset to {max_id}")
            except Exception as e:
                logger.warning(f"  Could not reset sequence {seq}: {e}")
        await session.commit()


async def create_tables(engine):
    """Create all tables in PostgreSQL (if not using Alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Tables created in PostgreSQL")


async def main():
    parser = argparse.ArgumentParser(description="Migrate Nexus SQLite to PostgreSQL")
    parser.add_argument(
        "--sqlite-path",
        default=os.getenv("SQLITE_PATH", str(Path(__file__).resolve().parents[2] / "data" / "nexus.db")),
        help="Path to the SQLite database file",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of rows per batch insert (default: 500)",
    )
    parser.add_argument(
        "--create-tables",
        action="store_true",
        help="Create tables in PostgreSQL before migrating (alternative to Alembic)",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL environment variable is required")
        sys.exit(1)

    if not os.path.exists(args.sqlite_path):
        logger.error(f"SQLite database not found: {args.sqlite_path}")
        sys.exit(1)

    logger.info(f"Source: {args.sqlite_path}")
    logger.info(f"Target: {database_url.split('@')[1] if '@' in database_url else database_url}")

    engine = init_engine(database_url)

    if args.create_tables:
        await create_tables(engine)

    session_factory = get_session_factory()

    logger.info("Starting migration...")
    total_rows = 0

    for table_name, orm_class, converters in MIGRATION_SPECS:
        count = await migrate_table(
            session_factory, args.sqlite_path, table_name, orm_class, converters, args.batch_size
        )
        total_rows += count

    logger.info("Resetting auto-increment sequences...")
    await reset_sequences(session_factory)

    # Validate: compare row counts
    logger.info("Validating migration...")
    errors = 0
    for table_name, orm_class, _ in MIGRATION_SPECS:
        sqlite_rows = await read_sqlite_table(args.sqlite_path, table_name)
        async with session_factory() as session:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            pg_count = result.scalar_one()
        sqlite_count = len(sqlite_rows)
        if sqlite_count != pg_count:
            logger.error(f"  MISMATCH {table_name}: SQLite={sqlite_count}, PG={pg_count}")
            errors += 1
        else:
            logger.info(f"  OK {table_name}: {pg_count} rows")

    await dispose_engine()

    if errors:
        logger.error(f"Migration completed with {errors} validation errors!")
        sys.exit(1)
    else:
        logger.info(f"Migration complete! {total_rows} total rows migrated successfully.")


if __name__ == "__main__":
    asyncio.run(main())
