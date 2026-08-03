"""Admin zoom — split a digest into its two child blocks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import store
from .types import MemoryScope
from .wake import resolve_block


async def zoom(
    scope: MemoryScope, lo: int, hi: int
) -> Dict[str, Any]:
    digest = await store.get_digest(scope, lo, hi)
    if not digest:
        return {"error": "digest_not_found", "lo": lo, "hi": hi}
    if hi - lo < 2:
        return {"error": "range_too_small", "lo": lo, "hi": hi}
    mid = (lo + hi) // 2
    left = await resolve_block(scope, lo, mid)
    right = await resolve_block(scope, mid, hi)
    return {
        "digest": {
            "lo": lo,
            "hi": hi,
            "ready": digest.ready,
            "summary": digest.summary_text,
        },
        "left": left,
        "right": right,
    }
