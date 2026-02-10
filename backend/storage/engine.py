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
    # Only add SSL and server_settings for real PostgreSQL (not SQLite)
    if database_url.startswith("postgresql"):
        connect_args = {
            "ssl": "require",
            "server_settings": {
                "application_name": "nexus",
                "statement_timeout": "30000",
            },
        }

    # Allow disabling SSL for local development
    if os.getenv("DATABASE_SSL", "true").lower() in ("0", "false", "no"):
        connect_args.pop("ssl", None)

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


async def dispose_engine() -> None:
    """Gracefully close all pooled connections. Call during shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed")
        _engine = None
        _session_factory = None
