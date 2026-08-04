"""REST API for Mnemos project memory notes (chat-ui)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.memory.mnemos.scope import default_tenant_id, sanitize_project_slug
from src.memory.project_memory_service import (
    NOTE_CATEGORIES,
    compress_project_memory,
    create_project_note,
    delete_project_note,
    get_project_note,
    list_project_digests,
    list_project_notes,
    project_memory_status,
    project_wake_preview,
    search_project_notes,
    update_project_note,
    zoom_project_digest,
)
from src.memory.sql_query_memory import sql_query_memory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project-memory", tags=["project-memory"])


class NoteOut(BaseModel):
    id: int
    seq: int
    content: str
    category: str
    importance: int
    status: str
    created_at: Optional[str] = None
    superseded_by: Optional[int] = None
    source_session_id: Optional[str] = None


class DigestOut(BaseModel):
    lo: int
    hi: int
    level: int
    ready: bool
    summary: str
    updated_at: Optional[str] = None


class CreateNoteBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    project: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=500)
    category: str = Field(default="fact")
    importance: int = Field(default=3, ge=1, le=5)


class UpdateNoteBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    project: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=500)
    category: Optional[str] = None
    importance: Optional[int] = Field(default=None, ge=1, le=5)


class DeleteNoteBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    note_id: int = Field(..., ge=1)


async def _assert_project_access(
    project_slug: str,
    auth: ChatAuthIdentity,
) -> str:
    slug = sanitize_project_slug(project_slug)
    err = await sql_query_memory.check_user_project_access(
        project_slug=slug,
        tenant_id=default_tenant_id(),
        user_id=auth.identifier,
    )
    if err:
        raise HTTPException(status_code=403, detail=err)
    return slug


async def require_project_access(
    project: str = Query(...),
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> str:
    return await _assert_project_access(project, auth)


@router.get("/status")
async def get_status(
    slug: str = Depends(require_project_access),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    try:
        return await project_memory_status(tenant_id=tenant, project_slug=slug)
    except Exception as exc:
        logger.warning("project memory status failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/notes", response_model=List[NoteOut])
async def get_notes(
    category: Optional[str] = Query(None),
    status: str = Query("active"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    slug: str = Depends(require_project_access),
) -> List[Dict[str, Any]]:
    if category and category not in NOTE_CATEGORIES:
        raise HTTPException(status_code=400, detail="invalid category")
    tenant = default_tenant_id()
    status_filter = "" if status == "all" else status
    return await list_project_notes(
        tenant_id=tenant,
        project_slug=slug,
        category=category,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/notes/search", response_model=List[NoteOut])
async def search_notes(
    q: str = Query(..., min_length=1),
    mode: str = Query("current"),
    limit: int = Query(20, ge=1, le=100),
    slug: str = Depends(require_project_access),
) -> List[Dict[str, Any]]:
    tenant = default_tenant_id()
    return await search_project_notes(
        tenant_id=tenant,
        project_slug=slug,
        query=q,
        limit=limit,
        mode=mode,
    )


@router.get("/notes/{note_id}", response_model=NoteOut)
async def get_note(
    note_id: int,
    slug: str = Depends(require_project_access),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    try:
        return await get_project_note(
            tenant_id=tenant, project_slug=slug, note_id=note_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/digests", response_model=List[DigestOut])
async def get_digests(
    ready_only: Optional[bool] = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    slug: str = Depends(require_project_access),
) -> List[Dict[str, Any]]:
    tenant = default_tenant_id()
    return await list_project_digests(
        tenant_id=tenant,
        project_slug=slug,
        ready_only=ready_only,
        limit=limit,
    )


@router.get("/digests/zoom")
async def get_digest_zoom(
    lo: int = Query(..., ge=0),
    hi: int = Query(..., gt=0),
    slug: str = Depends(require_project_access),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    return await zoom_project_digest(
        tenant_id=tenant, project_slug=slug, lo=lo, hi=hi
    )


@router.get("/wake-preview")
async def get_wake_preview(
    budget: Optional[int] = Query(None, ge=1, le=100),
    slug: str = Depends(require_project_access),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    return await project_wake_preview(
        tenant_id=tenant, project_slug=slug, budget=budget
    )


@router.post("/compress")
async def post_compress(
    slug: str = Depends(require_project_access),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    try:
        return await compress_project_memory(
            tenant_id=tenant, project_slug=slug
        )
    except Exception as exc:
        logger.warning("project memory compress failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/notes", response_model=NoteOut)
async def post_note(
    body: CreateNoteBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    slug = await _assert_project_access(body.project, auth)
    if body.category not in NOTE_CATEGORIES:
        raise HTTPException(status_code=400, detail="invalid category")
    tenant = default_tenant_id()
    try:
        out = await create_project_note(
            tenant_id=tenant,
            user_id=auth.identifier,
            project_slug=slug,
            content=body.content,
            category=body.category,
            importance=body.importance,
            session_id=body.session_id,
        )
        return out
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/notes/{note_id}", response_model=NoteOut)
async def patch_note(
    note_id: int,
    body: UpdateNoteBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    slug = await _assert_project_access(body.project, auth)
    tenant = default_tenant_id()
    try:
        return await update_project_note(
            tenant_id=tenant,
            user_id=auth.identifier,
            project_slug=slug,
            note_id=note_id,
            content=body.content,
            category=body.category,
            importance=body.importance,
            session_id=body.session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/notes/{note_id}")
async def remove_note(
    note_id: int,
    body: DeleteNoteBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    from src.memory.mnemos import store

    note = await store.get_note(note_id)
    if not note or note.scope_type != "project":
        raise HTTPException(status_code=404, detail="note_not_found")
    slug = await _assert_project_access(note.scope_key, auth)
    tenant = default_tenant_id()
    ok = await delete_project_note(
        note_id, tenant_id=tenant, project_slug=slug
    )
    if not ok:
        raise HTTPException(status_code=404, detail="note_not_found")
    return {"ok": True, "note_id": note_id}
