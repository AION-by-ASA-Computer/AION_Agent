"""Digest compression (CompressBlock) and background maintenance."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

from sqlalchemy import select

from src.data.engine import get_async_session_maker
from src.data.models import LtmDigest
from src.memory.llm_extract import complete_json_async
from src.skill_registry import skill_registry

from . import store
from .types import MemoryScope

logger = logging.getLogger("aion.memory.mnemos.compress")

_compress_task: Optional[asyncio.Task] = None


def _compression_skill() -> str:
    return skill_registry.get_skill("ltm_digest_compression") or (
        "Compress the block into one line max 500 chars. Reply with JSON: "
        '{"summary": "..."}'
    )


async def _fetch_block_content(scope: MemoryScope, lo: int, hi: int) -> str:
    if hi - lo == 1:
        notes = await store.get_notes_in_range(scope, lo, hi, active_only=True)
        lines = []
        for n in notes:
            lines.append(f"[#{n.seq}] ({n.category}) {n.content}")
        return "\n".join(lines)
    mid = (lo + hi) // 2
    left_d = await store.get_digest(scope, lo, mid)
    right_d = await store.get_digest(scope, mid, hi)
    parts = []
    if left_d and left_d.ready and left_d.summary_text:
        parts.append(left_d.summary_text)
    if right_d and right_d.ready and right_d.summary_text:
        parts.append(right_d.summary_text)
    return "\n".join(parts)


async def _half_ready(scope: MemoryScope, lo: int, hi: int) -> bool:
    if hi - lo == 1:
        notes = await store.get_notes_in_range(scope, lo, hi, active_only=False)
        return len(notes) > 0
    d = await store.get_digest(scope, lo, hi)
    return bool(d and d.ready)


async def compress_block(scope: MemoryScope, lo: int, hi: int) -> Optional[str]:
    if hi - lo < 2:
        return None
    mid = (lo + hi) // 2
    if not await _half_ready(scope, lo, mid):
        return None
    if not await _half_ready(scope, mid, hi):
        return None
    content = await _fetch_block_content(scope, lo, hi)
    if not content.strip():
        return None
    system = _compression_skill()
    user = f"SCOPE: {scope.scope_type}/{scope.scope_key}\nBLOCK [{lo},{hi}):\n{content}"
    try:
        data = await complete_json_async(system, user)
        summary = (data.get("summary") or data.get("text") or "").strip()
        if not summary and isinstance(data, str):
            summary = data.strip()
    except Exception as e:
        logger.warning("digest compression LLM failed: %s", e)
        return None
    if not summary:
        return None
    await store.upsert_digest(scope, lo, hi, summary, ready=True)
    return summary


async def compress_scope(scope: MemoryScope) -> int:
    """Try to compress all mergeable blocks in scope; returns count compressed."""
    async with get_async_session_maker()() as session:
        t = await store.seq_count(session, scope)
    if t < 2:
        return 0
    compressed = 0
    size = 2
    while size <= t:
        lo = 0
        while lo + size <= t:
            hi = lo + size
            existing = await store.get_digest(scope, lo, hi)
            if not existing or not existing.ready:
                result = await compress_block(scope, lo, hi)
                if result:
                    compressed += 1
            lo += size
        size *= 2
    return compressed


def schedule_compress(scope: MemoryScope) -> None:
    global _compress_task

    async def _run() -> None:
        try:
            n = await compress_scope(scope)
            if n:
                logger.info(
                    "Mnemos compressed %d digest(s) for %s/%s",
                    n,
                    scope.scope_type,
                    scope.scope_key,
                )
        except Exception as e:
            logger.warning("Mnemos compress job failed: %s", e)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        pass


async def compress_all_pending() -> int:
    """Periodic job: re-compress not-ready digests across all scopes."""
    total = 0
    async with get_async_session_maker()() as session:
        rows = (
            await session.execute(
                select(LtmDigest).where(LtmDigest.ready.is_(False)).limit(50)
            )
        ).scalars().all()
    seen: set[tuple[str, str, str]] = set()
    for d in rows:
        key = (d.tenant_id, d.scope_type, d.scope_key)
        if key in seen:
            continue
        seen.add(key)
        scope = MemoryScope(d.tenant_id, d.scope_type, d.scope_key)
        total += await compress_scope(scope)
    return total
