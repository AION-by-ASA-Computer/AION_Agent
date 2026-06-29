"""REST API for SQL QueryMemory (chat users — JWT / chat-ui secret, not API-key only)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.identity import sanitize_user_id
from src.memory.sql_query_memory import sql_query_memory, sql_query_memory_enabled
from src.memory.sql_query_memory.models import SqlProjectMemberOut, SqlProjectOut

router = APIRouter(prefix="/query-memory", tags=["v1-query-memory"])


class SqlProjectCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    scope_mode: str = "inherit"


class SqlProjectPatch(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=256)
    description: Optional[str] = None


class SqlProjectMemberAdd(BaseModel):
    user_identifier: str = Field(..., min_length=1, max_length=256)


class SqlQueryPatch(BaseModel):
    user_request: Optional[str] = None
    sql_text: Optional[str] = None
    is_verified: Optional[bool] = None


def _tenant() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"


def _chat_user_id(
    auth: ChatAuthIdentity,
    x_aion_user_id: Optional[str] = None,
    body_user_id: Optional[str] = None,
) -> str:
    if auth.via == "chat_token" and auth.identifier:
        return sanitize_user_id(auth.identifier)
    if body_user_id:
        return sanitize_user_id(body_user_id)
    return sanitize_user_id(x_aion_user_id or "default")


def _resolve_profile_slug(profile: Optional[str]) -> Optional[str]:
    if not (profile or "").strip():
        return None
    from src.agent_profile import profile_manager

    p = profile_manager.get_profile(profile.strip())
    if p:
        return p.slug
    return profile.strip().replace(" ", "_").lower()


def _map_project_error(exc: ValueError) -> HTTPException:
    code = str(exc)
    if code == "project_exists":
        return HTTPException(status_code=409, detail="Project slug already exists")
    if code == "not_found":
        return HTTPException(status_code=404, detail="Project not found")
    if code == "forbidden":
        return HTTPException(status_code=403, detail="Not allowed on this project")
    if code == "already_member":
        return HTTPException(status_code=409, detail="User is already a member")
    if code == "cannot_remove_self":
        return HTTPException(status_code=400, detail="Cannot remove yourself from the project")
    return HTTPException(status_code=400, detail=code)


@router.get("/projects")
async def list_projects(
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    profile: Optional[str] = Query(None, description="Profile display name or slug"),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> List[SqlProjectOut]:
    if not sql_query_memory_enabled():
        return []
    uid = _chat_user_id(auth, x_aion_user_id)
    slug = _resolve_profile_slug(profile)
    return await sql_query_memory.list_projects(
        tenant_id=_tenant(), profile_slug=slug, user_id=uid
    )


@router.post("/projects")
async def create_project(
    body: SqlProjectCreate,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    profile: Optional[str] = Query(None),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> SqlProjectOut:
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    uid = _chat_user_id(auth, x_aion_user_id)
    slug = _resolve_profile_slug(profile)
    try:
        return await sql_query_memory.create_project(
            slug=body.slug.strip().lower(),
            display_name=body.display_name,
            tenant_id=_tenant(),
            description=body.description,
            profile_slug=slug,
            scope_mode=body.scope_mode,
            created_by=uid,
        )
    except ValueError as exc:
        raise _map_project_error(exc) from exc


@router.patch("/projects/{project_slug}")
async def patch_project(
    project_slug: str,
    body: SqlProjectPatch,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> SqlProjectOut:
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    uid = _chat_user_id(auth, x_aion_user_id)
    try:
        return await sql_query_memory.update_project(
            slug=project_slug.strip().lower(),
            tenant_id=_tenant(),
            user_id=uid,
            display_name=body.display_name,
            description=body.description,
        )
    except ValueError as exc:
        raise _map_project_error(exc) from exc


@router.get("/projects/{project_slug}/members")
async def list_members(
    project_slug: str,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> List[SqlProjectMemberOut]:
    if not sql_query_memory_enabled():
        return []
    uid = _chat_user_id(auth, x_aion_user_id)
    try:
        return await sql_query_memory.list_project_members(
            slug=project_slug.strip().lower(),
            tenant_id=_tenant(),
            user_id=uid,
        )
    except ValueError as exc:
        raise _map_project_error(exc) from exc


@router.post("/projects/{project_slug}/members")
async def add_member(
    project_slug: str,
    body: SqlProjectMemberAdd,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> SqlProjectMemberOut:
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    uid = _chat_user_id(auth, x_aion_user_id)
    try:
        return await sql_query_memory.add_project_member(
            slug=project_slug.strip().lower(),
            member_identifier=body.user_identifier,
            tenant_id=_tenant(),
            invited_by=uid,
        )
    except ValueError as exc:
        raise _map_project_error(exc) from exc


@router.delete("/projects/{project_slug}/members/{member_identifier}")
async def remove_member(
    project_slug: str,
    member_identifier: str,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    uid = _chat_user_id(auth, x_aion_user_id)
    try:
        ok = await sql_query_memory.remove_project_member(
            slug=project_slug.strip().lower(),
            member_identifier=member_identifier,
            tenant_id=_tenant(),
            actor_user_id=uid,
        )
    except ValueError as exc:
        raise _map_project_error(exc) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"status": "ok"}


@router.get("/queries")
async def list_queries(
    project: str = Query(..., description="Project slug"),
    q: Optional[str] = Query(None),
    verified_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> List[Dict[str, Any]]:
    if not sql_query_memory_enabled():
        return []
    uid = _chat_user_id(auth, x_aion_user_id)
    return await sql_query_memory.list_queries(
        project_slug=project,
        tenant_id=_tenant(),
        user_id=uid,
        q=q,
        verified_only=verified_only,
        limit=limit,
    )


@router.patch("/queries/{entry_id}")
async def patch_query(
    entry_id: int,
    body: SqlQueryPatch,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    uid = _chat_user_id(auth, x_aion_user_id)
    ok, err = await sql_query_memory.update_entry(
        entry_id,
        user_request=body.user_request,
        sql_text=body.sql_text,
        is_verified=body.is_verified,
        user_id=uid,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=err or "Not found")
    return {"status": "ok", "id": entry_id}


@router.delete("/queries/{entry_id}")
async def delete_query(
    entry_id: int,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    uid = _chat_user_id(auth, x_aion_user_id)
    ok, err = await sql_query_memory.delete_entry(entry_id, user_id=uid)
    if not ok:
        raise HTTPException(status_code=404, detail=err or "Not found")
    return {"status": "ok"}


@router.post("/queries/{entry_id}/use")
async def touch_query(
    entry_id: int,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    if not await sql_query_memory.touch_used(entry_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "ok"}
