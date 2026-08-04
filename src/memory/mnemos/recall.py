"""Recall — targeted FTS retrieval with optional hybrid embedding rerank."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List

from . import store
from .embedding import (
    bytes_to_embedding,
    cosine_similarity,
    embedding_min_score,
    embedding_recall_enabled,
    embeddings_configured,
    get_embedding,
    reciprocal_rank_fusion,
)
from .format import format_note_line
from .types import MemoryScope

logger = logging.getLogger("aion.memory.mnemos.recall")


def recall_limit() -> int:
    return int(os.getenv("AION_MNEMOS_RECALL_LIMIT", "10"))


def _note_rows(notes: List, scope: MemoryScope) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for n in notes:
        out.append(
            {
                "id": n.id,
                "seq": n.seq,
                "content": n.content,
                "category": n.category,
                "importance": n.importance,
                "status": n.status,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "scope_type": scope.scope_type,
                "scope_key": scope.scope_key,
                "line": format_note_line(
                    seq=n.seq,
                    content=n.content,
                    created_at=n.created_at,
                    category=n.category,
                    scope_label=scope.scope_type,
                ),
            }
        )
    return out


async def _fts_recall(
    scope: MemoryScope,
    query: str,
    *,
    limit: int,
    mode: str,
) -> List[Dict[str, Any]]:
    notes = await store.fts_search(scope, query, limit=limit, mode=mode)
    return _note_rows(notes, scope)


async def _hybrid_recall(
    scope: MemoryScope,
    query: str,
    *,
    limit: int,
    mode: str,
) -> List[Dict[str, Any]]:
    """FTS candidates reranked with embeddings; falls back to FTS-only."""
    candidate_mult = max(2, int(os.getenv("AION_MNEMOS_HYBRID_CANDIDATE_MULT", "3")))
    fts_limit = max(limit, limit * candidate_mult)
    fts_notes = await store.fts_search(scope, query, limit=fts_limit, mode=mode)
    fts_ranked = [n.id for n in fts_notes]

    if not embeddings_configured():
        return _note_rows(fts_notes[:limit], scope)

    try:
        query_vec = await asyncio.to_thread(get_embedding, query)
    except Exception as exc:
        logger.warning("Hybrid recall: embedding service unavailable: %s", exc)
        return _note_rows(fts_notes[:limit], scope)

    if query_vec is None:
        return _note_rows(fts_notes[:limit], scope)

    min_score = embedding_min_score()
    emb_ranked: List[int] = []

    for note in fts_notes:
        blob = getattr(note, "embedding", None)
        vec = bytes_to_embedding(blob)
        if vec is None:
            continue
        if cosine_similarity(query_vec, vec) >= min_score:
            emb_ranked.append(note.id)

    if not emb_ranked:
        scope_emb = await store.embedding_search(
            scope,
            query_vec,
            limit=max(limit, fts_limit),
            mode=mode,
        )
        emb_ranked = [n.id for n in scope_emb]

    if not emb_ranked and not fts_ranked:
        return []

    if not emb_ranked:
        return _note_rows(fts_notes[:limit], scope)

    fused = reciprocal_rank_fusion([fts_ranked, emb_ranked])
    ordered_ids = [note_id for note_id, _ in fused[: max(limit, len(fused))]]
    notes_by_id = {n.id: n for n in fts_notes}
    missing = [nid for nid in ordered_ids if nid not in notes_by_id]
    if missing:
        extra = await store.get_notes_by_ids(missing, mode=mode)
        notes_by_id.update({n.id: n for n in extra})

    ordered_notes = [notes_by_id[nid] for nid in ordered_ids if nid in notes_by_id]
    return _note_rows(ordered_notes[:limit], scope)


async def recall(
    scope: MemoryScope,
    query: str,
    *,
    limit: int | None = None,
    mode: str = "current",
) -> List[Dict[str, Any]]:
    lim = limit if limit is not None else recall_limit()
    if embedding_recall_enabled():
        return await _hybrid_recall(scope, query, limit=lim, mode=mode)
    return await _fts_recall(scope, query, limit=lim, mode=mode)


async def recall_across_scopes(
    scopes: List[MemoryScope],
    query: str,
    *,
    limit: int | None = None,
    mode: str = "current",
) -> List[Dict[str, Any]]:
    """Recall merged across scopes (user + project, etc.), deduped by note id."""
    lim = limit if limit is not None else recall_limit()
    seen: set[int] = set()
    merged: List[Dict[str, Any]] = []
    per_scope = max(lim, 5)
    for scope in scopes:
        rows = await recall(scope, query, limit=per_scope, mode=mode)
        for row in rows:
            nid = int(row["id"])
            if nid in seen:
                continue
            seen.add(nid)
            merged.append(row)
            if len(merged) >= lim:
                return merged
    return merged
