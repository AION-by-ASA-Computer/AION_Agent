from fastmcp import FastMCP
import os
import sys
from typing import Optional, List

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.query_memory import memory
from src.api.history import history_manager
from src.memory.llm_extract import complete_text_sync
from src.memory.sql_query_memory import sql_query_memory, sql_query_memory_enabled

mcp = FastMCP("AION Query Memory")


def _mcp_sql_context() -> tuple[str, str, str]:
    tenant = (os.getenv("AION_CURRENT_TENANT_ID") or "default").strip() or "default"
    user = (os.getenv("AION_CURRENT_USER_ID") or "default").strip() or "default"
    profile = (os.getenv("AION_CURRENT_PROFILE_SLUG") or "").strip() or None
    return tenant, user, profile or None


def _resolve_profile_slug(profile: Optional[str]) -> Optional[str]:
    if not (profile or "").strip():
        return None
    from src.agent_profile import profile_manager

    p = profile_manager.get_profile(profile.strip())
    if p:
        return p.slug
    return profile.strip().replace(" ", "_").lower()


async def _active_sql_project() -> str:
    sid = (os.getenv("AION_CHAT_SESSION_ID") or "").strip()
    if sid:
        try:
            from src.runtime.sql_query_memory_context import get_sql_qm_turn_context

            ctx = get_sql_qm_turn_context(sid)
            if ctx and (ctx.project_slug or "").strip():
                return ctx.project_slug.strip()
        except Exception:
            pass
        from src.memory.sql_query_memory.conversation_project import (
            get_conversation_sql_project,
        )

        conv = await get_conversation_sql_project(sid)
        if conv:
            return conv
    return (
        os.getenv("AION_SQL_QM_CURRENT_PROJECT")
        or os.getenv("AION_SQL_QM_DEFAULT_PROJECT")
        or "default"
    ).strip() or "default"


def _default_sql_project() -> str:
    """Sync fallback when async session lookup is unavailable."""
    return (
        os.getenv("AION_SQL_QM_CURRENT_PROJECT")
        or os.getenv("AION_SQL_QM_DEFAULT_PROJECT")
        or "default"
    ).strip() or "default"


async def _bound_sql_project(project: str = "") -> str:
    """Active chat-ui project; optional `project` arg is accepted for scope preflight."""
    bound = (project or "").strip()
    if bound:
        return bound
    return await _active_sql_project()


@mcp.tool()
async def search_known_query(
    request: str, namespace: str = "default", verified_only: bool = False
) -> str:
    """
    [PROMQL CACHE ONLY] Search the validated PromQL query cache.
    This tool is EXCLUSIVELY for Prometheus/PromQL queries —
    Do NOT use it to search past conversations or generic memory.
    To search chat history, use `session_search`.
    To search facts and preferences, use `mempalace_search` on the mempalace server.

    Compare `request` (natural language) with previously saved PromQL queries
    via cosine similarity on embeddings. Returns matches sorted by relevance.
    """
    results = await memory.search(
        request, limit=5, namespace=namespace, verified_only=verified_only
    )
    if not results:
        return "No similar PromQL query found in cache. Proceed with generating a new PromQL query."

    output = "PromQL queries found in cache (sorted by relevance). Check whether any match the request:\n\n"
    for r in results:
        status = "✅ Verified" if r["is_verified"] else "⏳ Suggested"
        output += f"- ID: {r['id']} [{status}] (Score: {r['score']:.2f})\n"
        output += f'  Request: "{r["user_request"]}"\n'
        output += f"  Query PromQL: {r['promql_query']}\n\n"
    return output


@mcp.tool()
async def save_successful_query(
    request: str, query: str, namespace: str = "default", is_verified: bool = False
) -> str:
    """
    [PROMQL CACHE ONLY] Save a verified PromQL query to the cache for future use.
    This tool is EXCLUSIVELY for Prometheus/PromQL queries —
    Do NOT use it to save conversations, generic facts, or user preferences.
    To persist facts and preferences, use `mempalace_save` on the mempalace server.
    Use is_verified=True only if the PromQL query already produced correct results.
    """
    success = await memory.add(
        request, query, namespace=namespace, is_verified=is_verified
    )
    return (
        f"Saved successfully: '{request}' -> '{query}'"
        if success
        else "Error while saving to memory."
    )


@mcp.tool()
async def mark_query_as_successful(id: int) -> str:
    """
    [PROMQL CACHE ONLY] Increment the success counter for a cached PromQL query.
    Use only to confirm a PromQL query produced correct results.
    After enough successes the query is verified automatically.
    """
    await memory.increment_success(id)
    return f"Success recorded for query ID {id}."


@mcp.tool()
async def delete_memory_entry(id: int) -> str:
    """Permanently delete a memory entry (requires ID)."""
    success = await memory.delete_entry(id)
    return f"Entry {id} deleted." if success else "Entry not found."


