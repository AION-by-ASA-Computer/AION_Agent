"""
Admin REST API for Mnemos LTM.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.memory.ltm_audit import append_ltm_audit
from src.memory.mnemos.compress import compress_scope
from src.memory.mnemos.scope import (
    default_tenant_id,
    global_scope,
    project_scope,
    user_scope,
)
from src.memory.mnemos import store
from src.memory.mnemos.zoom import zoom as zoom_digest

logger = logging.getLogger("aion.api.ltm_admin")

router = APIRouter(prefix="/ltm", tags=["ltm"])


class CompressBody(BaseModel):
    scope_type: str = Field(..., pattern="^(user|project|global)$")
    scope_key: str = Field(..., min_length=1)
    tenant_id: str = Field(default="default")


def _scope(tenant_id: str, scope_type: str, scope_key: str):
    if scope_type == "project":
        return project_scope(tenant_id, scope_key)
    if scope_type == "global":
        return global_scope(tenant_id)
    return user_scope(tenant_id, scope_key)


@router.get("/status")
async def ltm_status(
    scope_type: str = Query("user"),
    scope_key: str = Query("default"),
    tenant_id: str = Query("default"),
) -> Dict[str, Any]:
    scope = _scope(tenant_id, scope_type, scope_key)
    return await store.note_counts(scope)


@router.get("/notes")
async def ltm_notes(
    scope_type: str = Query(...),
    scope_key: str = Query(...),
    tenant_id: str = Query("default"),
    category: Optional[str] = Query(None),
    status: str = Query("active"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[Dict[str, Any]]:
    scope = _scope(tenant_id, scope_type, scope_key)
    notes = await store.list_notes(
        scope, category=category, status=status, limit=limit, offset=offset
    )
    return [
        {
            "id": n.id,
            "seq": n.seq,
            "content": n.content,
            "category": n.category,
            "importance": n.importance,
            "status": n.status,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notes
    ]


@router.get("/notes/search")
async def ltm_search(
    q: str = Query(..., min_length=1),
    scope_type: str = Query(...),
    scope_key: str = Query(...),
    tenant_id: str = Query("default"),
    mode: str = Query("current"),
    limit: int = Query(20, ge=1, le=100),
) -> List[Dict[str, Any]]:
    scope = _scope(tenant_id, scope_type, scope_key)
    notes = await store.fts_search(scope, q, limit=limit, mode=mode)
    return [
        {"id": n.id, "seq": n.seq, "content": n.content, "status": n.status}
        for n, _ in notes
    ]


@router.get("/digests/zoom")
async def ltm_zoom(
    scope_type: str = Query(...),
    scope_key: str = Query(...),
    lo: int = Query(..., ge=0),
    hi: int = Query(..., gt=0),
    tenant_id: str = Query("default"),
) -> Dict[str, Any]:
    scope = _scope(tenant_id, scope_type, scope_key)
    return await zoom_digest(scope, lo, hi)


@router.post("/compress")
async def ltm_compress(body: CompressBody) -> Dict[str, Any]:
    scope = _scope(body.tenant_id, body.scope_type, body.scope_key)
    n = await compress_scope(scope)
    append_ltm_audit(
        {
            "action": "compress",
            "scope_type": body.scope_type,
            "scope_key": body.scope_key,
            "compressed": n,
        }
    )
    return {"compressed": n}
