from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger("aion.data.engine")

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _default_db_url() -> str:
    return os.getenv("AION_DB_URL", "sqlite+aiosqlite:///data/aion.db")


def init_engine(url: str | None = None) -> AsyncEngine:
    global _engine, _session_factory
    u = url or _default_db_url()
    if _engine is not None:
        return _engine

    is_sqlite = u.startswith("sqlite")
    if is_sqlite:
        Path(u.split("///")[-1]).parent.mkdir(parents=True, exist_ok=True)

        # SQLite connection timeout in seconds (default is 5.0 in sqlite3)
        connect_args = {"timeout": 30.0}
        _engine = create_async_engine(
            u,
            echo=os.getenv("AION_SQL_ECHO", "0") == "1",
            connect_args=connect_args,
        )

        # Enforce WAL mode and NORMAL synchronization on connect for better concurrency
        from sqlalchemy import event

        @event.listens_for(_engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            except Exception as e:
                logger.warning("Failed to configure SQLite pragmas: %s", e)
            finally:
                cursor.close()
    else:
        _engine = create_async_engine(u, echo=os.getenv("AION_SQL_ECHO", "0") == "1")

    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info(
        "SQLAlchemy async engine ready: %s", u.split("@")[-1] if "@" in u else u
    )
    return _engine


def get_engine() -> AsyncEngine:
    return init_engine()


def get_async_session_maker() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory
