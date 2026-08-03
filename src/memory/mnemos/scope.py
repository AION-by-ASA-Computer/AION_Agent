"""Scope resolution for Mnemos (server-enforced, not LLM-controlled)."""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select

from src.data.engine import get_async_session_maker
from src.data.models import Project

from .types import MemoryScope, SCOPE_TYPES

_SLUG_RE = re.compile(r"^[a-z0-9_\-]+$")


def sanitize_scope_key(key: str) -> str:
    s = re.sub(r"[^a-z0-9_\-]", "_", (key or "default").lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:256] or "default"


def sanitize_project_slug(slug: str) -> str:
    return sanitize_scope_key(slug)


def default_tenant_id() -> str:
    import os

    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"


def user_scope(tenant_id: str, user_id: str) -> MemoryScope:
    return MemoryScope(
        tenant_id=tenant_id,
        scope_type="user",
        scope_key=sanitize_scope_key(user_id or "default"),
    )


def project_scope(tenant_id: str, project_slug: str) -> MemoryScope:
    return MemoryScope(
        tenant_id=tenant_id,
        scope_type="project",
        scope_key=sanitize_project_slug(project_slug),
    )


def global_scope(tenant_id: str) -> MemoryScope:
    return MemoryScope(
        tenant_id=tenant_id,
        scope_type="global",
        scope_key="global",
    )


def parse_scope_name(scope: str) -> str:
    s = (scope or "user").strip().lower()
    if s not in SCOPE_TYPES:
        return "user"
    return s


async def project_exists(tenant_id: str, project_slug: str) -> bool:
    slug = sanitize_project_slug(project_slug)
    async with get_async_session_maker()() as session:
        row = (
            await session.execute(
                select(Project.id).where(
                    Project.tenant_id == tenant_id,
                    Project.slug == slug,
                )
            )
        ).scalar_one_or_none()
        return row is not None


def resolve_scopes_for_wake(
    *,
    tenant_id: str,
    user_id: str,
    active_project_slug: Optional[str] = None,
    include_global: bool = False,
) -> list[MemoryScope]:
    scopes: list[MemoryScope] = [user_scope(tenant_id, user_id)]
    if active_project_slug and sanitize_project_slug(active_project_slug) != "default":
        scopes.append(project_scope(tenant_id, active_project_slug))
    if include_global:
        scopes.append(global_scope(tenant_id))
    return scopes


def resolve_scope_for_write(
    *,
    tenant_id: str,
    user_id: str,
    scope_name: str,
    active_project_slug: Optional[str] = None,
) -> MemoryScope:
    parsed = parse_scope_name(scope_name)
    if parsed == "project":
        if not active_project_slug:
            return user_scope(tenant_id, user_id)
        return project_scope(tenant_id, active_project_slug)
    if parsed == "global":
        return global_scope(tenant_id)
    return user_scope(tenant_id, user_id)
