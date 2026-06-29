"""Per-turn context for SQL QueryMemory (project slug, tenant, user)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import contextvars

    _ctx: contextvars.ContextVar[Optional["SqlQmTurnContext"]] = contextvars.ContextVar(
        "aion_sql_qm_turn", default=None
    )
except ImportError:
    _ctx = None  # type: ignore

# MCP tools run on worker threads; ContextVar alone does not propagate. Session id is the key.
_TURN_BY_SESSION: Dict[str, "SqlQmTurnContext"] = {}


@dataclass
class SqlQmTurnContext:
    tenant_id: str
    user_id: str
    profile_slug: str
    project_slug: str
    session_id: str
    mempalace_writes_allowed: bool = True
    sql_cache_inject_active: bool = False
    sql_cache_schemas: tuple[str, ...] = ()
    sql_cache_hit_ids: tuple[int, ...] = ()
    execute_sql_succeeded: bool = False
    exploration_unlocked: bool = False
    list_tables_count: int = 0
    last_success: Optional[Dict[str, Any]] = field(default=None)


def _store(ctx: SqlQmTurnContext) -> None:
    _TURN_BY_SESSION[ctx.session_id] = ctx
    if _ctx is not None:
        _ctx.set(ctx)


def set_sql_qm_turn_context(
    *,
    tenant_id: Optional[str] = None,
    user_id: str,
    profile_slug: str,
    project_slug: Optional[str] = None,
    session_id: str,
    mempalace_writes_allowed: bool = True,
    sql_cache_inject_active: bool = False,
    sql_cache_schemas: Optional[tuple[str, ...]] = None,
    sql_cache_hit_ids: Optional[tuple[int, ...]] = None,
) -> None:
    tid = (
        tenant_id or os.getenv("AION_DEFAULT_TENANT_ID") or "default"
    ).strip() or "default"
    proj = (
        project_slug or os.getenv("AION_SQL_QM_DEFAULT_PROJECT") or "default"
    ).strip() or "default"
    _store(
        SqlQmTurnContext(
            tenant_id=tid,
            user_id=user_id,
            profile_slug=profile_slug,
            project_slug=proj,
            session_id=session_id,
            mempalace_writes_allowed=mempalace_writes_allowed,
            sql_cache_inject_active=sql_cache_inject_active,
            sql_cache_schemas=sql_cache_schemas or (),
            sql_cache_hit_ids=sql_cache_hit_ids or (),
        )
    )


def get_sql_qm_turn_context(
    session_id: Optional[str] = None,
) -> Optional[SqlQmTurnContext]:
    if session_id:
        hit = _TURN_BY_SESSION.get(session_id)
        if hit is not None:
            return hit
    if _ctx is not None:
        return _ctx.get()
    return None


def _update_session(session_id: str, **changes) -> None:
    cur = get_sql_qm_turn_context(session_id)
    if cur is None or cur.session_id != session_id:
        return
    data = {
        "tenant_id": cur.tenant_id,
        "user_id": cur.user_id,
        "profile_slug": cur.profile_slug,
        "project_slug": cur.project_slug,
        "session_id": cur.session_id,
        "mempalace_writes_allowed": cur.mempalace_writes_allowed,
        "sql_cache_inject_active": cur.sql_cache_inject_active,
        "sql_cache_schemas": cur.sql_cache_schemas,
        "sql_cache_hit_ids": cur.sql_cache_hit_ids,
        "execute_sql_succeeded": cur.execute_sql_succeeded,
        "exploration_unlocked": cur.exploration_unlocked,
        "list_tables_count": cur.list_tables_count,
        "last_success": cur.last_success,
    }
    data.update(changes)
    _store(SqlQmTurnContext(**data))


def mark_execute_sql_succeeded(session_id: str) -> None:
    _update_session(
        session_id,
        execute_sql_succeeded=True,
        exploration_unlocked=True,
    )


def mark_execute_sql_failed(session_id: str) -> None:
    """Allow list_tables / memory search again after cached SQL failed."""
    _update_session(session_id, exploration_unlocked=True)


def mark_execute_sql_used(session_id: str) -> None:
    mark_execute_sql_succeeded(session_id)


def set_mempalace_writes_allowed(allowed: bool) -> None:
    cur = get_sql_qm_turn_context()
    if cur is None:
        return
    _update_session(cur.session_id, mempalace_writes_allowed=allowed)


def increment_list_tables_count(session_id: str) -> None:
    cur = get_sql_qm_turn_context(session_id)
    if cur is None:
        return
    _update_session(session_id, list_tables_count=cur.list_tables_count + 1)


def record_last_success(
    session_id: str,
    *,
    sql_text: str,
    user_request: str = "",
    schemas: Optional[List[str]] = None,
    tables: Optional[List[str]] = None,
) -> None:
    payload = {
        "sql_text": (sql_text or "")[:2000],
        "user_request": (user_request or "")[:500],
        "schemas": schemas or [],
        "tables": tables or [],
    }
    _update_session(session_id, last_success=payload)


def format_session_entity_cache_block(session_id: Optional[str]) -> str:
    """Compact READ-only inject for follow-up questions in the same thread."""
    cur = get_sql_qm_turn_context(session_id)
    if not cur or not cur.last_success:
        return ""
    ls = cur.last_success
    sql_preview = (ls.get("sql_text") or "").strip()
    if not sql_preview:
        return ""
    schemas = ls.get("schemas") or []
    tables = ls.get("tables") or []
    lines = [
        "\n\n## Session context (same thread — reuse, do not re-explore)",
        "Previous turn executed SQL successfully in this session. For follow-ups "
        "('serial?', 'model?', 'and the brand?') adapt the SQL below instead of "
        "calling `list_tables` again.",
    ]
    if schemas:
        lines.append(f"Schemas: `{', '.join(schemas)}`")
    if tables:
        lines.append(f"Tables: `{', '.join(tables)}`")
    if ls.get("user_request"):
        lines.append(f'Prior question: "{ls["user_request"]}"')
    lines.append(f"```sql\n{sql_preview[:1500]}\n```")
    return "\n".join(lines)


def clear_sql_qm_turn_context(session_id: Optional[str] = None) -> None:
    if session_id:
        _TURN_BY_SESSION.pop(session_id, None)
    else:
        _TURN_BY_SESSION.clear()
    if _ctx is not None:
        _ctx.set(None)


def increment_cache_hits_sync(session_id: str) -> None:
    """Fire-and-forget success bump for server-injected SQL cache hits."""
    ctx = get_sql_qm_turn_context(session_id)
    if not ctx or not ctx.sql_cache_hit_ids:
        return
    try:
        from src.runtime.sql_query_memory_tools import _run_async
        from src.memory.sql_query_memory import sql_query_memory

        for entry_id in ctx.sql_cache_hit_ids:
            try:
                _run_async(sql_query_memory.increment_success(entry_id))
            except Exception:
                pass
    except Exception:
        pass
