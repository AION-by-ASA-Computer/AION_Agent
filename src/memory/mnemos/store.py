"""Persistence layer for Mnemos notes and digests."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.engine import get_async_session_maker
from src.data.models import LtmDigest, LtmNote

from .embedding import (
    bytes_to_embedding,
    cosine_similarity,
    embed_on_bulk_insert,
    embedding_scan_limit,
    maybe_embed_text,
)
from .fts import build_fts_queries, fts_delete, fts_insert
from .types import CONTENT_MAX_CHARS, MemoryScope, NOTE_CATEGORIES

logger = logging.getLogger("aion.memory.mnemos.store")

_scope_insert_locks: dict[tuple[str, str, str], asyncio.Lock] = {}


def _insert_lock(scope: MemoryScope) -> asyncio.Lock:
    """Serialize note inserts per scope (parallel memory_note tool calls)."""
    key = scope.as_tuple()
    if key not in _scope_insert_locks:
        _scope_insert_locks[key] = asyncio.Lock()
    return _scope_insert_locks[key]


def _normalize_category(category: Optional[str]) -> str:
    c = (category or "fact").strip().lower()
    return c if c in NOTE_CATEGORIES else "fact"


def _clamp_content(text: str) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) > CONTENT_MAX_CHARS:
        return t[: CONTENT_MAX_CHARS - 3] + "..."
    return t


async def _embedding_blob_for_content(body: str, *, allow: bool = True) -> bytes | None:
    if not allow:
        return None
    return await maybe_embed_text(body)


async def seq_count(session: AsyncSession, scope: MemoryScope) -> int:
    tid, st, sk = scope.as_tuple()
    val = (
        await session.execute(
            select(func.count())
            .select_from(LtmNote)
            .where(
                LtmNote.tenant_id == tid,
                LtmNote.scope_type == st,
                LtmNote.scope_key == sk,
            )
        )
    ).scalar_one()
    return int(val or 0)


async def next_seq(session: AsyncSession, scope: MemoryScope) -> int:
    tid, st, sk = scope.as_tuple()
    val = (
        await session.execute(
            select(func.coalesce(func.max(LtmNote.seq), -1)).where(
                LtmNote.tenant_id == tid,
                LtmNote.scope_type == st,
                LtmNote.scope_key == sk,
            )
        )
    ).scalar_one()
    return int(val) + 1


async def insert_notes_bulk(
    scope: MemoryScope,
    contents: Sequence[str],
    *,
    category: str = "fact",
    importance: int = 3,
    source_session_id: Optional[str] = None,
) -> int:
    """Insert many notes in one transaction (benchmark ingest). Returns count."""
    bodies = [_clamp_content(c) for c in contents if len(_clamp_content(c)) >= 3]
    if not bodies:
        return 0
    imp = max(1, min(5, int(importance)))
    cat = _normalize_category(category)

    async with _insert_lock(scope):
        async with get_async_session_maker()() as sess:
            start_seq = await next_seq(sess, scope)
            notes: List[LtmNote] = []
            embed_notes = embed_on_bulk_insert()
            for offset, body in enumerate(bodies):
                emb = await _embedding_blob_for_content(body, allow=embed_notes)
                note = LtmNote(
                    tenant_id=scope.tenant_id,
                    scope_type=scope.scope_type,
                    scope_key=scope.scope_key,
                    seq=start_seq + offset,
                    content=body,
                    category=cat,
                    importance=imp,
                    status="active",
                    source_session_id=source_session_id,
                    embedding=emb,
                )
                sess.add(note)
                notes.append(note)
            await sess.flush()
            for note in notes:
                await fts_insert(
                    sess,
                    note_id=note.id,
                    tenant_id=scope.tenant_id,
                    scope_type=scope.scope_type,
                    scope_key=scope.scope_key,
                    content=note.content,
                )
            if notes:
                await invalidate_digests_covering(
                    sess, scope, start_seq + len(notes) - 1
                )
            await sess.commit()
            return len(notes)


async def insert_note(
    scope: MemoryScope,
    *,
    content: str,
    category: str = "fact",
    importance: int = 3,
    source_session_id: Optional[str] = None,
    source_message_id: Optional[str] = None,
    session: Optional[AsyncSession] = None,
) -> LtmNote:
    body = _clamp_content(content)
    if len(body) < 3:
        raise ValueError("Note content too short")
    imp = max(1, min(5, int(importance)))

    async def _do(sess: AsyncSession) -> LtmNote:
        seq = await next_seq(sess, scope)
        emb = await _embedding_blob_for_content(body)
        note = LtmNote(
            tenant_id=scope.tenant_id,
            scope_type=scope.scope_type,
            scope_key=scope.scope_key,
            seq=seq,
            content=body,
            category=_normalize_category(category),
            importance=imp,
            status="active",
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            embedding=emb,
        )
        sess.add(note)
        await sess.flush()
        await fts_insert(
            sess,
            note_id=note.id,
            tenant_id=scope.tenant_id,
            scope_type=scope.scope_type,
            scope_key=scope.scope_key,
            content=body,
        )
        await invalidate_digests_covering(sess, scope, seq)
        return note

    if session is not None:
        return await _do(session)

    async with _insert_lock(scope):
        for attempt in range(5):
            try:
                async with get_async_session_maker()() as sess:
                    note = await _do(sess)
                    await sess.commit()
                    await sess.refresh(note)
                    return note
            except IntegrityError:
                if attempt >= 4:
                    raise
                await asyncio.sleep(0.02 * (attempt + 1))
    raise RuntimeError("unreachable")


async def get_note(note_id: int) -> Optional[LtmNote]:
    async with get_async_session_maker()() as session:
        return await session.get(LtmNote, note_id)


async def list_notes(
    scope: MemoryScope,
    *,
    category: Optional[str] = None,
    status: str = "active",
    limit: int = 100,
    offset: int = 0,
) -> List[LtmNote]:
    tid, st, sk = scope.as_tuple()
    async with get_async_session_maker()() as session:
        q = (
            select(LtmNote)
            .where(
                LtmNote.tenant_id == tid,
                LtmNote.scope_type == st,
                LtmNote.scope_key == sk,
            )
            .order_by(LtmNote.seq.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            q = q.where(LtmNote.status == status)
        if category:
            q = q.where(LtmNote.category == _normalize_category(category))
        return list((await session.execute(q)).scalars().all())


async def follow_supersede_chain(note: LtmNote) -> LtmNote:
    current = note
    seen: set[int] = set()
    async with get_async_session_maker()() as session:
        while current.superseded_by and current.id not in seen:
            seen.add(current.id)
            nxt = await session.get(LtmNote, current.superseded_by)
            if not nxt:
                break
            current = nxt
        return current


async def supersede_note(
    old_note_id: int,
    new_note: LtmNote,
    *,
    session: Optional[AsyncSession] = None,
) -> None:
    async def _do(sess: AsyncSession) -> None:
        old = await sess.get(LtmNote, old_note_id)
        if not old or old.status == "superseded":
            return
        old.status = "superseded"
        old.superseded_by = new_note.id
        scope = MemoryScope(old.tenant_id, old.scope_type, old.scope_key)
        await invalidate_digests_covering(sess, scope, old.seq)

    if session is not None:
        await _do(session)
        return

    async with get_async_session_maker()() as sess:
        await _do(sess)
        await sess.commit()


async def find_supersede_candidates(
    scope: MemoryScope,
    hint: str,
    *,
    limit: int = 5,
) -> List[LtmNote]:
    hits = await fts_search(scope, hint, limit=limit, mode="current")
    return [h for h in hits if h.status == "active"]


async def forget_note(note_id: int, *, hard: bool = False) -> bool:
    async with get_async_session_maker()() as session:
        note = await session.get(LtmNote, note_id)
        if not note:
            return False
        if hard:
            await fts_delete(session, note_id)
            await session.delete(note)
        else:
            note.status = "superseded"
            scope = MemoryScope(note.tenant_id, note.scope_type, note.scope_key)
            await invalidate_digests_covering(session, scope, note.seq)
        await session.commit()
        return True


async def invalidate_digests_covering(
    session: AsyncSession, scope: MemoryScope, seq: int
) -> None:
    tid, st, sk = scope.as_tuple()
    rows = (
        await session.execute(
            select(LtmDigest).where(
                LtmDigest.tenant_id == tid,
                LtmDigest.scope_type == st,
                LtmDigest.scope_key == sk,
                LtmDigest.range_start_seq <= seq,
                LtmDigest.range_end_seq > seq,
                LtmDigest.ready.is_(True),
            )
        )
    ).scalars().all()
    for d in rows:
        d.ready = False
        d.updated_at = datetime.now(timezone.utc)
        await _invalidate_ancestors(session, scope, d.range_start_seq, d.range_end_seq)


async def _invalidate_ancestors(
    session: AsyncSession,
    scope: MemoryScope,
    lo: int,
    hi: int,
) -> None:
    tid, st, sk = scope.as_tuple()
    parents = (
        await session.execute(
            select(LtmDigest).where(
                LtmDigest.tenant_id == tid,
                LtmDigest.scope_type == st,
                LtmDigest.scope_key == sk,
                LtmDigest.range_start_seq <= lo,
                LtmDigest.range_end_seq >= hi,
                LtmDigest.ready.is_(True),
            )
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for p in parents:
        if p.range_start_seq == lo and p.range_end_seq == hi:
            continue
        p.ready = False
        p.updated_at = now


async def _get_digest_in_session(
    session: AsyncSession, scope: MemoryScope, lo: int, hi: int
) -> Optional[LtmDigest]:
    tid, st, sk = scope.as_tuple()
    return (
        await session.execute(
            select(LtmDigest).where(
                LtmDigest.tenant_id == tid,
                LtmDigest.scope_type == st,
                LtmDigest.scope_key == sk,
                LtmDigest.range_start_seq == lo,
                LtmDigest.range_end_seq == hi,
            )
        )
    ).scalar_one_or_none()


async def get_digest(
    scope: MemoryScope, lo: int, hi: int
) -> Optional[LtmDigest]:
    async with get_async_session_maker()() as session:
        return await _get_digest_in_session(session, scope, lo, hi)


async def upsert_digest(
    scope: MemoryScope,
    lo: int,
    hi: int,
    summary: str,
    *,
    ready: bool = True,
    session: Optional[AsyncSession] = None,
) -> LtmDigest:
    level = hi - lo
    summary = _clamp_content(summary)

    async def _do(sess: AsyncSession) -> LtmDigest:
        existing = await _get_digest_in_session(sess, scope, lo, hi)
        if existing:
            existing.summary_text = summary
            existing.ready = ready
            existing.level = level
            existing.updated_at = datetime.now(timezone.utc)
            return existing
        d = LtmDigest(
            tenant_id=scope.tenant_id,
            scope_type=scope.scope_type,
            scope_key=scope.scope_key,
            level=level,
            range_start_seq=lo,
            range_end_seq=hi,
            summary_text=summary,
            ready=ready,
        )
        sess.add(d)
        await sess.flush()
        return d

    if session is not None:
        return await _do(session)

    async with get_async_session_maker()() as sess:
        d = await _do(sess)
        await sess.commit()
        await sess.refresh(d)
        return d


async def get_notes_in_range(
    scope: MemoryScope, lo: int, hi: int, *, active_only: bool = True
) -> List[LtmNote]:
    tid, st, sk = scope.as_tuple()
    async with get_async_session_maker()() as session:
        q = (
            select(LtmNote)
            .where(
                LtmNote.tenant_id == tid,
                LtmNote.scope_type == st,
                LtmNote.scope_key == sk,
                LtmNote.seq >= lo,
                LtmNote.seq < hi,
            )
            .order_by(LtmNote.seq.asc())
        )
        if active_only:
            q = q.where(LtmNote.status == "active")
        return list((await session.execute(q)).scalars().all())


async def fts_search(
    scope: MemoryScope,
    query: str,
    *,
    limit: int = 10,
    mode: str = "current",
) -> List[LtmNote]:
    tid, st, sk = scope.as_tuple()
    queries = build_fts_queries(query)
    if not queries:
        return []
    async with get_async_session_maker()() as session:
        rows = None
        fts_q_used = ""
        for fts_q in queries:
            fts_q_used = fts_q
            try:
                rows = (
                    await session.execute(
                        text(
                            """
                    SELECT note_id, bm25(ltm_notes_fts) AS score
                    FROM ltm_notes_fts
                    WHERE ltm_notes_fts MATCH :q
                      AND tenant_id = :tid
                      AND scope_type = :st
                      AND scope_key = :sk
                    ORDER BY score
                    LIMIT :lim
                    """
                        ),
                        {"q": fts_q, "tid": tid, "st": st, "sk": sk, "lim": limit},
                    )
                ).mappings().all()
            except Exception as exc:
                logger.warning(
                    "Mnemos FTS search failed scope=%s:%s query=%r escaped=%r: %s",
                    st,
                    sk,
                    query[:120],
                    fts_q[:120],
                    exc,
                )
                rows = None
            if rows:
                break
        if not rows:
            return []
        out: List[LtmNote] = []
        for r in rows:
            nid = int(r["note_id"])
            note = await session.get(LtmNote, nid)
            if not note:
                continue
            if mode == "current" and note.status == "superseded":
                note = await follow_supersede_chain(note)
            out.append(note)
        return out


async def get_notes_by_ids(
    note_ids: List[int],
    *,
    mode: str = "current",
) -> List[LtmNote]:
    if not note_ids:
        return []
    async with get_async_session_maker()() as session:
        rows = list(
            (await session.execute(select(LtmNote).where(LtmNote.id.in_(note_ids))))
            .scalars()
            .all()
        )
        out: List[LtmNote] = []
        for note in rows:
            if mode == "current" and note.status == "superseded":
                note = await follow_supersede_chain(note)
            out.append(note)
        return out


async def embedding_search(
    scope: MemoryScope,
    query_vec,
    *,
    limit: int = 10,
    mode: str = "current",
) -> List[LtmNote]:
    """Cosine similarity over stored note embeddings (bounded scan)."""
    import numpy as np

    if query_vec is None:
        return []
    tid, st, sk = scope.as_tuple()
    scan_lim = embedding_scan_limit()
    async with get_async_session_maker()() as session:
        q = (
            select(LtmNote)
            .where(
                LtmNote.tenant_id == tid,
                LtmNote.scope_type == st,
                LtmNote.scope_key == sk,
                LtmNote.status == "active",
                LtmNote.embedding.is_not(None),
            )
            .order_by(LtmNote.seq.desc())
            .limit(scan_lim)
        )
        rows = list((await session.execute(q)).scalars().all())

    scored: list[tuple[float, LtmNote]] = []
    for note in rows:
        vec = bytes_to_embedding(note.embedding)
        if vec is None:
            continue
        sim = cosine_similarity(np.asarray(query_vec, dtype=np.float32), vec)
        scored.append((sim, note))
    scored.sort(key=lambda item: item[0], reverse=True)

    out: List[LtmNote] = []
    for _, note in scored[:limit]:
        if mode == "current" and note.status == "superseded":
            note = await follow_supersede_chain(note)
        out.append(note)
    return out


async def list_digests(
    scope: MemoryScope,
    *,
    ready_only: Optional[bool] = None,
    limit: int = 500,
) -> List[LtmDigest]:
    tid, st, sk = scope.as_tuple()
    async with get_async_session_maker()() as session:
        q = (
            select(LtmDigest)
            .where(
                LtmDigest.tenant_id == tid,
                LtmDigest.scope_type == st,
                LtmDigest.scope_key == sk,
            )
            .order_by(LtmDigest.range_start_seq.asc(), LtmDigest.range_end_seq.asc())
            .limit(limit)
        )
        if ready_only is True:
            q = q.where(LtmDigest.ready.is_(True))
        elif ready_only is False:
            q = q.where(LtmDigest.ready.is_(False))
        return list((await session.execute(q)).scalars().all())


async def note_counts(scope: MemoryScope) -> Dict[str, int]:
    tid, st, sk = scope.as_tuple()
    async with get_async_session_maker()() as session:
        total = (
            await session.execute(
                select(func.count())
                .select_from(LtmNote)
                .where(
                    LtmNote.tenant_id == tid,
                    LtmNote.scope_type == st,
                    LtmNote.scope_key == sk,
                )
            )
        ).scalar_one()
        active = (
            await session.execute(
                select(func.count())
                .select_from(LtmNote)
                .where(
                    LtmNote.tenant_id == tid,
                    LtmNote.scope_type == st,
                    LtmNote.scope_key == sk,
                    LtmNote.status == "active",
                )
            )
        ).scalar_one()
        digests = (
            await session.execute(
                select(func.count())
                .select_from(LtmDigest)
                .where(
                    LtmDigest.tenant_id == tid,
                    LtmDigest.scope_type == st,
                    LtmDigest.scope_key == sk,
                    LtmDigest.ready.is_(True),
                )
            )
        ).scalar_one()
        return {
            "notes_total": int(total or 0),
            "notes_active": int(active or 0),
            "digests_ready": int(digests or 0),
        }


async def digest_debug_stats(scope: MemoryScope) -> Dict[str, Any]:
    """Extended counters for Mnemos debug UI."""
    tid, st, sk = scope.as_tuple()
    base = await note_counts(scope)
    async with get_async_session_maker()() as session:
        seq_n = await seq_count(session, scope)
        digests_total = (
            await session.execute(
                select(func.count())
                .select_from(LtmDigest)
                .where(
                    LtmDigest.tenant_id == tid,
                    LtmDigest.scope_type == st,
                    LtmDigest.scope_key == sk,
                )
            )
        ).scalar_one()
        digests_stale = (
            await session.execute(
                select(func.count())
                .select_from(LtmDigest)
                .where(
                    LtmDigest.tenant_id == tid,
                    LtmDigest.scope_type == st,
                    LtmDigest.scope_key == sk,
                    LtmDigest.ready.is_(False),
                )
            )
        ).scalar_one()
        superseded = (
            await session.execute(
                select(func.count())
                .select_from(LtmNote)
                .where(
                    LtmNote.tenant_id == tid,
                    LtmNote.scope_type == st,
                    LtmNote.scope_key == sk,
                    LtmNote.status == "superseded",
                )
            )
        ).scalar_one()
        level_rows = (
            await session.execute(
                select(LtmDigest.level, func.count())
                .where(
                    LtmDigest.tenant_id == tid,
                    LtmDigest.scope_type == st,
                    LtmDigest.scope_key == sk,
                )
                .group_by(LtmDigest.level)
                .order_by(LtmDigest.level.asc())
            )
        ).all()
    return {
        **base,
        "seq_count": int(seq_n or 0),
        "notes_superseded": int(superseded or 0),
        "digests_total": int(digests_total or 0),
        "digests_stale": int(digests_stale or 0),
        "digest_levels": {int(lv): int(cnt) for lv, cnt in level_rows},
    }
