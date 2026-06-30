"""Built-in in-process SQL QueryMemory tools (merge into agent tool list)."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, List, Optional

from haystack.tools import Tool

from src.memory.sql_query_memory import sql_query_memory, sql_query_memory_enabled
from src.runtime.sql_query_memory_context import get_sql_qm_turn_context
from src.runtime.sql_query_project_scope import (
    bound_sql_project,
    project_scope_enforced,
    verify_user_project_access,
)

SQL_QM_BUILTIN_TOOL_NAMES = (
    "sql_memory_search",
    "sql_memory_save",
    "sql_memory_update",
    "sql_memory_delete",
    "sql_memory_list_projects",
    "sql_memory_list_saved",
)


def sql_native_tools_enabled() -> bool:
    if not sql_query_memory_enabled():
        return False
    return os.getenv("AION_SQL_QM_NATIVE_TOOLS", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def profile_wants_sql_query_memory(profile) -> bool:
    groups = getattr(profile, "native_tool_groups", None) or []
    if "sql_query_memory" in groups:
        return True
    servers = getattr(profile, "mcp_servers", None) or []
    return any(s in servers for s in ("toolbox-postgres", "toolbox-mysql"))


def _run_async(coro) -> Any:
    from src.main import _GLOBAL_LOOP

    loop = _GLOBAL_LOOP
    if not loop:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            pass
    if not loop:
        raise RuntimeError("No event loop for SQL QueryMemory tools")
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=float(os.getenv("AION_SQL_QM_TOOL_TIMEOUT_SEC", "60")))


def _resolve_ctx(
    session_id: str,
    user_id: str,
    profile_slug: str,
    project: str = "",
) -> tuple[str, str, str, str, Optional[str]]:
    """
    Return (tenant, user, profile, project, access_error).
    Project is always the chat-ui bound slug when scope enforcement is on.
    """
    turn = get_sql_qm_turn_context(session_id)
    if turn and turn.session_id == session_id:
        bound = (turn.project_slug or "").strip()
        if project_scope_enforced() and bound:
            proj = bound
        else:
            proj = (project or bound).strip()
        return turn.tenant_id, turn.user_id, turn.profile_slug, proj, None
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    proj = (
        project
        or os.getenv("AION_SQL_QM_CURRENT_PROJECT")
        or os.getenv("AION_SQL_QM_DEFAULT_PROJECT")
        or "default"
    ).strip()
    return tenant, user_id, profile_slug, proj, None


def _access_error_or_none(tenant: str, uid: str, proj: str) -> Optional[str]:
    if not (proj or "").strip():
        return "No SQL QueryMemory project is bound to this turn."

    async def _check() -> Optional[str]:
        return await verify_user_project_access(
            project_slug=proj,
            tenant_id=tenant,
            user_id=uid,
        )

    return _run_async(_check())


def build_sql_query_memory_haystack_tools(
    session_id: str, user_id: str, profile_slug: str
) -> List[Tool]:
    def sql_memory_search_fn(
        request: str,
        project: str = "",
        verified_only: bool = False,
        sql_draft: str = "",
    ) -> str:
        from src.runtime.sql_query_memory_gate import (
            block_exploration_tool_if_sql_cache,
        )

        blocked = block_exploration_tool_if_sql_cache(
            "sql_query_memory", "sql_memory_search", session_id, {}
        )
        if blocked:
            return blocked
        tenant, uid, prof, proj, _ = _resolve_ctx(
            session_id, user_id, profile_slug, project
        )
        access_err = _access_error_or_none(tenant, uid, proj)
        if access_err:
            return access_err

        async def _run() -> str:
            hits = await sql_query_memory.search(
                request_text=request,
                project_slug=proj,
                tenant_id=tenant,
                user_id=uid,
                profile_slug=prof,
                sql_draft=sql_draft or None,
                limit=5,
                verified_only=verified_only,
            )
            return sql_query_memory.format_search_results_markdown(hits)

        return _run_async(_run())

    def sql_memory_save_fn(
        request: str,
        sql: str,
        project: str = "",
        is_verified: bool = False,
        tables_used: Optional[List[str]] = None,
    ) -> str:
        tenant, uid, prof, proj, _ = _resolve_ctx(
            session_id, user_id, profile_slug, project
        )
        access_err = _access_error_or_none(tenant, uid, proj)
        if access_err:
            return access_err

        async def _run() -> str:
            eid = await sql_query_memory.save(
                request_text=request,
                sql_text=sql,
                project_slug=proj,
                tenant_id=tenant,
                user_id=uid,
                profile_slug=prof,
                is_verified=is_verified,
                tables_used=tables_used,
            )
            if eid < 0:
                return json.dumps(
                    {"ok": False, "error": "save_failed_or_forbidden", "project": proj},
                    ensure_ascii=False,
                )
            return json.dumps(
                {"ok": True, "id": eid, "project": proj}, ensure_ascii=False
            )

        return _run_async(_run())

    def sql_memory_update_fn(
        id: int,
        request: str = "",
        sql: str = "",
        is_verified: Optional[bool] = None,
        project: str = "",
    ) -> str:
        tenant, uid, prof, proj, _ = _resolve_ctx(
            session_id, user_id, profile_slug, project
        )
        access_err = _access_error_or_none(tenant, uid, proj)
        if access_err:
            return access_err

        async def _run() -> str:
            ok, err = await sql_query_memory.update_entry(
                id,
                user_request=request or None,
                sql_text=sql or None,
                is_verified=is_verified,
                user_id=uid,
                tenant_id=tenant,
                profile_slug=prof,
                project_slug=proj,
            )
            if ok:
                return json.dumps(
                    {"ok": True, "id": id, "project": proj}, ensure_ascii=False
                )
            msg = await sql_query_memory.resolve_mutation_error_message(
                err, entry_id=id, project_slug=proj
            )
            return json.dumps(
                {"ok": False, "id": id, "error": err, "message": msg},
                ensure_ascii=False,
            )

        return _run_async(_run())

    def sql_memory_delete_fn(id: int, project: str = "") -> str:
        tenant, uid, prof, proj, _ = _resolve_ctx(
            session_id, user_id, profile_slug, project
        )
        access_err = _access_error_or_none(tenant, uid, proj)
        if access_err:
            return access_err

        async def _run() -> str:
            ok, err = await sql_query_memory.delete_entry(
                id,
                user_id=uid,
                tenant_id=tenant,
                profile_slug=prof,
                project_slug=proj,
            )
            if ok:
                return json.dumps(
                    {"ok": True, "id": id, "project": proj}, ensure_ascii=False
                )
            msg = await sql_query_memory.resolve_mutation_error_message(
                err, entry_id=id, project_slug=proj
            )
            return json.dumps(
                {"ok": False, "id": id, "error": err, "message": msg},
                ensure_ascii=False,
            )

        return _run_async(_run())

    def sql_memory_list_projects_fn() -> str:
        """Return only the active bound project (agent cannot switch/list all)."""
        from src.runtime.sql_query_project_scope import block_project_list_tool

        blocked = block_project_list_tool("sql_memory_list_projects", session_id)
        if blocked:
            return blocked
        tenant, uid, prof, proj, _ = _resolve_ctx(session_id, user_id, profile_slug)
        access_err = _access_error_or_none(tenant, uid, proj)
        if access_err:
            return access_err

        async def _run() -> str:
            row = await sql_query_memory.get_active_project_for_user(
                project_slug=proj,
                tenant_id=tenant,
                user_id=uid,
            )
            if not row:
                return json.dumps(
                    {
                        "active_project": proj,
                        "error": "forbidden_or_missing",
                        "message": f"No access to project '{proj}'.",
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "active_project": proj,
                    "project": row.model_dump(),
                    "note": "Project is fixed for this turn (chat-ui selection).",
                },
                ensure_ascii=False,
            )

        return _run_async(_run())

    def sql_memory_list_saved_fn(
        project: str = "",
        limit: int = 50,
        verified_only: bool = False,
    ) -> str:
        tenant, uid, prof, proj, _ = _resolve_ctx(
            session_id, user_id, profile_slug, project
        )
        access_err = _access_error_or_none(tenant, uid, proj)
        if access_err:
            return access_err

        async def _run() -> str:
            rows = await sql_query_memory.list_queries(
                project_slug=proj,
                tenant_id=tenant,
                user_id=uid,
                profile_slug=prof,
                verified_only=verified_only,
                limit=min(max(int(limit), 1), 200),
            )
            return sql_query_memory.format_list_results_markdown(
                rows, project_slug=proj
            )

        return _run_async(_run())

    return [
        Tool(
            name="sql_memory_search",
            description=(
                "[SQL QueryMemory] Semantic search for validated SELECT in the **active chat-ui project** "
                "(do not pass `project`). Call BEFORE generating new SQL. NOT for PromQL."
            ),
            function=sql_memory_search_fn,
            parameters={
                "type": "object",
                "properties": {
                    "request": {"type": "string"},
                    "verified_only": {"type": "boolean"},
                    "sql_draft": {"type": "string"},
                },
                "required": ["request"],
            },
        ),
        Tool(
            name="sql_memory_save",
            description=(
                "[SQL QueryMemory] Save a verified SELECT to the **active chat-ui project** "
                "(do not pass `project`). NOT for PromQL."
            ),
            function=sql_memory_save_fn,
            parameters={
                "type": "object",
                "properties": {
                    "request": {"type": "string"},
                    "sql": {"type": "string"},
                    "is_verified": {"type": "boolean"},
                    "tables_used": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["request", "sql"],
            },
        ),
        Tool(
            name="sql_memory_update",
            description=(
                "[SQL QueryMemory] Update an existing saved query by id in the **active chat-ui project**. "
                "Provide at least one of `request`, `sql`, or `is_verified`. "
                "Use sql_memory_list_saved to find valid ids. NOT for PromQL."
            ),
            function=sql_memory_update_fn,
            parameters={
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "request": {"type": "string"},
                    "sql": {"type": "string"},
                    "is_verified": {"type": "boolean"},
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="sql_memory_delete",
            description=(
                "[SQL QueryMemory] Delete a saved query by id from the **active chat-ui project**. "
                "Use sql_memory_list_saved to find valid ids. NOT for PromQL."
            ),
            function=sql_memory_delete_fn,
            parameters={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        ),
        Tool(
            name="sql_memory_list_projects",
            description=(
                "[SQL QueryMemory] Returns metadata for the **active chat-ui project only** "
                "(project switching is not allowed)."
            ),
            function=sql_memory_list_projects_fn,
            parameters={"type": "object", "properties": {}},
        ),
        Tool(
            name="sql_memory_list_saved",
            description=(
                "[SQL QueryMemory] List saved SQL in the **active chat-ui project** "
                "(do not pass `project`). NOT semantic search."
            ),
            function=sql_memory_list_saved_fn,
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "verified_only": {"type": "boolean"},
                },
            },
        ),
    ]


def merge_builtin_sql_query_memory_tools(
    tools: List[Any], session_id: str, user_id: str, profile
) -> List[Any]:
    if not sql_native_tools_enabled() or not profile_wants_sql_query_memory(profile):
        return tools
    existing = {getattr(t, "name", None) for t in tools}
    profile_slug = getattr(profile, "slug", None) or getattr(profile, "name", "default")
    for haystack_tool in build_sql_query_memory_haystack_tools(
        session_id, user_id, str(profile_slug)
    ):
        name = getattr(haystack_tool, "name", None)
        if name and name not in existing:
            tools.append(haystack_tool)
            existing.add(name)
    return tools
