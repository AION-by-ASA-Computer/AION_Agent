"""Admin API for SQL QueryMemory tenant settings and cross-user management."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.auth_login import require_admin_role
from src.memory.sql_query_memory import sql_query_memory, sql_query_memory_enabled
from src.memory.sql_query_memory.models import (
    SqlProjectOut,
    AdminProjectMemberOut,
    AdminProjectOut,
)

router = APIRouter(prefix="/query-memory", tags=["admin-query-memory"])


class AdminSqlProjectCreate(BaseModel):
    slug: str
    display_name: str
    description: Optional[str] = None
    profile_slug: Optional[str] = None
    scope_mode: str = "inherit"


class AdminProjectPatch(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    profile_slug: Optional[str] = None
    scope_mode: Optional[str] = None


class AdminProjectMemberAdd(BaseModel):
    user_identifier: str = Field(..., min_length=1, max_length=256)
    role: str = "member"


def _tenant() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"


@router.get("/projects")
async def admin_list_projects(
    _admin=Depends(require_admin_role),
    profile: Optional[str] = Query(None),
) -> List[AdminProjectOut]:
    if not sql_query_memory_enabled():
        return []
    projects = await sql_query_memory.admin_list_projects_with_members(tenant_id=_tenant())
    if profile:
        p_slug = profile.strip().lower()
        projects = [p for p in projects if p.profile_slug == p_slug]
    return projects


@router.post("/projects")
async def admin_create_project(
    body: AdminSqlProjectCreate,
    _admin=Depends(require_admin_role),
) -> SqlProjectOut:
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    return await sql_query_memory.create_project(
        slug=body.slug.strip().lower(),
        display_name=body.display_name,
        tenant_id=_tenant(),
        description=body.description,
        profile_slug=body.profile_slug,
        scope_mode=body.scope_mode,
        created_by="admin",
    )


@router.patch("/projects/{project_slug}")
async def admin_update_project(
    project_slug: str,
    body: AdminProjectPatch,
    _admin=Depends(require_admin_role),
) -> AdminProjectOut:
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    try:
        return await sql_query_memory.admin_update_project(
            slug=project_slug.strip().lower(),
            tenant_id=_tenant(),
            display_name=body.display_name,
            description=body.description,
            profile_slug=body.profile_slug,
            scope_mode=body.scope_mode,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "not_found":
            raise HTTPException(status_code=404, detail="Project not found")
        raise HTTPException(status_code=400, detail=code)


@router.delete("/projects/{project_slug}")
async def admin_delete_project(
    project_slug: str,
    _admin=Depends(require_admin_role),
):
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    ok = await sql_query_memory.delete_project(
        slug=project_slug.strip().lower(),
        tenant_id=_tenant(),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "ok"}


@router.post("/projects/{project_slug}/members")
async def admin_add_project_member(
    project_slug: str,
    body: AdminProjectMemberAdd,
    _admin=Depends(require_admin_role),
) -> AdminProjectMemberOut:
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    try:
        return await sql_query_memory.admin_add_project_member(
            slug=project_slug.strip().lower(),
            member_identifier=body.user_identifier,
            tenant_id=_tenant(),
            role=body.role,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "not_found":
            raise HTTPException(status_code=404, detail="Project not found")
        if code == "already_member":
            raise HTTPException(status_code=409, detail="User is already a member of this project")
        raise HTTPException(status_code=400, detail=code)


@router.delete("/projects/{project_slug}/members/{member_identifier}")
async def admin_remove_project_member(
    project_slug: str,
    member_identifier: str,
    _admin=Depends(require_admin_role),
):
    if not sql_query_memory_enabled():
        raise HTTPException(status_code=503, detail="SQL QueryMemory disabled")
    try:
        ok = await sql_query_memory.admin_remove_project_member(
            slug=project_slug.strip().lower(),
            member_identifier=member_identifier,
            tenant_id=_tenant(),
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Member not found")
        return {"status": "ok"}
    except ValueError as exc:
        code = str(exc)
        if code == "not_found":
            raise HTTPException(status_code=404, detail="Project not found")
        raise HTTPException(status_code=400, detail=code)



@router.get("/queries")
async def admin_list_queries(
    project: str = Query(...),
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    _admin=Depends(require_admin_role),
) -> List[Dict[str, Any]]:
    if not sql_query_memory_enabled():
        return []
    return await sql_query_memory.list_queries(
        project_slug=project,
        tenant_id=_tenant(),
        user_id="default",
        q=q,
        limit=limit,
    )


@router.post("/queries/{entry_id}/verify")
async def admin_verify_query(entry_id: int, _admin=Depends(require_admin_role)):
    ok, err = await sql_query_memory.update_entry(entry_id, is_verified=True)
    if not ok:
        raise HTTPException(status_code=404, detail=err or "Not found")
    return {"status": "ok"}


@router.delete("/queries/{entry_id}")
async def admin_delete_query(entry_id: int, _admin=Depends(require_admin_role)):
    ok, err = await sql_query_memory.delete_entry(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail=err or "Not found")
    return {"status": "ok"}
