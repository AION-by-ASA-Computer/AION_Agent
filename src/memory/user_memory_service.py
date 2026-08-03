"""REST-facing service for user-scoped Mnemos notes (chat-ui)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.memory.mnemos.compress import compress_scope
from src.memory.mnemos.orchestrator import mnemos_orchestrator
from src.memory.mnemos.scope import (
    default_tenant_id,
    sanitize_scope_key,
    user_scope,
)
from src.memory.mnemos import store
from src.memory.mnemos.wake import wake
from src.memory.mnemos.zoom import zoom as zoom_digest
from src.memory.project_memory_service import (
    NOTE_CATEGORIES,
    _digest_to_dict,
    _note_dict_by_id,
    _note_to_dict,
)

__all__ = ["NOTE_CATEGORIES"]


def _user_scope(tenant_id: str, user_identifier: str):
    return user_scope(tenant_id, user_identifier)


def _assert_user_note(note, *, tenant_id: str, user_identifier: str) -> None:
    key = sanitize_scope_key(user_identifier)
    if (
        not note
        or note.tenant_id != tenant_id
        or note.scope_type != "user"
        or note.scope_key != key
    ):
        raise ValueError("note_not_found")


async def list_user_notes(
    *,
    tenant_id: str,
    user_identifier: str,
    category: Optional[str] = None,
    status: str = "active",
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    scope = _user_scope(tenant_id, user_identifier)
    notes = await store.list_notes(
        scope, category=category, status=status, limit=limit, offset=offset
    )
    return [_note_to_dict(n) for n in notes]


async def search_user_notes(
    *,
    tenant_id: str,
    user_identifier: str,
    query: str,
    limit: int = 20,
    mode: str = "current",
) -> List[Dict[str, Any]]:
    scope = _user_scope(tenant_id, user_identifier)
    notes = await store.fts_search(scope, query, limit=limit, mode=mode)
    return [_note_to_dict(n) for n in notes]


async def create_user_note(
    *,
    tenant_id: str,
    user_identifier: str,
    content: str,
    category: str = "fact",
    importance: int = 3,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    out = await mnemos_orchestrator.add_note(
        tenant_id=tenant_id,
        user_id=user_identifier,
        text=content,
        scope_name="user",
        category=category,
        importance=importance,
        source_session_id=session_id,
    )
    return await _note_dict_by_id(int(out["id"]))


async def update_user_note(
    *,
    tenant_id: str,
    user_identifier: str,
    note_id: int,
    content: str,
    category: Optional[str] = None,
    importance: Optional[int] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    old = await store.get_note(note_id)
    _assert_user_note(old, tenant_id=tenant_id, user_identifier=user_identifier)
    out = await mnemos_orchestrator.add_note(
        tenant_id=tenant_id,
        user_id=user_identifier,
        text=content,
        scope_name="user",
        category=category or old.category,
        importance=importance if importance is not None else old.importance,
        source_session_id=session_id,
        supersede_hint=old.content,
    )
    return await _note_dict_by_id(int(out["id"]))


async def delete_user_note(
    *, tenant_id: str, user_identifier: str, note_id: int
) -> bool:
    note = await store.get_note(note_id)
    _assert_user_note(note, tenant_id=tenant_id, user_identifier=user_identifier)
    return await store.forget_note(note_id, hard=False)


async def user_memory_status(
    *, tenant_id: str, user_identifier: str
) -> Dict[str, Any]:
    key = sanitize_scope_key(user_identifier)
    scope = _user_scope(tenant_id, user_identifier)
    counts = await store.digest_debug_stats(scope)
    return {
        "user_id": key,
        "tenant_id": tenant_id,
        "scope_type": "user",
        "scope_key": key,
        **counts,
    }


async def get_user_note(
    *, tenant_id: str, user_identifier: str, note_id: int
) -> Dict[str, Any]:
    note = await store.get_note(note_id)
    _assert_user_note(note, tenant_id=tenant_id, user_identifier=user_identifier)
    return _note_to_dict(note)


async def list_user_digests(
    *,
    tenant_id: str,
    user_identifier: str,
    ready_only: Optional[bool] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    scope = _user_scope(tenant_id, user_identifier)
    digests = await store.list_digests(scope, ready_only=ready_only, limit=limit)
    return [_digest_to_dict(d) for d in digests]


async def zoom_user_digest(
    *, tenant_id: str, user_identifier: str, lo: int, hi: int
) -> Dict[str, Any]:
    scope = _user_scope(tenant_id, user_identifier)
    return await zoom_digest(scope, lo, hi)


async def user_wake_preview(
    *, tenant_id: str, user_identifier: str, budget: Optional[int] = None
) -> Dict[str, Any]:
    scope = _user_scope(tenant_id, user_identifier)
    rows = await wake(scope, k=budget)
    return {"rows": rows, "budget": budget}


async def compress_user_memory(
    *, tenant_id: str, user_identifier: str
) -> Dict[str, Any]:
    scope = _user_scope(tenant_id, user_identifier)
    n = await compress_scope(scope)
    return {"compressed": n}