@mcp.tool()
def session_search(
    query: str,
    limit: int = 5,
    since_days: int = 30,
    summarize: bool = True,
) -> str:
    """
    [CHAT HISTORY SEARCH ONLY] Full-text search (FTS5) on past conversations
    persisted in the unified DB (``aion.db`` / ``AION_UNIFIED_DB``).
    Use when the user asks what was said/discussed in past sessions
    (e.g. "what did we discuss yesterday?", "remember when I said X?").
    Do NOT use for PromQL queries (use `search_known_query`) or
    structured facts/preferences (use `mempalace_search`).
    With summarize=True synthesizes matches using the configured model.
    """
    rows = history_manager.fts_search_blocking(
        query, limit=limit * 3, since_days=since_days
    )
    if not rows:
        return "No past conversations found for the query."

    seen_sessions = set()
    matches = []
    for r in rows:
        sid = r.get("session_id") or ""
        if sid in seen_sessions:
            continue
        seen_sessions.add(sid)
        rid = r.get("id") or r.get("rowid")
        if rid is None:
            continue
        ctx = history_manager.get_turn_context_blocking(str(rid), window=2)
        matches.append(
            {
                "session_id": sid,
                "timestamp": r.get("timestamp"),
                "profile": r.get("profile_name"),
                "turn_context": "\n".join(
                    f"{m.get('role', '?')}: {(m.get('content') or '')[:500]}"
                    for m in ctx
                ),
            }
        )
        if len(matches) >= limit:
            break

    if not summarize:
        out = [f"Found {len(matches)} conversations:"]
        for m in matches:
            out.append(f"\n### Session {str(m['session_id'])[:8]} ({m['timestamp']})")
            out.append(m["turn_context"])
        return "\n".join(out)

    system = (
        "You are a search assistant. You are given excerpts from past conversations. "
        "Summarize facts relevant to the QUERY, citing session_id and timestamp when possible. "
        "If matches do not answer the query, say so clearly."
    )
    user_prompt = f"QUERY: {query}\n\nEXCERPTS:\n"
    for m in matches:
        user_prompt += (
            f"\n[session={str(m['session_id'])[:12]} ts={m['timestamp']} profile={m['profile']}]\n"
            f"{m['turn_context']}\n"
        )
    try:
        return (
            complete_text_sync(system, user_prompt, max_tokens=800, timeout=60.0)
            or user_prompt[:4000]
        )
    except Exception as e:
        return f"[summarization failed: {e}]\n\n" + "\n---\n".join(
            m["turn_context"] for m in matches
        )


@mcp.tool()
async def update_memory_entry(
    id: int,
    user_request: str = None,
    promql_query: str = None,
    is_verified: bool = None,
) -> str:
    """Update an existing PromQL entry in memory."""
    success = await memory.update_entry(id, user_request, promql_query, is_verified)
    return f"Entry {id} updated." if success else "Update error or entry not found."


# --- SQL QueryMemory (PostgreSQL) — separate from PromQL cache ---


@mcp.tool()
async def search_known_sql(
    request: str,
    project: str = "",
    verified_only: bool = False,
    sql_draft: str = "",
) -> str:
    """
    [SQL QUERY MEMORY ONLY] Search validated PostgreSQL (SELECT) queries in the QueryMemory drawer.
    Do NOT use for PromQL (use search_known_query) or chat history (session_search).
    ALWAYS call before exploring information_schema or inventing SQL from scratch.
    `project` = drawer slug (e.g. sales, tech); defaults from config if empty.
    """
    if not sql_query_memory_enabled():
        return "SQL QueryMemory disabled (AION_SQL_QM_ENABLED=0)."
    tenant, user, profile = _mcp_sql_context()
    proj = (project or await _active_sql_project()).strip()
    access_err = await sql_query_memory.check_user_project_access(
        project_slug=proj,
        tenant_id=tenant,
        user_id=user,
    )
    if access_err:
        return access_err
    hits = await sql_query_memory.search(
        request_text=request,
        project_slug=proj,
        tenant_id=tenant,
        user_id=user,
        profile_slug=profile,
        sql_draft=sql_draft or None,
        limit=5,
        verified_only=verified_only,
    )
    return sql_query_memory.format_search_results_markdown(hits)


@mcp.tool()
async def save_successful_sql(
    request: str,
    sql: str,
    project: str = "",
    is_verified: bool = False,
    tables_used: Optional[List[str]] = None,
) -> str:
    """
    [SQL QUERY MEMORY ONLY] Save a verified PostgreSQL query to the drawer.
    Do NOT use for PromQL. Use is_verified=True only after correct results.
    """
    if not sql_query_memory_enabled():
        return "SQL QueryMemory disabled (AION_SQL_QM_ENABLED=0)."
    tenant, user, profile = _mcp_sql_context()
    proj = (project or await _active_sql_project()).strip()
    access_err = await sql_query_memory.check_user_project_access(
        project_slug=proj,
        tenant_id=tenant,
        user_id=user,
    )
    if access_err:
        return access_err
    eid = await sql_query_memory.save(
        request_text=request,
        sql_text=sql,
        project_slug=proj,
        tenant_id=tenant,
        user_id=user,
        profile_slug=profile,
        is_verified=is_verified,
        tables_used=tables_used,
    )
    return (
        f"SQL query saved (id={eid}) in project '{proj}'."
        if eid >= 0
        else "Save failed."
    )


