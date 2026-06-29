import sqlite3
import asyncio
import os
import sys
import logging
import json
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.getcwd()))

from src.data.engine import get_async_session_maker, init_engine
from src.data.models import Base, CachedQuery, TrustedPath
from sqlalchemy import select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aion.unify_memory")

OLD_DB = "src/prom_agent_memory.db"
OLD_TRUST_DB = "data/security_trust.db"

async def unify():
    # 1. Init
    engine = init_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session_factory = get_async_session_maker()

    # --- PART 1: Query Memory ---
    if os.path.exists(OLD_DB):
        logger.info(f"Unifying {OLD_DB} into aion.db...")
        # ... (same logic as before)
        conn_old = sqlite3.connect(OLD_DB)
        cursor = conn_old.cursor()
        cursor.execute("SELECT user_request, promql_query, is_verified, success_count, namespace, metadata, embedding, created_at FROM cached_queries")
        rows = cursor.fetchall()
        migrated = 0
        async with session_factory() as session:
            for row in rows:
                user_req, promql, is_ver, succ, ns, meta, emb, created = row
                q = select(CachedQuery).where(CachedQuery.user_request == user_req, CachedQuery.namespace == ns)
                if (await session.execute(q)).scalars().first(): continue
                session.add(CachedQuery(
                    user_request=user_req, promql_query=promql, is_verified=int(is_ver),
                    success_count=int(succ), namespace=ns or "default", metadata_json=meta,
                    embedding=emb, created_at=datetime.strptime(created, "%Y-%m-%d %H:%M:%S") if isinstance(created, str) else datetime.now()
                ))
                migrated += 1
            await session.commit()
        logger.info(f"Memory migrated: {migrated}")
        os.remove(OLD_DB)

    # --- PART 2: Security Trust ---
    if os.path.exists(OLD_TRUST_DB):
        logger.info(f"Unifying {OLD_TRUST_DB} into aion.db...")
        conn_trust = sqlite3.connect(OLD_TRUST_DB)
        cursor = conn_trust.cursor()
        cursor.execute("SELECT path, added_at FROM trusted_paths")
        rows = cursor.fetchall()
        migrated = 0
        async with session_factory() as session:
            for row in rows:
                path, added = row
                q = select(TrustedPath).where(TrustedPath.path == path)
                if (await session.execute(q)).scalars().first(): continue
                session.add(TrustedPath(
                    path=path,
                    added_at=datetime.strptime(added, "%Y-%m-%d %H:%M:%S") if isinstance(added, str) else datetime.now()
                ))
                migrated += 1
            await session.commit()
        logger.info(f"Trust records migrated: {migrated}")
        os.remove(OLD_TRUST_DB)

    logger.info("Unification complete.")

if __name__ == "__main__":
    asyncio.run(unify())
