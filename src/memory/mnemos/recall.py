"""Recall — targeted FTS retrieval with optional hybrid embedding rerank."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.data.models import LtmNote

from . import store
from .embedding import (
    embedding_recall_enabled,
    embeddings_configured,
    get_embedding,
)
from .format import format_note_line
from .ranking import rank_notes
from .types import MemoryScope

logger = logging.getLogger("aion.memory.mnemos.recall")


def recall_limit() -> int:
    return int(os.getenv("AION_MNEMOS_RECALL_LIMIT", "10"))


def _hybrid_candidate_mult() -> int:
    return max(2, int(os.getenv("AION_MNEMOS_HYBRID_CANDIDATE_MULT", "3")))


def _scope_for_note(note: LtmNote) -> MemoryScope:
    return MemoryScope(note.tenant_id, note.scope_type, note.scope_key)


def _note_rows(notes: List[LtmNote]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for n in notes:
        scope = _scope_for_note(n)
        confidence = getattr(n, "confidence", None)
        out.append(
            {
                "id": n.id,
                "seq": n.seq,
                "content": n.content,
                "category": n.category,
                "importance": n.importance,
                "status": n.status,
                "confidence": confidence,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "scope_type": scope.scope_type,
                "scope_key": scope.scope_key,
                "line": format_note_line(
                    seq=n.seq,
                    content=n.content,
                    created_at=n.created_at,
                    category=n.category,
                    scope_label=scope.scope_type,
                    confidence=confidence,
                ),
            }
        )
    return out


async def _gather_ranked_lists(
    scope: MemoryScope,
    query: str,
    *,
    limit: int,
    mode: str,
    as_of: Optional[datetime] = None,
    use_hybrid: bool,
) -> tuple[List[List[int]], Dict[int, LtmNote]]:
    candidate_limit = max(limit, limit * _hybrid_candidate_mult())
    fts_hits = await store.fts_search(
        scope, query, limit=candidate_limit, mode=mode, as_of=as_of
    )
    notes_by_id: Dict[int, LtmNote] = {n.id: n for n, _ in fts_hits}
    ranked_lists: List[List[int]] = []
    fts_ranked = [n.id for n, _ in fts_hits]
    if fts_ranked:
        ranked_lists.append(fts_ranked)

    if not use_hybrid or not embeddings_configured():
        return ranked_lists, notes_by_id

    try:
        query_vec = await asyncio.to_thread(get_embedding, query)
    except Exception as exc:
        logger.warning("Hybrid recall: embedding service unavailable: %s", exc)
        return ranked_lists, notes_by_id

    if query_vec is None:
        return ranked_lists, notes_by_id

    emb_hits = await store.embedding_search(
        scope,
        query_vec,
        limit=candidate_limit,
        mode=mode,
        as_of=as_of,
    )
    emb_ranked = [n.id for n, _ in emb_hits]
    for n, _ in emb_hits:
        notes_by_id[n.id] = n
    if emb_ranked:
        ranked_lists.append(emb_ranked)

    try:
        from .entities import entity_recall_enabled, search_entity_note_ids

        if entity_recall_enabled():
            entity_ids = await search_entity_note_ids(
                scope, query, limit=candidate_limit
            )
            if entity_ids:
                ranked_lists.append(entity_ids)
                entity_notes = await store.get_notes_by_ids(
                    entity_ids, mode=mode, as_of=as_of
                )
                for n in entity_notes:
                    notes_by_id[n.id] = n
    except Exception as exc:
        logger.debug("Entity recall skipped: %s", exc)

    return ranked_lists, notes_by_id


async def _recall_notes(
    scope: MemoryScope,
    query: str,
    *,
    limit: int,
    mode: str,
    as_of: Optional[datetime] = None,
    use_hybrid: Optional[bool] = None,
) -> List[LtmNote]:
    hybrid = use_hybrid if use_hybrid is not None else embedding_recall_enabled()
    ranked_lists, notes_by_id = await _gather_ranked_lists(
        scope, query, limit=limit, mode=mode, as_of=as_of, use_hybrid=hybrid
    )
    if not notes_by_id:
        return []
    ordered = rank_notes(ranked_lists, notes_by_id, limit=limit, now=as_of)
    await store.touch_recall_stats([n.id for n in ordered])
    return ordered


async def recall(
    scope: MemoryScope,
    query: str,
    *,
    limit: int | None = None,
    mode: str = "current",
    as_of: datetime | None = None,
) -> List[Dict[str, Any]]:
    lim = limit if limit is not None else recall_limit()
    notes = await _recall_notes(scope, query, limit=lim, mode=mode, as_of=as_of)
    return _note_rows(notes)


async def recall_across_scopes(
    scopes: List[MemoryScope],
    query: str,
    *,
    limit: int | None = None,
    mode: str = "current",
    as_of: datetime | None = None,
) -> List[Dict[str, Any]]:
    """Recall merged across scopes with global score normalization."""
    lim = limit if limit is not None else recall_limit()
    per_scope = max(lim, lim * _hybrid_candidate_mult())
    ranked_lists: List[List[int]] = []
    notes_by_id: Dict[int, LtmNote] = {}

    use_hybrid = embedding_recall_enabled()
    for scope in scopes:
        scope_lists, scope_notes = await _gather_ranked_lists(
            scope,
            query,
            limit=per_scope,
            mode=mode,
            as_of=as_of,
            use_hybrid=use_hybrid,
        )
        ranked_lists.extend(scope_lists)
        notes_by_id.update(scope_notes)

    if not notes_by_id:
        return []

    ordered = rank_notes(ranked_lists, notes_by_id, limit=lim, now=as_of)
    await store.touch_recall_stats([n.id for n in ordered])
    return _note_rows(ordered)
