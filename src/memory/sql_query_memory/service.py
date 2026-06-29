"""SQL QueryMemory: persistent validated SELECT cache with hybrid retrieval."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import selectinload

from src.data.engine import get_async_session_maker
from src.data.models import (
    CachedSqlQuery,
    SqlQueryProject,
    SqlQueryProjectMember,
    TenantQueryMemorySettings,
)
from src.identity import sanitize_user_id

from .embedding import (
    bytes_to_embedding,
    cosine_similarity,
    embedding_to_bytes,
    get_embedding,
)
from .fingerprint import (
    build_save_metadata,
    normalize_request_intent,
    normalize_request_text,
    normalize_sql,
    sql_fingerprint,
)
from .models import (
    SqlProjectMemberOut,
    SqlProjectOut,
    SqlQueryHit,
    TenantSqlQmSettingsOut,
    AdminProjectMemberOut,
    AdminProjectOut,
)
from .scope import (
    ScopeContext,
    datasource_key_from_env,
    default_tenant_id,
    effective_scope,
    env_default_scope,
    user_scope_key,
)

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def sql_query_memory_enabled() -> bool:
    return os.getenv("AION_SQL_QM_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class SqlQueryMemoryService:
    def __init__(self) -> None:
        self.session_maker = get_async_session_maker()

    async def get_tenant_settings(
        self, tenant_id: Optional[str] = None
    ) -> TenantSqlQmSettingsOut:
        tid = tenant_id or default_tenant_id()
        async with self.session_maker() as session:
            row = await session.get(TenantQueryMemorySettings, tid)
            if not row:
                return TenantSqlQmSettingsOut(
                    tenant_id=tid,
                    sql_default_scope=env_default_scope(),
                    sql_auto_learn=False,
                    sql_search_before_run=True,
                )
            return TenantSqlQmSettingsOut(
                tenant_id=tid,
                sql_default_scope=row.sql_default_scope,
                sql_auto_learn=bool(row.sql_auto_learn),
                sql_search_before_run=bool(row.sql_search_before_run),
            )

    async def patch_tenant_settings(
        self, patch: Dict[str, Any], tenant_id: Optional[str] = None
    ) -> TenantSqlQmSettingsOut:
        tid = tenant_id or default_tenant_id()
        async with self.session_maker() as session:
            row = await session.get(TenantQueryMemorySettings, tid)
            if not row:
                row = TenantQueryMemorySettings(tenant_id=tid)
                session.add(row)
            if "sql_default_scope" in patch and patch["sql_default_scope"]:
                row.sql_default_scope = patch["sql_default_scope"]
            if "sql_auto_learn" in patch and patch["sql_auto_learn"] is not None:
                row.sql_auto_learn = bool(patch["sql_auto_learn"])
            if (
                "sql_search_before_run" in patch
                and patch["sql_search_before_run"] is not None
            ):
                row.sql_search_before_run = bool(patch["sql_search_before_run"])
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
        return await self.get_tenant_settings(tid)

    async def ensure_project(
        self,
        *,
        project_slug: str,
        tenant_id: Optional[str] = None,
        profile_slug: Optional[str] = None,
        display_name: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> SqlQueryProject:
        tid = tenant_id or default_tenant_id()
        slug = (project_slug or "default").strip().lower()
        ds = datasource_key_from_env(profile_slug)
        async with self.session_maker() as session:
            q = select(SqlQueryProject).where(
                SqlQueryProject.tenant_id == tid,
                SqlQueryProject.slug == slug,
            )
            row = (await session.execute(q)).scalars().first()
            if row:
                return row
            row = SqlQueryProject(
                tenant_id=tid,
                slug=slug,
                display_name=display_name or slug.replace("_", " ").title(),
                datasource_key=ds,
                profile_slug=profile_slug,
                scope_mode="inherit",
                created_by=created_by,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_project_by_slug(
        self, project_slug: str, tenant_id: Optional[str] = None
    ) -> Optional[SqlQueryProject]:
        tid = tenant_id or default_tenant_id()
        async with self.session_maker() as session:
            q = select(SqlQueryProject).where(
                SqlQueryProject.tenant_id == tid,
                SqlQueryProject.slug == project_slug.strip().lower(),
            )
            return (await session.execute(q)).scalars().first()

    async def _member_count(self, session, project_id: int) -> int:
        q = (
            select(func.count())
            .select_from(SqlQueryProjectMember)
            .where(SqlQueryProjectMember.project_id == project_id)
        )
        return int((await session.execute(q)).scalar() or 0)

    async def _user_role_on_project(
        self, session, project_id: int, user_id: str
    ) -> Optional[str]:
        uid = sanitize_user_id(user_id)
        q = select(SqlQueryProjectMember).where(
            SqlQueryProjectMember.project_id == project_id,
            SqlQueryProjectMember.user_identifier == uid,
        )
        row = (await session.execute(q)).scalars().first()
        return row.role if row else None

    async def _bootstrap_owner_if_needed(
        self, session, project: SqlQueryProject, user_id: str
    ) -> None:
        if await self._member_count(session, project.id) > 0:
            return
        owner = sanitize_user_id(project.created_by or user_id)
        session.add(
            SqlQueryProjectMember(
                project_id=project.id,
                user_identifier=owner,
                role="owner",
                invited_by=owner,
            )
        )
        await session.flush()

    async def _can_access_project(
        self, session, project: SqlQueryProject, user_id: str
    ) -> tuple[bool, Optional[str]]:
        uid = sanitize_user_id(user_id)
        role = await self._user_role_on_project(session, project.id, uid)
        if role:
            return True, role
        if project.slug == "default":
            # Auto-register as member so they are explicitly in the default project
            try:
                session.add(
                    SqlQueryProjectMember(
                        project_id=project.id,
                        user_identifier=uid,
                        role="member",
                        invited_by="system",
                    )
                )
                await session.flush()
            except Exception:
                pass
            return True, "member"
        mc = await self._member_count(session, project.id)
        if mc == 0:
            if project.created_by in (None, "", uid):
                await self._bootstrap_owner_if_needed(session, project, uid)
                return True, "owner"
            return (
                project.created_by == uid,
                "owner" if project.created_by == uid else None,
            )
        return False, None

    async def check_user_project_access(
        self,
        *,
        project_slug: str,
        tenant_id: Optional[str] = None,
        user_id: str = "default",
    ) -> Optional[str]:
        """Return error message if user cannot access project; None if OK."""
        tid = tenant_id or default_tenant_id()
        slug = (project_slug or "").strip().lower()
        if not slug:
            return "No SQL QueryMemory project selected."
        project = await self.get_project_by_slug(slug, tenant_id=tid)
        if not project:
            return f"SQL QueryMemory project '{slug}' does not exist."
        async with self.session_maker() as session:
            ok, _role = await self._can_access_project(session, project, user_id)
            if not ok:
                return (
                    f"Access denied to SQL QueryMemory project '{slug}'. "
                    "Ask a project owner to invite you or select another project in chat-ui."
                )
        return None

    async def _resolve_project_for_user(
        self,
        *,
        project_slug: str,
        tenant_id: Optional[str] = None,
        user_id: str = "default",
        profile_slug: Optional[str] = None,
        allow_create: bool = False,
    ) -> Optional[SqlQueryProject]:
        tid = tenant_id or default_tenant_id()
        slug = (project_slug or "").strip().lower()
        if not slug:
            return None
        project = await self.get_project_by_slug(slug, tenant_id=tid)
        if not project:
            if not allow_create:
                return None
            project = await self.ensure_project(
                project_slug=slug,
                tenant_id=tid,
                profile_slug=profile_slug,
                created_by=user_id,
            )
        async with self.session_maker() as session:
            ok, _role = await self._can_access_project(session, project, user_id)
            if not ok:
                return None
        return project

    async def get_active_project_for_user(
        self,
        *,
        project_slug: str,
        tenant_id: Optional[str] = None,
        user_id: str = "default",
    ) -> Optional[SqlProjectOut]:
        tid = tenant_id or default_tenant_id()
        project = await self._resolve_project_for_user(
            project_slug=project_slug,
            tenant_id=tid,
            user_id=user_id,
            allow_create=False,
        )
        if not project:
            return None
        async with self.session_maker() as session:
            ok, role = await self._can_access_project(session, project, user_id)
            if not ok:
                return None
            return SqlProjectOut(
                id=project.id,
                slug=project.slug,
                display_name=project.display_name,
                description=project.description,
                datasource_key=project.datasource_key,
                profile_slug=project.profile_slug,
                scope_mode=project.scope_mode,
                role=role,
            )

    async def list_projects(
        self,
        *,
        tenant_id: Optional[str] = None,
        profile_slug: Optional[str] = None,
        user_id: str = "default",
    ) -> List[SqlProjectOut]:
        """
        List projects the user can access (membership / owner).

        ``profile_slug`` is used only to sort matching projects first — it does not
        hide projects bound to another profile (e.g. Asset Manager ``aion_am``).
        """
        tid = tenant_id or default_tenant_id()
        uid = sanitize_user_id(user_id)
        async with self.session_maker() as session:
            q = select(SqlQueryProject).where(SqlQueryProject.tenant_id == tid)
            rows = (
                (await session.execute(q.order_by(SqlQueryProject.slug)))
                .scalars()
                .all()
            )
            out: List[SqlProjectOut] = []
            for r in rows:
                ok, role = await self._can_access_project(session, r, uid)
                if not ok:
                    continue
                out.append(
                    SqlProjectOut(
                        id=r.id,
                        slug=r.slug,
                        display_name=r.display_name,
                        description=r.description,
                        datasource_key=r.datasource_key,
                        profile_slug=r.profile_slug,
                        scope_mode=r.scope_mode,
                        role=role,
                    )
                )
            await session.commit()
            if profile_slug:
                ps = profile_slug.strip().lower()

                def _sort_key(p: SqlProjectOut) -> tuple:
                    if (p.profile_slug or "").lower() == ps:
                        return (0, p.slug)
                    if p.profile_slug is None:
                        return (1, p.slug)
                    return (2, p.slug)

                out.sort(key=_sort_key)
            return out

    async def admin_list_projects_with_members(
        self,
        *,
        tenant_id: Optional[str] = None,
    ) -> List[AdminProjectOut]:
        tid = tenant_id or default_tenant_id()
        async with self.session_maker() as session:
            q = (
                select(SqlQueryProject)
                .where(SqlQueryProject.tenant_id == tid)
                .options(selectinload(SqlQueryProject.members))
            )
            rows = (
                (await session.execute(q.order_by(SqlQueryProject.slug)))
                .scalars()
                .all()
            )
            out: List[AdminProjectOut] = []
            for r in rows:
                members_list = [
                    AdminProjectMemberOut(
                        user_identifier=m.user_identifier,
                        role=m.role,
                        invited_by=m.invited_by,
                        created_at=m.created_at,
                    )
                    for m in r.members
                ]
                out.append(
                    AdminProjectOut(
                        id=r.id,
                        tenant_id=r.tenant_id,
                        slug=r.slug,
                        display_name=r.display_name,
                        description=r.description,
                        datasource_key=r.datasource_key,
                        profile_slug=r.profile_slug,
                        scope_mode=r.scope_mode,
                        created_by=r.created_by,
                        created_at=r.created_at,
                        members=members_list,
                    )
                )
            return out

    async def admin_update_project(
        self,
        *,
        slug: str,
        tenant_id: Optional[str] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        profile_slug: Optional[str] = None,
        scope_mode: Optional[str] = None,
    ) -> AdminProjectOut:
        tid = tenant_id or default_tenant_id()
        project = await self.get_project_by_slug(slug, tenant_id=tid)
        if not project:
            raise ValueError("not_found")
        ds = datasource_key_from_env(profile_slug) if profile_slug is not None else None
        async with self.session_maker() as session:
            row = await session.get(SqlQueryProject, project.id)
            if not row:
                raise ValueError("not_found")
            if display_name is not None and display_name.strip():
                row.display_name = display_name.strip()
            if description is not None:
                row.description = description.strip() or None
            if profile_slug is not None:
                row.profile_slug = profile_slug.strip() or None
                if ds is not None:
                    row.datasource_key = ds
            if scope_mode is not None:
                row.scope_mode = (
                    scope_mode
                    if scope_mode in ("inherit", "shared", "per_user")
                    else "inherit"
                )
            await session.commit()

            # Fetch with eager loaded members
            q = (
                select(SqlQueryProject)
                .where(SqlQueryProject.id == row.id)
                .options(selectinload(SqlQueryProject.members))
            )
            updated_row = (await session.execute(q)).scalars().first()

            members_list = [
                AdminProjectMemberOut(
                    user_identifier=m.user_identifier,
                    role=m.role,
                    invited_by=m.invited_by,
                    created_at=m.created_at,
                )
                for m in updated_row.members
            ]
            return AdminProjectOut(
                id=updated_row.id,
                tenant_id=updated_row.tenant_id,
                slug=updated_row.slug,
                display_name=updated_row.display_name,
                description=updated_row.description,
                datasource_key=updated_row.datasource_key,
                profile_slug=updated_row.profile_slug,
                scope_mode=updated_row.scope_mode,
                created_by=updated_row.created_by,
                created_at=updated_row.created_at,
                members=members_list,
            )

    async def admin_add_project_member(
        self,
        *,
        slug: str,
        member_identifier: str,
        tenant_id: Optional[str] = None,
        role: str = "member",
    ) -> AdminProjectMemberOut:
        tid = tenant_id or default_tenant_id()
        project = await self.get_project_by_slug(slug, tenant_id=tid)
        if not project:
            raise ValueError("not_found")
        new_uid = sanitize_user_id(member_identifier)
        async with self.session_maker() as session:
            existing = await self._user_role_on_project(session, project.id, new_uid)
            if existing:
                raise ValueError("already_member")
            row = SqlQueryProjectMember(
                project_id=project.id,
                user_identifier=new_uid,
                role=role if role in ("owner", "member") else "member",
                invited_by="admin",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return AdminProjectMemberOut(
                user_identifier=row.user_identifier,
                role=row.role,
                invited_by=row.invited_by,
                created_at=row.created_at,
            )

    async def admin_remove_project_member(
        self,
        *,
        slug: str,
        member_identifier: str,
        tenant_id: Optional[str] = None,
    ) -> bool:
        tid = tenant_id or default_tenant_id()
        project = await self.get_project_by_slug(slug, tenant_id=tid)
        if not project:
            raise ValueError("not_found")
        target = sanitize_user_id(member_identifier)
        async with self.session_maker() as session:
            res = await session.execute(
                delete(SqlQueryProjectMember).where(
                    SqlQueryProjectMember.project_id == project.id,
                    SqlQueryProjectMember.user_identifier == target,
                )
            )
            await session.commit()
            return res.rowcount > 0

    async def delete_project(self, slug: str, tenant_id: Optional[str] = None) -> bool:
        tid = tenant_id or default_tenant_id()
        project = await self.get_project_by_slug(slug, tenant_id=tid)
        if not project:
            return False
        async with self.session_maker() as session:
            await session.execute(
                delete(SqlQueryProject).where(
                    SqlQueryProject.tenant_id == tid,
                    SqlQueryProject.slug == slug.strip().lower(),
                )
            )
            await session.commit()
            return True

    async def create_project(
        self,
        *,
        slug: str,
        display_name: str,
        tenant_id: Optional[str] = None,
        description: Optional[str] = None,
        profile_slug: Optional[str] = None,
        scope_mode: str = "inherit",
        created_by: Optional[str] = None,
    ) -> SqlProjectOut:
        tid = tenant_id or default_tenant_id()
        norm_slug = (slug or "").strip().lower()
        if await self.get_project_by_slug(norm_slug, tenant_id=tid):
            raise ValueError("project_exists")
        creator = sanitize_user_id(created_by or "default")
        ds = datasource_key_from_env(profile_slug)
        async with self.session_maker() as session:
            row = SqlQueryProject(
                tenant_id=tid,
                slug=norm_slug,
                display_name=display_name.strip(),
                description=description,
                datasource_key=ds,
                profile_slug=profile_slug,
                scope_mode=scope_mode
                if scope_mode in ("inherit", "shared", "per_user")
                else "inherit",
                created_by=creator,
            )
            session.add(row)
            await session.flush()
            session.add(
                SqlQueryProjectMember(
                    project_id=row.id,
                    user_identifier=creator,
                    role="owner",
                    invited_by=creator,
                )
            )
            await session.commit()
            await session.refresh(row)
            return SqlProjectOut(
                id=row.id,
                slug=row.slug,
                display_name=row.display_name,
                description=row.description,
                datasource_key=row.datasource_key,
                profile_slug=row.profile_slug,
                scope_mode=row.scope_mode,
                role="owner",
            )

    async def update_project(
        self,
        *,
        slug: str,
        tenant_id: Optional[str] = None,
        user_id: str,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> SqlProjectOut:
        tid = tenant_id or default_tenant_id()
        project = await self.get_project_by_slug(slug, tenant_id=tid)
        if not project:
            raise ValueError("not_found")
        async with self.session_maker() as session:
            row = await session.get(SqlQueryProject, project.id)
            if not row:
                raise ValueError("not_found")
            ok, role = await self._can_access_project(session, row, user_id)
            if not ok or role not in ("owner", "member"):
                raise ValueError("forbidden")
            if display_name is not None and display_name.strip():
                row.display_name = display_name.strip()
            if description is not None:
                row.description = description.strip() or None
            await session.commit()
            await session.refresh(row)
            return SqlProjectOut(
                id=row.id,
                slug=row.slug,
                display_name=row.display_name,
                description=row.description,
                datasource_key=row.datasource_key,
                profile_slug=row.profile_slug,
                scope_mode=row.scope_mode,
                role=role,
            )

    async def list_project_members(
        self, *, slug: str, tenant_id: Optional[str] = None, user_id: str
    ) -> List[SqlProjectMemberOut]:
        tid = tenant_id or default_tenant_id()
        project = await self.get_project_by_slug(slug, tenant_id=tid)
        if not project:
            raise ValueError("not_found")
        async with self.session_maker() as session:
            ok, _role = await self._can_access_project(session, project, user_id)
            if not ok:
                raise ValueError("forbidden")
            q = select(SqlQueryProjectMember).where(
                SqlQueryProjectMember.project_id == project.id
            )
            rows = (
                (await session.execute(q.order_by(SqlQueryProjectMember.role)))
                .scalars()
                .all()
            )
            return [
                SqlProjectMemberOut(
                    user_identifier=m.user_identifier,
                    role=m.role,
                    invited_by=m.invited_by,
                )
                for m in rows
            ]

    async def add_project_member(
        self,
        *,
        slug: str,
        member_identifier: str,
        tenant_id: Optional[str] = None,
        invited_by: str,
        role: str = "member",
    ) -> SqlProjectMemberOut:
        tid = tenant_id or default_tenant_id()
        project = await self.get_project_by_slug(slug, tenant_id=tid)
        if not project:
            raise ValueError("not_found")
        inviter = sanitize_user_id(invited_by)
        new_uid = sanitize_user_id(member_identifier)
        async with self.session_maker() as session:
            ok, actor_role = await self._can_access_project(session, project, inviter)
            if not ok or actor_role != "owner":
                raise ValueError("forbidden")
            existing = await self._user_role_on_project(session, project.id, new_uid)
            if existing:
                raise ValueError("already_member")
            row = SqlQueryProjectMember(
                project_id=project.id,
                user_identifier=new_uid,
                role=role if role in ("owner", "member") else "member",
                invited_by=inviter,
            )
            session.add(row)
            await session.commit()
            return SqlProjectMemberOut(
                user_identifier=row.user_identifier,
                role=row.role,
                invited_by=row.invited_by,
            )

    async def remove_project_member(
        self,
        *,
        slug: str,
        member_identifier: str,
        tenant_id: Optional[str] = None,
        actor_user_id: str,
    ) -> bool:
        tid = tenant_id or default_tenant_id()
        project = await self.get_project_by_slug(slug, tenant_id=tid)
        if not project:
            raise ValueError("not_found")
        actor = sanitize_user_id(actor_user_id)
        target = sanitize_user_id(member_identifier)
        async with self.session_maker() as session:
            ok, actor_role = await self._can_access_project(session, project, actor)
            if not ok or actor_role != "owner":
                raise ValueError("forbidden")
            if target == actor:
                raise ValueError("cannot_remove_self")
            res = await session.execute(
                delete(SqlQueryProjectMember).where(
                    SqlQueryProjectMember.project_id == project.id,
                    SqlQueryProjectMember.user_identifier == target,
                )
            )
            await session.commit()
            return res.rowcount > 0

    def _scope_for_project(
        self, project: SqlQueryProject, tenant_settings: TenantSqlQmSettingsOut
    ) -> str:
        return effective_scope(project.scope_mode, tenant_settings.sql_default_scope)

    async def _visible_scope_keys(
        self, ctx: ScopeContext, project: SqlQueryProject
    ) -> List[str]:
        settings = await self.get_tenant_settings(ctx.tenant_id)
        scope = effective_scope(project.scope_mode, settings.sql_default_scope)
        if scope == "shared":
            return [user_scope_key("shared", "")]
        return [user_scope_key("per_user", ctx.user_id)]

    async def _validate_entry_for_user(
        self,
        session,
        row: Optional[CachedSqlQuery],
        *,
        tenant_id: str,
        user_id: str,
        profile_slug: Optional[str] = None,
        project_slug: Optional[str] = None,
    ) -> tuple[Optional[CachedSqlQuery], Optional[SqlQueryProject], str]:
        """Return (row, project, error_code). error_code is empty when OK."""
        if not row:
            return None, None, "not_found"
        project = await session.get(SqlQueryProject, row.project_id)
        if not project:
            return row, None, "not_found"
        ok, _ = await self._can_access_project(session, project, user_id)
        if not ok:
            return row, project, "forbidden"
        bound = (project_slug or "").strip().lower()
        if bound and project.slug != bound:
            return row, project, "wrong_project"
        ctx = ScopeContext(
            tenant_id=tenant_id,
            user_id=sanitize_user_id(user_id),
            profile_slug=profile_slug,
            project_scope_mode=project.scope_mode or "inherit",
        )
        scope_keys = await self._visible_scope_keys(ctx, project)
        if row.user_scope_key not in scope_keys:
            return row, project, "forbidden"
        return row, project, ""

    @staticmethod
    def format_mutation_error(
        code: str,
        *,
        entry_id: int,
        project_slug: Optional[str] = None,
        entry_project: Optional[str] = None,
    ) -> str:
        if code == "not_found":
            return f"SQL query id={entry_id} not found."
        if code == "forbidden":
            return f"SQL query id={entry_id} exists but you do not have permission to modify it."
        if code == "wrong_project":
            active = (project_slug or "").strip() or "?"
            other = (entry_project or "").strip() or "?"
            return (
                f"SQL query id={entry_id} belongs to project '{other}', not the active project "
                f"'{active}'. Use sql_memory_list_saved to list ids in the active project, "
                f"or sql_memory_save to store a corrected query."
            )
        if code == "no_fields":
            return f"SQL query id={entry_id}: nothing to update (provide sql, request, or is_verified)."
        return f"SQL query id={entry_id}: mutation failed ({code or 'unknown'})."

    async def resolve_mutation_error_message(
        self,
        code: str,
        *,
        entry_id: int,
        project_slug: Optional[str] = None,
    ) -> str:
        entry_project = None
        if code == "wrong_project":
            async with self.session_maker() as session:
                row = await session.get(CachedSqlQuery, entry_id)
                if row:
                    proj = await session.get(SqlQueryProject, row.project_id)
                    entry_project = proj.slug if proj else None
        return self.format_mutation_error(
            code,
            entry_id=entry_id,
            project_slug=project_slug,
            entry_project=entry_project,
        )

    async def search(
        self,
        *,
        request_text: str,
        project_slug: str,
        tenant_id: Optional[str] = None,
        user_id: str = "default",
        profile_slug: Optional[str] = None,
        sql_draft: Optional[str] = None,
        limit: int = 5,
        verified_only: bool = False,
    ) -> List[SqlQueryHit]:
        if not sql_query_memory_enabled():
            return []
        tid = tenant_id or default_tenant_id()
        project = await self._resolve_project_for_user(
            project_slug=project_slug,
            tenant_id=tid,
            user_id=user_id,
            profile_slug=profile_slug,
            allow_create=False,
        )
        if not project:
            return []
        ctx = ScopeContext(tid, user_id, profile_slug, project.scope_mode)
        scope_keys = await self._visible_scope_keys(ctx, project)
        norm_req = normalize_request_text(request_text)
        norm_intent = normalize_request_intent(request_text)
        fp = sql_fingerprint(sql_draft) if sql_draft else None
        emb_req = get_embedding(request_text)
        emb_intent = get_embedding(norm_intent) if norm_intent != norm_req else None
        emb_sql = get_embedding(sql_draft) if sql_draft else None
        threshold = _env_float("AION_SQL_QM_SEARCH_THRESHOLD", 0.78)
        struct_threshold = _env_float("AION_SQL_QM_STRUCT_MATCH_THRESHOLD", 0.85)

        async with self.session_maker() as session:
            q = select(CachedSqlQuery).where(
                CachedSqlQuery.project_id == project.id,
                CachedSqlQuery.user_scope_key.in_(scope_keys),
            )
            if verified_only:
                q = q.where(CachedSqlQuery.is_verified == 1)
            candidates = (await session.execute(q)).scalars().all()

        hits: List[SqlQueryHit] = []
        for cand in candidates:
            score = 0.0
            cand_meta = None
            if cand.metadata_json:
                try:
                    cand_meta = json.loads(cand.metadata_json)
                except json.JSONDecodeError:
                    cand_meta = None
            cand_intent = (cand_meta or {}).get(
                "intent_template"
            ) or normalize_request_intent(cand.user_request)
            if norm_intent and cand_intent and norm_intent == cand_intent:
                score = max(score, 0.98)
            elif norm_req and normalize_request_text(cand.user_request) == norm_req:
                score = 1.0
            elif fp and cand.sql_fingerprint == fp:
                score = 1.0
            else:
                if emb_req is not None:
                    cemb = bytes_to_embedding(cand.embedding_request)
                    if cemb is not None:
                        score = max(score, cosine_similarity(emb_req, cemb))
                if emb_intent is not None:
                    cemb_i = bytes_to_embedding(cand.embedding_request)
                    if cemb_i is not None:
                        score = max(score, cosine_similarity(emb_intent, cemb_i) * 0.95)
                if emb_sql is not None:
                    cemb_sql = bytes_to_embedding(cand.embedding_sql)
                    if cemb_sql is not None:
                        score = max(score, cosine_similarity(emb_sql, cemb_sql))
                if sql_draft and cand.sql_fingerprint:
                    draft_fp = sql_fingerprint(sql_draft)
                    if draft_fp == cand.sql_fingerprint:
                        score = max(score, struct_threshold)
                if norm_req and norm_req in normalize_request_text(cand.user_request):
                    score = max(score, 0.5)
                if norm_intent and norm_intent != "<FOLLOW_UP_DETAIL>":
                    if norm_intent in cand_intent or cand_intent in norm_intent:
                        score = max(score, 0.72)

            if score >= threshold or score >= 1.0:
                tables = None
                if cand.tables_used_json:
                    try:
                        tables = json.loads(cand.tables_used_json)
                    except json.JSONDecodeError:
                        tables = None
                meta = None
                if cand.metadata_json:
                    try:
                        meta = json.loads(cand.metadata_json)
                    except json.JSONDecodeError:
                        meta = None
                hits.append(
                    SqlQueryHit(
                        id=cand.id,
                        user_request=cand.user_request,
                        sql_text=cand.sql_text,
                        is_verified=bool(cand.is_verified),
                        success_count=cand.success_count,
                        score=score,
                        project_slug=project.slug,
                        tables_used=tables if isinstance(tables, list) else None,
                        metadata=meta,
                    )
                )

        hits.sort(
            key=lambda h: (h.is_verified, h.success_count, h.score),
            reverse=True,
        )
        return hits[:limit]

    async def save(
        self,
        *,
        request_text: str,
        sql_text: str,
        project_slug: str,
        tenant_id: Optional[str] = None,
        user_id: str = "default",
        profile_slug: Optional[str] = None,
        is_verified: bool = False,
        tables_used: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        if not sql_query_memory_enabled():
            return -1
        tid = tenant_id or default_tenant_id()
        project = await self._resolve_project_for_user(
            project_slug=project_slug,
            tenant_id=tid,
            user_id=user_id,
            profile_slug=profile_slug,
            allow_create=False,
        )
        if not project:
            return -1
        settings = await self.get_tenant_settings(tid)
        scope = effective_scope(project.scope_mode, settings.sql_default_scope)
        usk = user_scope_key(scope, user_id)

        intent_template, parameterized_sql, auto_meta = build_save_metadata(
            request_text=request_text,
            sql_text=sql_text,
            extra=metadata,
        )
        merged_tables = tables_used or auto_meta.get("tables_used")
        merged_meta = {**auto_meta, **(metadata or {})}
        store_sql = parameterized_sql if parameterized_sql.strip() else sql_text.strip()
        store_request = intent_template if intent_template else request_text.strip()

        fp = sql_fingerprint(store_sql)
        emb_req = embedding_to_bytes(get_embedding(store_request))
        emb_sql = embedding_to_bytes(get_embedding(store_sql))
        tables_json = json.dumps(merged_tables) if merged_tables else None
        meta_json = json.dumps(merged_meta) if merged_meta else None

        dedup_threshold = _env_float("AION_SQL_QM_DEDUP_THRESHOLD", 0.90)
        similar = await self.search(
            request_text=store_request,
            project_slug=project_slug,
            tenant_id=tid,
            user_id=user_id,
            profile_slug=profile_slug,
            sql_draft=store_sql,
            limit=3,
            verified_only=False,
        )
        if similar and similar[0].score >= dedup_threshold:
            entry_id = similar[0].id
            async with self.session_maker() as session:
                row = await session.get(CachedSqlQuery, entry_id)
                if row:
                    row.user_request = request_text.strip()
                    row.sql_text = store_sql
                    row.embedding_request = emb_req
                    row.embedding_sql = emb_sql
                    row.sql_fingerprint = fp
                    row.tables_used_json = tables_json or row.tables_used_json
                    if merged_meta:
                        row.metadata_json = meta_json
                    row.success_count += 1
                    if is_verified:
                        row.is_verified = 1
                    row.updated_at = datetime.now(timezone.utc)
                    row.last_used_at = datetime.now(timezone.utc)
                    await session.commit()
            return entry_id

        review_lo = _env_float("AION_SQL_QM_REVIEW_THRESHOLD", 0.82)
        if similar and similar[0].score >= review_lo:
            merged_meta = dict(merged_meta)
            merged_meta["needs_review"] = True
            meta_json = json.dumps(merged_meta)

        async with self.session_maker() as session:
            row = CachedSqlQuery(
                project_id=project.id,
                tenant_id=tid,
                user_id=user_id if scope == "per_user" else None,
                user_scope_key=usk,
                user_request=request_text.strip(),
                sql_text=store_sql,
                sql_fingerprint=fp,
                embedding_request=emb_req,
                embedding_sql=emb_sql,
                tables_used_json=tables_json,
                metadata_json=meta_json,
                is_verified=1 if is_verified else 0,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id

    async def increment_success(
        self,
        entry_id: int,
        *,
        user_id: str = "default",
        tenant_id: Optional[str] = None,
        profile_slug: Optional[str] = None,
        project_slug: Optional[str] = None,
    ) -> tuple[bool, str]:
        tid = tenant_id or default_tenant_id()
        auto_thr = _env_int("AION_SQL_QM_AUTO_VERIFY_THRESHOLD", 3)
        if auto_thr <= 0:
            auto_thr = _env_int("AION_AUTO_VERIFY_THRESHOLD", 3)
        async with self.session_maker() as session:
            row = await session.get(CachedSqlQuery, entry_id)
            row, _project, err = await self._validate_entry_for_user(
                session,
                row,
                tenant_id=tid,
                user_id=user_id,
                profile_slug=profile_slug,
                project_slug=project_slug,
            )
            if err:
                return False, err
            row.success_count += 1
            row.last_used_at = datetime.now(timezone.utc)
            if not row.is_verified and row.success_count >= auto_thr:
                row.is_verified = 1
            await session.commit()
            return True, ""

    async def touch_used(self, entry_id: int) -> bool:
        async with self.session_maker() as session:
            await session.execute(
                update(CachedSqlQuery)
                .where(CachedSqlQuery.id == entry_id)
                .values(last_used_at=datetime.now(timezone.utc))
            )
            await session.commit()
            return True

    async def delete_entry(
        self,
        entry_id: int,
        *,
        user_id: str = "default",
        tenant_id: Optional[str] = None,
        profile_slug: Optional[str] = None,
        project_slug: Optional[str] = None,
    ) -> tuple[bool, str]:
        tid = tenant_id or default_tenant_id()
        async with self.session_maker() as session:
            row = await session.get(CachedSqlQuery, entry_id)
            row, project, err = await self._validate_entry_for_user(
                session,
                row,
                tenant_id=tid,
                user_id=user_id,
                profile_slug=profile_slug,
                project_slug=project_slug,
            )
            if err:
                return False, err
            await session.execute(
                delete(CachedSqlQuery).where(CachedSqlQuery.id == entry_id)
            )
            await session.commit()
            return True, ""

    async def update_entry(
        self,
        entry_id: int,
        *,
        user_request: Optional[str] = None,
        sql_text: Optional[str] = None,
        is_verified: Optional[bool] = None,
        user_id: str = "default",
        tenant_id: Optional[str] = None,
        profile_slug: Optional[str] = None,
        project_slug: Optional[str] = None,
    ) -> tuple[bool, str]:
        tid = tenant_id or default_tenant_id()
        if user_request is None and sql_text is None and is_verified is None:
            return False, "no_fields"
        async with self.session_maker() as session:
            row = await session.get(CachedSqlQuery, entry_id)
            row, project, err = await self._validate_entry_for_user(
                session,
                row,
                tenant_id=tid,
                user_id=user_id,
                profile_slug=profile_slug,
                project_slug=project_slug,
            )
            if err:
                return False, err
            if user_request:
                row.user_request = user_request.strip()
                row.embedding_request = embedding_to_bytes(get_embedding(user_request))
            if sql_text:
                row.sql_text = sql_text.strip()
                row.sql_fingerprint = sql_fingerprint(sql_text)
                row.embedding_sql = embedding_to_bytes(get_embedding(sql_text))
            if is_verified is not None:
                row.is_verified = 1 if is_verified else 0
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return True, ""

    async def list_queries(
        self,
        *,
        project_slug: str,
        tenant_id: Optional[str] = None,
        user_id: str = "default",
        q: Optional[str] = None,
        verified_only: bool = False,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        tid = tenant_id or default_tenant_id()
        project = await self.get_project_by_slug(project_slug, tenant_id=tid)
        if not project:
            return []
        async with self.session_maker() as session:
            ok, _ = await self._can_access_project(session, project, user_id)
            if not ok:
                return []
        ctx = ScopeContext(tid, user_id, None, project.scope_mode)
        scope_keys = await self._visible_scope_keys(ctx, project)
        async with self.session_maker() as session:
            stmt = (
                select(CachedSqlQuery)
                .where(
                    CachedSqlQuery.project_id == project.id,
                    CachedSqlQuery.user_scope_key.in_(scope_keys),
                )
                .order_by(CachedSqlQuery.updated_at.desc())
                .limit(limit)
            )
            if verified_only:
                stmt = stmt.where(CachedSqlQuery.is_verified == 1)
            rows = (await session.execute(stmt)).scalars().all()
        out: List[Dict[str, Any]] = []
        qn = (q or "").strip().lower()
        for r in rows:
            if qn and qn not in r.user_request.lower() and qn not in r.sql_text.lower():
                continue
            out.append(
                {
                    "id": r.id,
                    "user_request": r.user_request,
                    "sql_text": r.sql_text,
                    "is_verified": bool(r.is_verified),
                    "success_count": r.success_count,
                    "failure_count": r.failure_count,
                    "last_used_at": r.last_used_at.isoformat()
                    if r.last_used_at
                    else None,
                    "project_slug": project.slug,
                }
            )
        return out

    def format_list_results_markdown(
        self, rows: List[Dict[str, Any]], *, project_slug: str
    ) -> str:
        if not rows:
            return (
                f"No saved SQL queries in project '{project_slug}'. "
                "Use sql_memory_save / save_successful_sql after a successful SELECT."
            )
        lines = [
            f"Saved SQL queries in project '{project_slug}' ({len(rows)} shown):\n",
        ]
        for r in rows:
            status = "verified" if r.get("is_verified") else "draft"
            lines.append(
                f"- ID {r['id']} [{status}, successes={r.get('success_count', 0)}] "
                f'"{r.get("user_request", "")}"\n'
                f"  SQL: {r.get('sql_text', '')}"
            )
        return "\n".join(lines)

    def format_search_results_markdown(self, hits: List[SqlQueryHit]) -> str:
        if not hits:
            return (
                "No similar SQL queries found in QueryMemory. "
                "Run a new query or call save_successful_sql / sql_memory_save after success."
            )
        lines = [
            "SQL queries found in QueryMemory (by relevance). "
            "Check whether any match the request:\n",
        ]
        for h in hits:
            status = "verified" if h.is_verified else "suggested"
            lines.append(f"- ID: {h.id} [{status}] (score: {h.score:.2f})")
            lines.append(f'  Request: "{h.user_request}"')
            lines.append(f"  SQL: {h.sql_text}\n")
        return "\n".join(lines)


sql_query_memory = SqlQueryMemoryService()
