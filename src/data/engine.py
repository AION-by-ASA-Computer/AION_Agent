from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

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
    if u.startswith("sqlite"):
        Path(u.split("///")[-1]).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_async_engine(u, echo=os.getenv("AION_SQL_ECHO", "0") == "1")
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info("SQLAlchemy async engine ready: %s", u.split("@")[-1] if "@" in u else u)
    return _engine


def get_engine() -> AsyncEngine:
    return init_engine()


def get_async_session_maker() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory
