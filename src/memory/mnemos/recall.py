"""Recall — targeted FTS retrieval with optional embedding layer."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from . import store
from .format import format_note_line
from .types import MemoryScope


def recall_limit() -> int:
    return int(os.getenv("AION_MNEMOS_RECALL_LIMIT", "10"))


async def recall(
    scope: MemoryScope,
    query: str,
    *,
    limit: int | None = None,
    mode: str = "current",
) -> List[Dict[str, Any]]:
    lim = limit if limit is not None else recall_limit()
    notes = await store.fts_search(scope, query, limit=lim, mode=mode)
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


async def recall_across_scopes(
    scopes: List[MemoryScope],
    query: str,
    *,
    limit: int | None = None,
    mode: str = "current",
) -> List[Dict[str, Any]]:
    """FTS recall merged across scopes (user + project, etc.), deduped by note id."""
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
