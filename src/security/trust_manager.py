import os
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, delete
from ..data.engine import get_async_session_maker
from ..data.models import TrustedPath

logger = logging.getLogger("aion.security.trust")

class TrustManager:
    """Manages the database of trusted files and paths using unified SQLAlchemy engine."""
    
    def __init__(self):
        self.session_maker = get_async_session_maker()

    async def is_trusted(self, path: str) -> bool:
        """Checks if a specific path is in the trustlist."""
        async with self.session_maker() as session:
            q = select(TrustedPath).where(TrustedPath.path == path)
            result = await session.execute(q)
            return result.scalars().first() is not None

    async def add_trust(self, path: str):
        """Adds a path to the trustlist."""
        async with self.session_maker() as session:
            q = select(TrustedPath).where(TrustedPath.path == path)
            existing = (await session.execute(q)).scalars().first()
            if not existing:
                new_trust = TrustedPath(path=path)
                session.add(new_trust)
                await session.commit()
                logger.info(f"✅ Path marked as SAFE: {path}")

    async def remove_trust(self, path: str):
        """Removes a path from the trustlist."""
        async with self.session_maker() as session:
            q = delete(TrustedPath).where(TrustedPath.path == path)
            await session.execute(q)
            await session.commit()
            logger.info(f"🚫 Trust removed from path: {path}")

# Singleton instance
trust_manager = TrustManager()