@mcp.tool()
async def mark_sql_query_successful(id: int, project: str = "") -> str:
    """[SQL ONLY] Increment successes; auto-verify after configured threshold."""
    tenant, user, profile = _mcp_sql_context()
    active = await _bound_sql_project(project)
    ok, err = await sql_query_memory.increment_success(
        id,
        user_id=user,
        tenant_id=tenant,
        profile_slug=profile,
        project_slug=active,
    )
    if ok:
        return f"Success recorded for SQL query id={id}."
    return await sql_query_memory.resolve_mutation_error_message(
        err, entry_id=id, project_slug=active
    )


@mcp.tool()
async def list_sql_projects() -> str:
    """[SQL ONLY] Active chat-ui project metadata (listing/switching is not allowed mid-turn)."""
    if not sql_query_memory_enabled():
        return "SQL QueryMemory disabled (AION_SQL_QM_ENABLED=0)."
    from src.runtime.sql_query_project_scope import block_project_list_tool

    blocked = block_project_list_tool(
        "list_sql_projects", os.getenv("AION_CHAT_SESSION_ID")
    )
    if blocked:
        return blocked
    tenant, user, profile = _mcp_sql_context()
    active = await _active_sql_project()
    access_err = await sql_query_memory.check_user_project_access(
        project_slug=active,
        tenant_id=tenant,
        user_id=user,
    )
    if access_err:
        return access_err
    row = await sql_query_memory.get_active_project_for_user(
        project_slug=active,
        tenant_id=tenant,
        user_id=user,
    )
    if not row:
        return f"No access to SQL project '{active}'."
    return (
        f"Active SQL QueryMemory project (chat-ui): **{row.display_name}** (`{row.slug}`)\n"
        f"Role: {row.role or 'member'}\n"
        f"{row.description or ''}"
    ).strip()


@mcp.tool()
async def list_saved_sql(
    project: str = "",
    limit: int = 50,
    verified_only: bool = False,
) -> str:
    """
    [SQL QUERY MEMORY ONLY] List saved PostgreSQL queries in a project drawer (full inventory).
    Use this to count or browse all cached SQL — NOT semantic search (use search_known_sql for that).
    Do NOT use for PromQL.
    """
    if not sql_query_memory_enabled():
        return "SQL QueryMemory disabled (AION_SQL_QM_ENABLED=0)."
    tenant, user, profile = _mcp_sql_context()
    proj = (project or await _active_sql_project()).strip()
    access_err = await sql_query_memory.check_user_project_access(
        project_slug=proj,
        tenant_id=tenant,
        user_id=user,
    )
    if access_err:
        return access_err
    rows = await sql_query_memory.list_queries(
        project_slug=proj,
        tenant_id=tenant,
        user_id=user,
        verified_only=verified_only,
        limit=min(max(limit, 1), 200),
    )
    return sql_query_memory.format_list_results_markdown(rows, project_slug=proj)


@mcp.tool()
async def delete_sql_memory_entry(id: int, project: str = "") -> str:
    """[SQL ONLY] Delete a SQL query from the active project cache."""
    tenant, user, profile = _mcp_sql_context()
    active = await _bound_sql_project(project)
    ok, err = await sql_query_memory.delete_entry(
        id,
        user_id=user,
        tenant_id=tenant,
        profile_slug=profile,
        project_slug=active,
    )
    if ok:
        return f"SQL query {id} deleted from project '{active}'."
    return await sql_query_memory.resolve_mutation_error_message(
        err, entry_id=id, project_slug=active
    )


@mcp.tool()
async def update_sql_memory_entry(
    id: int,
    user_request: str = None,
    sql: str = None,
    is_verified: bool = None,
    project: str = "",
) -> str:
    """[SQL ONLY] Update NL request, SQL, or verified flag in the active project."""
    tenant, user, profile = _mcp_sql_context()
    active = await _bound_sql_project(project)
    ok, err = await sql_query_memory.update_entry(
        id,
        user_request=user_request,
        sql_text=sql,
        is_verified=is_verified,
        user_id=user,
        tenant_id=tenant,
        profile_slug=profile,
        project_slug=active,
    )
    if ok:
        return f"SQL query {id} updated in project '{active}'."
    return await sql_query_memory.resolve_mutation_error_message(
        err, entry_id=id, project_slug=active
    )


if __name__ == "__main__":
    import asyncio
    import traceback
    from mcp.server.stdio import stdio_server

    async def main():
        try:
            async with stdio_server() as (read_stream, write_stream):
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(),
                )
        except Exception as e:
            with open("data/mcp_debug.log", "a") as f:
                f.write(f"\n--- MEMORY CRASH ---\n{traceback.format_exc()}\n")
            raise e

    asyncio.run(main())
