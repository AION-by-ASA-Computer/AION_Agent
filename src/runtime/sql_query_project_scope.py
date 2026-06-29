"""Hard-bind SQL QueryMemory tools to the chat-ui selected project (per turn)."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, FrozenSet, Optional

logger = logging.getLogger("aion.sql_qm.scope")

# Tool base names where `project` / PromQL `namespace` must match the active turn project.
SQL_QM_PROJECT_SCOPED_TOOLS: FrozenSet[str] = frozenset(
    {
        "sql_memory_search",
        "sql_memory_save",
        "sql_memory_update",
        "sql_memory_delete",
        "sql_memory_list_saved",
        "search_known_sql",
        "save_successful_sql",
        "mark_sql_query_successful",
        "update_sql_memory_entry",
        "delete_sql_memory_entry",
    }
)

# Agent cannot enumerate/switch projects mid-turn.
SQL_QM_PROJECT_LIST_TOOLS: FrozenSet[str] = frozenset(
    {
        "sql_memory_list_projects",
        "list_sql_projects",
    }
)


def project_scope_enforced() -> bool:
    return os.getenv("AION_SQL_QM_PROJECT_SCOPE_ENFORCE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _tool_base(tool_name: str) -> str:
    return (tool_name or "").split("-")[-1].strip().lower()


def bound_sql_project(session_id: Optional[str] = None) -> Optional[str]:
    """Active project slug from turn context (set from chat-ui at pre_turn)."""
    try:
        from src.runtime.sql_query_memory_context import get_sql_qm_turn_context

        ctx = get_sql_qm_turn_context(session_id)
    except Exception:
        ctx = None
    if ctx and (ctx.project_slug or "").strip():
        return ctx.project_slug.strip()
    return None


def block_project_list_tool(tool_name: str, session_id: Optional[str] = None) -> Optional[str]:
    """Disallow listing/switching projects while a turn project is bound."""
    if not project_scope_enforced():
        return None
    if _tool_base(tool_name) not in SQL_QM_PROJECT_LIST_TOOLS:
        return None
    bound = bound_sql_project(session_id)
    if not bound:
        return None
    return (
        f"Tool `{tool_name}` is disabled during an active data turn. "
        f"The SQL QueryMemory project is fixed to `{bound}` (selected in chat-ui). "
        "Use sql_memory_search / sql_memory_save without a project parameter."
    )


def apply_sql_query_project_scope(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Force SQL memory tools to use the bound project; ignore agent-supplied project/namespace.
    """
    if not project_scope_enforced():
        return arguments
    base = _tool_base(tool_name)
    if base not in SQL_QM_PROJECT_SCOPED_TOOLS:
        return arguments
    bound = bound_sql_project(session_id)
    if not bound:
        return arguments
    out = dict(arguments or {})
    requested = (out.get("project") or out.get("namespace") or "").strip()
    if requested and requested.lower() != bound.lower():
        logger.warning(
            "sql_qm scope: blocked project override %s -> %s (tool=%s session=%s)",
            requested,
            bound,
            tool_name,
            (session_id or "")[:12],
        )
    out.pop("namespace", None)
    out["project"] = bound
    return out


async def verify_user_project_access(
    *,
    project_slug: str,
    tenant_id: Optional[str] = None,
    user_id: str = "default",
    profile_slug: Optional[str] = None,
) -> Optional[str]:
    """
    Return user-visible error when the user cannot access the project, else None.
    """
    slug = (project_slug or "").strip().lower()
    if not slug:
        return "No SQL QueryMemory project selected."
    if slug == "default":
        should_block = True
        if profile_slug:
            try:
                from src.runtime.query_memory_hooks import profile_has_memory_capability_by_slug
                should_block = profile_has_memory_capability_by_slug(profile_slug)
            except Exception:
                pass
        if should_block:
            return (
                "Access to the default SQL QueryMemory project is disabled for memory-enabled profiles. "
                "Please create or select a dedicated project in the chat-ui."
            )
    try:
        from src.memory.sql_query_memory import sql_query_memory

        err = await sql_query_memory.check_user_project_access(
            project_slug=slug,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return err
    except Exception as exc:
        logger.warning("verify_user_project_access failed: %s", exc)
        return f"Could not verify access to project '{slug}'."


async def verify_bound_project_access(session_id: Optional[str], user_id: str) -> Optional[str]:
    bound = bound_sql_project(session_id)
    if not bound:
        return None
    try:
        from src.runtime.sql_query_memory_context import get_sql_qm_turn_context

        ctx = get_sql_qm_turn_context(session_id)
        tenant = ctx.tenant_id if ctx else None
        profile_slug = ctx.profile_slug if ctx else None
    except Exception:
        tenant = None
        profile_slug = None
    return await verify_user_project_access(
        project_slug=bound,
        tenant_id=tenant,
        user_id=user_id,
        profile_slug=profile_slug,
    )
