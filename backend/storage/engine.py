"""Async SQLAlchemy engine factory and connection pooling for PostgreSQL (Supabase)."""

import logging
import os
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from storage.models import Base

logger = logging.getLogger("nexus.storage")

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def init_engine(
    database_url: str,
    *,
    pool_size: int = 10,
    max_overflow: int = 20,
    echo: bool = False,
) -> AsyncEngine:
    """Create the async engine with Supabase-appropriate pooling.

    Call once at application startup.
    """
    global _engine, _session_factory

    connect_args: dict = {}

    # Detect ssl=disable in the URL (common for local PostgreSQL).
    # asyncpg can't handle it as a query param, so strip it and use connect_args.
    ssl_disabled_in_url = "ssl=disable" in database_url
    if ssl_disabled_in_url:
        database_url = database_url.replace("?ssl=disable", "").replace("&ssl=disable", "")

    # Only add SSL and server_settings for real PostgreSQL (not SQLite)
    if database_url.startswith("postgresql"):
        connect_args = {
            "server_settings": {
                "application_name": "nexus",
                "statement_timeout": "30000",
            },
        }

        # Default to SSL require for cloud/production PostgreSQL.
        # Disable for local development (ssl=disable in URL, DATABASE_SSL=false, or localhost).
        ssl_env_disabled = os.getenv("DATABASE_SSL", "true").lower() in ("0", "false", "no")
        is_localhost = "localhost" in database_url or "127.0.0.1" in database_url

        if ssl_disabled_in_url or ssl_env_disabled or is_localhost:
            connect_args["ssl"] = False
        else:
            connect_args["ssl"] = "require"

    _engine = create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_timeout=30,
        echo=echo,
        connect_args=connect_args,
    )

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    logger.info(
        "Database engine created (pool_size=%d, max_overflow=%d)",
        pool_size,
        max_overflow,
    )
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialized — call init_engine() first")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Session factory not initialized — call init_engine() first")
    return _session_factory


async def create_all_tables() -> None:
    """Create all SQLAlchemy ORM tables if they don't exist.

    Safe to call on existing databases — uses checkfirst=True (the default),
    so it only creates tables that are missing. Call once at application startup
    after init_engine(), before any code tries to query tables.
    """
    if _engine is None:
        raise RuntimeError("Database engine not initialized — call init_engine() first")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified/created (%d tables)", len(Base.metadata.tables))


async def dispose_engine() -> None:
    """Gracefully close all pooled connections. Call during shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed")
        _engine = None
        _session_factory = None
