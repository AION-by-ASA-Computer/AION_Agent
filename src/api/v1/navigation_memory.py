"""REST API for MemPalace navigation memory (per SQL QueryMemory project)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.memory.navigation_memory_service import (
    delete_drawer,
    get_drawer,
    list_drawers,
    list_wings,
    navigation_status,
    prune_legacy_wings,
    search_drawers,
    upsert_drawer,
)
from src.memory.project_memory_scope import sanitize_project_slug

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/navigation-memory", tags=["navigation-memory"])


class NavigationDrawerOut(BaseModel):
    id: Optional[str] = None
    drawer_id: Optional[str] = None
    wing: Optional[str] = None
    room: Optional[str] = None
    preview: Optional[str] = None
    content: Optional[str] = None
    text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class PruneLegacyBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    dry_run: bool = True
    include_agent_procedures: bool = False


class DeleteDrawerBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    drawer_id: str = Field(..., min_length=1)


class UpsertDrawerBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    project: str = Field(..., min_length=1)
    room: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=500)
    drawer_id: Optional[str] = Field(None, description="If set, replace this drawer")


@router.get("/status")
async def get_status(
    project: str = Query(..., description="SQL QueryMemory project slug"),
    session_id: str = Query(..., description="Chat session for MCP MemPalace pool"),
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    slug = sanitize_project_slug(project)
    try:
        all_drawers = await list_drawers(session_id, project_slug=slug, limit=200)
        count = len(all_drawers)
    except Exception as exc:
        logger.warning("navigation memory status failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    st = navigation_status(project_slug=slug, drawer_count=count)
    st["sample_drawers"] = all_drawers[:3]
    try:
        st["wings"] = await list_wings(session_id)
    except Exception:
        st["wings"] = {}
    return st


@router.get("/drawers/detail")
async def get_drawer_detail(
    drawer_id: str = Query(..., min_length=1),
    session_id: str = Query(...),
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> NavigationDrawerOut:
    try:
        row = await get_drawer(session_id, drawer_id=drawer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return NavigationDrawerOut(**row)


@router.get("/drawers")
async def get_drawers(
    project: str = Query(...),
    session_id: str = Query(...),
    wing: Optional[str] = Query(None),
    room: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    slug = sanitize_project_slug(project)
    try:
        items: List[Dict[str, Any]] = await list_drawers(
            session_id, project_slug=slug, wing=wing, room=room, limit=limit
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "project_slug": slug,
        "wing": wing or navigation_status(project_slug=slug)["wing"],
        "room": room,
        "drawers": items,
    }


@router.get("/search")
async def search(
    project: str = Query(...),
    session_id: str = Query(...),
    q: str = Query(..., min_length=1),
    wing: Optional[str] = Query(None),
    room: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    slug = sanitize_project_slug(project)
    try:
        hits = await search_drawers(
            session_id, project_slug=slug, wing=wing, query=q, room=room, limit=limit
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"project_slug": slug, "query": q, "results": hits}


@router.post("/drawers/upsert")
async def post_upsert_drawer(
    body: UpsertDrawerBody,
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    slug = sanitize_project_slug(body.project)
    try:
        result = await upsert_drawer(
            body.session_id,
            project_slug=slug,
            room=body.room,
            content=body.content,
            drawer_id=body.drawer_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "project_slug": slug, "result": result}


@router.post("/drawers/delete")
async def post_delete_drawer(
    body: DeleteDrawerBody,
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    try:
        result = await delete_drawer(body.session_id, drawer_id=body.drawer_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "result": result}


@router.post("/prune-legacy")
async def post_prune_legacy(
    body: PruneLegacyBody,
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    try:
        pruned, skipped = await prune_legacy_wings(
            body.session_id,
            dry_run=body.dry_run,
            include_agent_procedures=body.include_agent_procedures,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "dry_run": body.dry_run,
        "pruned_wings": pruned,
        "kept_wings": skipped,
    }
