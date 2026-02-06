"""Row Level Security (RLS) policy definitions for Supabase PostgreSQL.

Call `apply_rls(engine)` after running Alembic migrations to enable
RLS on all tables and install the initial policy set.

Current policies are permissive (single-user deployment).  When
multi-user auth is added, swap the `USING (true)` clauses for
`USING (auth.uid() = user_id)` or similar.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("nexus.rls")

# Tables that hold application data — permissive policies
_DATA_TABLES = [
    "conversations",
    "messages",
    "skills",
    "tasks",
    "settings",
    "settings_audit",
    "user_preferences",
    "project_contexts",
    "interaction_patterns",
    "session_contexts",
    "knowledge_associations",
    "user_goals",
    "users",
    "whitelist",
    "sessions",
    "auth_audit",
]

# Security tables — app role gets read-only access
_READONLY_TABLES = [
    "blocked_ips",
]


async def apply_rls(engine: AsyncEngine) -> None:
    """Enable RLS and create policies on all Nexus tables.

    Safe to call repeatedly — uses IF NOT EXISTS / OR REPLACE semantics.
    """
    async with engine.begin() as conn:
        for table in _DATA_TABLES + _READONLY_TABLES:
            await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))

        # Permissive policies for data tables (single-user: allow everything)
        for table in _DATA_TABLES:
            policy = f"nexus_allow_all_{table}"
            await conn.execute(text(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies
                        WHERE tablename = '{table}' AND policyname = '{policy}'
                    ) THEN
                        EXECUTE format(
                            'CREATE POLICY {policy} ON {table} FOR ALL USING (true) WITH CHECK (true)'
                        );
                    END IF;
                END
                $$;
            """))

        # Read-only policies for security tables
        for table in _READONLY_TABLES:
            policy_select = f"nexus_readonly_{table}"
            policy_admin = f"nexus_admin_{table}"
            await conn.execute(text(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies
                        WHERE tablename = '{table}' AND policyname = '{policy_select}'
                    ) THEN
                        EXECUTE format(
                            'CREATE POLICY {policy_select} ON {table} FOR SELECT USING (true)'
                        );
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies
                        WHERE tablename = '{table}' AND policyname = '{policy_admin}'
                    ) THEN
                        EXECUTE format(
                            'CREATE POLICY {policy_admin} ON {table} FOR ALL TO postgres USING (true) WITH CHECK (true)'
                        );
                    END IF;
                END
                $$;
            """))

    logger.info("RLS policies applied to %d tables", len(_DATA_TABLES) + len(_READONLY_TABLES))
