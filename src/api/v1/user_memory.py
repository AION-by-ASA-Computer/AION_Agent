"""REST API for Mnemos user-scoped memory notes (chat-ui)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.memory.mnemos.scope import default_tenant_id
from src.memory.project_memory_service import NOTE_CATEGORIES
from src.memory.user_memory_service import (
    compress_user_memory,
    create_user_note,
    delete_user_note,
    get_user_note,
    list_user_digests,
    list_user_notes,
    search_user_notes,
    update_user_note,
    user_memory_status,
    user_wake_preview,
    zoom_user_digest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user-memory", tags=["user-memory"])


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
    content: str = Field(..., min_length=1, max_length=500)
    category: str = Field(default="fact")
    importance: int = Field(default=3, ge=1, le=5)


class UpdateNoteBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=500)
    category: Optional[str] = None
    importance: Optional[int] = Field(default=None, ge=1, le=5)


class DeleteNoteBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    note_id: int = Field(..., ge=1)


@router.get("/status")
async def get_status(
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    try:
        return await user_memory_status(
            tenant_id=tenant, user_identifier=auth.identifier
        )
    except Exception as exc:
        logger.warning("user memory status failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/notes", response_model=List[NoteOut])
async def get_notes(
    category: Optional[str] = Query(None),
    status: str = Query("active"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> List[Dict[str, Any]]:
    if category and category not in NOTE_CATEGORIES:
        raise HTTPException(status_code=400, detail="invalid category")
    tenant = default_tenant_id()
    status_filter = "" if status == "all" else status
    return await list_user_notes(
        tenant_id=tenant,
        user_identifier=auth.identifier,
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
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> List[Dict[str, Any]]:
    tenant = default_tenant_id()
    return await search_user_notes(
        tenant_id=tenant,
        user_identifier=auth.identifier,
        query=q,
        limit=limit,
        mode=mode,
    )


@router.get("/notes/{note_id}", response_model=NoteOut)
async def get_note(
    note_id: int,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    try:
        return await get_user_note(
            tenant_id=tenant,
            user_identifier=auth.identifier,
            note_id=note_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/digests", response_model=List[DigestOut])
async def get_digests(
    ready_only: Optional[bool] = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> List[Dict[str, Any]]:
    tenant = default_tenant_id()
    return await list_user_digests(
        tenant_id=tenant,
        user_identifier=auth.identifier,
        ready_only=ready_only,
        limit=limit,
    )


@router.get("/digests/zoom")
async def get_digest_zoom(
    lo: int = Query(..., ge=0),
    hi: int = Query(..., gt=0),
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    return await zoom_user_digest(
        tenant_id=tenant,
        user_identifier=auth.identifier,
        lo=lo,
        hi=hi,
    )


@router.get("/wake-preview")
async def get_wake_preview(
    budget: Optional[int] = Query(None, ge=1, le=100),
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    return await user_wake_preview(
        tenant_id=tenant,
        user_identifier=auth.identifier,
        budget=budget,
    )


@router.post("/compress")
async def post_compress(
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    try:
        return await compress_user_memory(
            tenant_id=tenant, user_identifier=auth.identifier
        )
    except Exception as exc:
        logger.warning("user memory compress failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/notes", response_model=NoteOut)
async def post_note(
    body: CreateNoteBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    if body.category not in NOTE_CATEGORIES:
        raise HTTPException(status_code=400, detail="invalid category")
    tenant = default_tenant_id()
    try:
        return await create_user_note(
            tenant_id=tenant,
            user_identifier=auth.identifier,
            content=body.content,
            category=body.category,
            importance=body.importance,
            session_id=body.session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/notes/{note_id}", response_model=NoteOut)
async def patch_note(
    note_id: int,
    body: UpdateNoteBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    tenant = default_tenant_id()
    try:
        return await update_user_note(
            tenant_id=tenant,
            user_identifier=auth.identifier,
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
    tenant = default_tenant_id()
    ok = await delete_user_note(
        tenant_id=tenant,
        user_identifier=auth.identifier,
        note_id=note_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="note_not_found")
    return {"ok": True, "note_id": note_id}
