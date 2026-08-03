"""Wake algorithm — bounded-budget bootstrap read."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from src.data.engine import get_async_session_maker

from . import store
from .format import format_digest_line, format_note_line
from .types import MemoryScope


def wake_budget() -> int:
    return int(os.getenv("AION_LTM_WAKE_MAX_ROWS", "20"))


async def resolve_block(
    scope: MemoryScope, lo: int, hi: int
) -> List[Dict[str, Any]]:
    """Return ordered rows covering [lo, hi), descending to raw notes if needed."""
    if hi <= lo:
        return []
    digest = await store.get_digest(scope, lo, hi)
    if digest and digest.ready and (digest.summary_text or "").strip():
        return [
            {
                "kind": "digest",
                "lo": lo,
                "hi": hi,
                "line": format_digest_line(
                    range_start=lo,
                    range_end=hi,
                    summary=digest.summary_text or "",
                    scope_label=scope.scope_type,
                ),
            }
        ]
    if hi - lo == 1:
        notes = await store.get_notes_in_range(scope, lo, hi, active_only=True)
        rows: List[Dict[str, Any]] = []
        for n in notes:
            rows.append(
                {
                    "kind": "note",
                    "seq": n.seq,
                    "line": format_note_line(
                        seq=n.seq,
                        content=n.content,
                        created_at=n.created_at,
                        category=n.category,
                        scope_label=scope.scope_type,
                    ),
                }
            )
        return rows
    mid = (lo + hi) // 2
    left = await resolve_block(scope, lo, mid)
    right = await resolve_block(scope, mid, hi)
    return left + right


async def wake(scope: MemoryScope, k: int | None = None) -> List[Dict[str, Any]]:
    budget = k if k is not None else wake_budget()
    async with get_async_session_maker()() as session:
        t = await store.seq_count(session, scope)
    if t <= 0:
        return []

    rows: List[Dict[str, Any]] = []
    hi = t
    w = 1
    b = budget
    while hi > 0 and b > 0:
        lo = max(0, hi - w)
        block = await resolve_block(scope, lo, hi)
        rows = block + rows
        hi = lo
        w *= 2
        b -= 1
    if hi > 0:
        rows = (await resolve_block(scope, 0, hi)) + rows
    return rows[:budget]
