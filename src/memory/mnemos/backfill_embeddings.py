"""Backfill missing note embeddings for hybrid recall."""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from src.data.engine import get_async_session_maker
from src.data.models import LtmNote
from src.memory.mnemos.embedding import embedding_to_bytes, embeddings_configured, get_embedding
from src.memory.mnemos.types import MemoryScope

logger = logging.getLogger("aion.memory.mnemos.backfill_embeddings")


async def backfill_embeddings(
    *,
    tenant_id: str = "default",
    batch_size: int = 50,
    limit: int | None = None,
) -> int:
    updated = 0
    async with get_async_session_maker()() as session:
        q = (
            select(LtmNote)
            .where(
                LtmNote.tenant_id == tenant_id,
                LtmNote.status == "active",
                LtmNote.embedding.is_(None),
            )
            .order_by(LtmNote.id)
        )
        if limit is not None:
            q = q.limit(limit)
        notes = list((await session.execute(q)).scalars().all())

    for note in notes:
        if not embeddings_configured():
            break
        try:
            vec = await asyncio.to_thread(get_embedding, note.content)
        except Exception as exc:
            logger.warning("Backfill embedding failed for note %s: %s", note.id, exc)
            continue
        emb = embedding_to_bytes(vec)
        if emb is None:
            continue
        async with get_async_session_maker()() as session:
            row = await session.get(LtmNote, note.id)
            if not row or row.embedding is not None:
                continue
            row.embedding = emb
            await session.commit()
            updated += 1
            if updated % batch_size == 0:
                logger.info("Backfilled %d embeddings", updated)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Mnemos note embeddings")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    n = asyncio.run(backfill_embeddings(tenant_id=args.tenant, limit=args.limit))
    print(f"backfilled={n}")


if __name__ == "__main__":
    main()
