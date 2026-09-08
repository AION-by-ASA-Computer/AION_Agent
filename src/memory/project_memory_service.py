"""REST-facing service for project-scoped Mnemos notes (chat-ui)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.memory.mnemos.compress import compress_scope
from src.memory.mnemos.orchestrator import mnemos_orchestrator
from src.memory.mnemos.scope import (
    project_scope,
    sanitize_project_slug,
)
from src.memory.mnemos import store
from src.memory.mnemos.wake import wake
from src.memory.mnemos.zoom import zoom as zoom_digest

logger = logging.getLogger("aion.project_memory")

NOTE_CATEGORIES = (
    "preference",
    "fact",
    "event",
    "decision",
    "pitfall",
    "task",
)


def _digest_to_dict(digest) -> Dict[str, Any]:
    return {
        "lo": digest.range_start_seq,
        "hi": digest.range_end_seq,
        "level": digest.level,
        "ready": bool(digest.ready),
        "summary": digest.summary_text or "",
        "updated_at": digest.updated_at.isoformat() if digest.updated_at else None,
    }


def _note_to_dict(note) -> Dict[str, Any]:
    return {
        "id": note.id,
        "seq": note.seq,
        "content": note.content,
        "category": note.category,
        "importance": note.importance,
        "status": note.status,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "superseded_by": note.superseded_by,
        "source_session_id": note.source_session_id,
    }


async def _note_dict_by_id(note_id: int) -> Dict[str, Any]:
    note = await store.get_note(note_id)
    if not note:
        raise ValueError("note_not_found")
    return _note_to_dict(note)


async def list_project_notes(
    *,
    tenant_id: str,
    project_slug: str,
    category: Optional[str] = None,
    status: str = "active",
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    scope = project_scope(tenant_id, project_slug)
    notes = await store.list_notes(
        scope, category=category, status=status, limit=limit, offset=offset
    )
    return [_note_to_dict(n) for n in notes]


async def search_project_notes(
    *,
    tenant_id: str,
    project_slug: str,
    query: str,
    limit: int = 20,
    mode: str = "current",
) -> List[Dict[str, Any]]:
    from src.memory.mnemos.recall import recall

    scope = project_scope(tenant_id, project_slug)
    rows = await recall(scope, query, limit=limit, mode=mode)
    return rows


async def create_project_note(
    *,
    tenant_id: str,
    user_id: str,
    project_slug: str,
    content: str,
    category: str = "fact",
    importance: int = 3,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    out = await mnemos_orchestrator.add_note(
        tenant_id=tenant_id,
        user_id=user_id,
        text=content,
        scope_name="project",
        category=category,
        importance=importance,
        active_project_slug=project_slug,
        source_session_id=session_id,
    )
    return await _note_dict_by_id(int(out["id"]))


async def update_project_note(
    *,
    tenant_id: str,
    user_id: str,
    project_slug: str,
    note_id: int,
    content: str,
    category: Optional[str] = None,
    importance: Optional[int] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    old = await store.get_note(note_id)
    if not old:
        raise ValueError("note_not_found")
    out = await mnemos_orchestrator.add_note(
        tenant_id=tenant_id,
        user_id=user_id,
        text=content,
        scope_name="project",
        category=category or old.category,
        importance=importance if importance is not None else old.importance,
        active_project_slug=project_slug,
        source_session_id=session_id,
        supersede_hint=old.content,
    )
    return await _note_dict_by_id(int(out["id"]))


async def delete_project_note(
    note_id: int,
    *,
    tenant_id: str,
    project_slug: str,
) -> bool:
    note = await store.get_note(note_id)
    if not note:
        return False
    slug = sanitize_project_slug(project_slug)
    if (
        note.tenant_id != tenant_id
        or note.scope_type != "project"
        or note.scope_key != slug
    ):
        return False
    return await store.forget_note(note_id, hard=False)


async def project_memory_status(*, tenant_id: str, project_slug: str) -> Dict[str, Any]:
    scope = project_scope(tenant_id, sanitize_project_slug(project_slug))
    counts = await store.digest_debug_stats(scope)
    return {
        "project": sanitize_project_slug(project_slug),
        "tenant_id": tenant_id,
        "scope_type": "project",
        "scope_key": sanitize_project_slug(project_slug),
        **counts,
    }


async def get_project_note(
    *, tenant_id: str, project_slug: str, note_id: int
) -> Dict[str, Any]:
    note = await store.get_note(note_id)
    if not note:
        raise ValueError("note_not_found")
    slug = sanitize_project_slug(project_slug)
    if (
        note.tenant_id != tenant_id
        or note.scope_type != "project"
        or note.scope_key != slug
    ):
        raise ValueError("note_not_found")
    return _note_to_dict(note)


async def list_project_digests(
    *,
    tenant_id: str,
    project_slug: str,
    ready_only: Optional[bool] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    scope = project_scope(tenant_id, project_slug)
    digests = await store.list_digests(scope, ready_only=ready_only, limit=limit)
    return [_digest_to_dict(d) for d in digests]


async def zoom_project_digest(
    *, tenant_id: str, project_slug: str, lo: int, hi: int
) -> Dict[str, Any]:
    scope = project_scope(tenant_id, project_slug)
    return await zoom_digest(scope, lo, hi)


async def project_wake_preview(
    *, tenant_id: str, project_slug: str, budget: Optional[int] = None
) -> Dict[str, Any]:
    scope = project_scope(tenant_id, project_slug)
    rows = await wake(scope, k=budget)
    return {"rows": rows, "budget": budget}


async def compress_project_memory(
    *, tenant_id: str, project_slug: str
) -> Dict[str, Any]:
    scope = project_scope(tenant_id, project_slug)
    n = await compress_scope(scope)
    return {"compressed": n}
