"""Nightly Mnemos maintenance (dream cycle)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy import func, select

from src.data.engine import get_async_session_maker
from src.data.models import LtmNote
from src.memory.llm_extract import complete_json_async
from src.memory.mnemos import store
from src.memory.mnemos.backfill_embeddings import backfill_embeddings
from src.memory.mnemos.compress import compress_all_pending
from src.memory.mnemos.embedding import bytes_to_embedding, cosine_similarity
from src.memory.mnemos.types import MemoryScope

logger = logging.getLogger("aion.memory.mnemos.dream")

_CONTRADICTION_PROMPT = (
    "Two memory notes may contradict. Reply JSON only: "
    '{"keep_id": <int>, "supersede_id": <int>, "reason": "..."} '
    "where keep_id is the current truth and supersede_id is outdated."
)


def _dream_settings() -> tuple[int, int, float]:
    decay_days = max(7, int(os.getenv("AION_MNEMOS_CONFIDENCE_DECAY_DAYS", "90")))
    decay_factor = float(os.getenv("AION_MNEMOS_CONFIDENCE_DECAY_FACTOR", "0.9"))
    min_conf = float(os.getenv("AION_MNEMOS_CONFIDENCE_MIN", "0.2"))
    return decay_days, decay_factor, min_conf


async def decay_stale_confidence(*, tenant_id: str = "default") -> int:
    """Reduce confidence on notes not recalled recently."""
    decay_days, decay_factor, min_conf = _dream_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=decay_days)
    changed = 0
    async with get_async_session_maker()() as session:
        rows = (
            await session.execute(
                select(LtmNote).where(
                    LtmNote.tenant_id == tenant_id,
                    LtmNote.status == "active",
                    LtmNote.confidence > min_conf,
                    (LtmNote.last_recalled_at.is_(None))
                    | (LtmNote.last_recalled_at < cutoff),
                ).limit(200)
            )
        ).scalars().all()
        for note in rows:
            note.confidence = max(min_conf, float(note.confidence or 1.0) * decay_factor)
            changed += 1
        if changed:
            await session.commit()
    return changed


async def resolve_contradictions(*, tenant_id: str = "default") -> int:
    """Find high-similarity note pairs in the same scope/category and supersede."""
    resolved = 0
    async with get_async_session_maker()() as session:
        scopes = (
            await session.execute(
                select(
                    LtmNote.tenant_id,
                    LtmNote.scope_type,
                    LtmNote.scope_key,
                    LtmNote.category,
                )
                .where(LtmNote.tenant_id == tenant_id, LtmNote.status == "active")
                .group_by(
                    LtmNote.tenant_id,
                    LtmNote.scope_type,
                    LtmNote.scope_key,
                    LtmNote.category,
                )
                .limit(50)
            )
        ).all()

    for tid, st, sk, cat in scopes:
        scope = MemoryScope(tid, st, sk)
        notes = await store.list_notes(scope, category=cat, status="active", limit=80)
        pairs: List[Tuple[LtmNote, LtmNote]] = []
        for i, a in enumerate(notes):
            vec_a = bytes_to_embedding(a.embedding)
            if vec_a is None:
                continue
            for b in notes[i + 1 :]:
                vec_b = bytes_to_embedding(b.embedding)
                if vec_b is None or a.id == b.id:
                    continue
                if a.superseded_by or b.superseded_by:
                    continue
                sim = cosine_similarity(vec_a, vec_b)
                if sim >= 0.85:
                    pairs.append((a, b))
        for a, b in pairs[:5]:
            user = (
                f"NOTE A (id={a.id}): {a.content}\n"
                f"NOTE B (id={b.id}): {b.content}\n"
                "Which is current?"
            )
            try:
                data = await complete_json_async(_CONTRADICTION_PROMPT, user)
                keep_id = int(data.get("keep_id", a.id))
                supersede_id = int(data.get("supersede_id", b.id))
            except Exception as exc:
                logger.debug("contradiction LLM skip: %s", exc)
                continue
            keep = await store.get_note(keep_id)
            old = await store.get_note(supersede_id)
            if not keep or not old or keep.id == old.id:
                continue
            await store.supersede_note(old.id, keep)
            resolved += 1
    return resolved


async def snapshot_quality_metrics(*, tenant_id: str = "default") -> Dict[str, Any]:
    """Observability snapshot: active notes, never-recalled fraction, wake coverage."""
    async with get_async_session_maker()() as session:
        active = (
            await session.execute(
                select(func.count())
                .select_from(LtmNote)
                .where(LtmNote.tenant_id == tenant_id, LtmNote.status == "active")
            )
        ).scalar_one()
        never_recalled = (
            await session.execute(
                select(func.count())
                .select_from(LtmNote)
                .where(
                    LtmNote.tenant_id == tenant_id,
                    LtmNote.status == "active",
                    LtmNote.recall_count == 0,
                )
            )
        ).scalar_one()
        by_user = (
            await session.execute(
                select(LtmNote.scope_key, func.count())
                .where(
                    LtmNote.tenant_id == tenant_id,
                    LtmNote.scope_type == "user",
                    LtmNote.status == "active",
                )
                .group_by(LtmNote.scope_key)
                .order_by(func.count().desc())
                .limit(20)
            )
        ).all()

    metrics = {
        "tenant_id": tenant_id,
        "active_notes": int(active or 0),
        "never_recalled": int(never_recalled or 0),
        "never_recalled_fraction": (
            float(never_recalled) / float(active) if active else 0.0
        ),
        "top_users_by_active_notes": [
            {"user": u, "count": int(c)} for u, c in by_user
        ],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("Mnemos quality snapshot: %s", metrics)
    return metrics


async def run_dream_cycle(*, tenant_id: str = "default") -> Dict[str, Any]:
    compressed = await compress_all_pending()
    contradictions = await resolve_contradictions(tenant_id=tenant_id)
    decayed = await decay_stale_confidence(tenant_id=tenant_id)
    backfilled = await backfill_embeddings(tenant_id=tenant_id, limit=100)
    metrics = await snapshot_quality_metrics(tenant_id=tenant_id)
    return {
        "compressed_digests": compressed,
        "contradictions_resolved": contradictions,
        "confidence_decayed": decayed,
        "embeddings_backfilled": backfilled,
        "metrics": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Mnemos dream cycle once")
    parser.add_argument("--tenant", default="default")
    args = parser.parse_args()
    result = asyncio.run(run_dream_cycle(tenant_id=args.tenant))
    print(result)


if __name__ == "__main__":
    main()
