"""MemPalace navigation hooks: pre-turn inject + post-tool auto-learn (project-scoped wings)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from src.memory.ltm_orchestrator import LTMOrchestrator
from src.memory.project_memory_scope import (
    duplicate_check_threshold,
    mempalace_nav_auto_kg_enabled,
    mempalace_nav_auto_learn_enabled,
    mempalace_nav_enabled,
    nav_inject_threshold,
    nav_pre_turn_inject_enabled,
    nav_search_limit,
    normalize_nav_room,
    project_wing,
    resolve_project_slug,
    room_hints_from_query,
)
from src.runtime.hooks import HookContext, hook_registry
from src.runtime.mcp_tool_result import classify_tool_result_text
from src.runtime.query_memory_hooks import profile_wants_sql_query_memory_by_slug

logger = logging.getLogger("aion.mempalace.nav.hooks")

_SQL_QUERY_TOOL_NAMES = frozenset(
    {"query", "execute_sql", "run_sql", "sql_query", "mysql_query", "postgres_query"}
)

_READ_ONLY_NAV_PATTERNS = (
    "qui in chat",
    "in chat",
    "incolla",
    "paste",
    "testo completo",
    "contenuto della skill",
    "scrivimi il testo",
    "scrivi qui",
    "mostra il contenuto",
    "leggi la skill",
    "read the skill",
    "skill_view",
)


def user_requests_navigation_docs_only(user_input: str) -> bool:
    """True when the user wants skill/memory text in chat, not SQL or MemPalace writes."""
    t = (user_input or "").lower()
    if not t.strip():
        return False
    nav_doc = any(
        k in t
        for k in (
            "db_navigation",
            "navigation map",
            "mappa navigazione",
            "skill db_",
        )
    ) or (
        "skill" in t
        and any(k in t for k in ("leggi", "read", "incolla", "paste", "scrivi"))
    )
    if not nav_doc:
        return False
    if any(
        k in t
        for k in ("select ", " query", "sql", "quanti", "count(", "join ", "postgres")
    ):
        return False
    return any(p in t for p in _READ_ONLY_NAV_PATTERNS)


def profile_wants_mempalace_navigation(profile_slug: str) -> bool:
    try:
        from src.agent_profile import profile_manager

        p = profile_manager.get_profile(profile_slug)
        if not p:
            return False
        servers = set(p.mcp_servers or [])
        return "mempalace" in servers and profile_wants_sql_query_memory_by_slug(
            profile_slug
        )
    except Exception:
        return False


async def _call_mempalace(
    session_id: Optional[str], tool: str, arguments: Dict[str, Any]
) -> Optional[str]:
    from src.memory.ltm_orchestrator import _call_mcp_optional

    return await _call_mcp_optional(session_id, tool, arguments)


def _parse_search_hits(raw: str) -> List[Tuple[float, str, str, str]]:
    """Return list of (similarity, text, wing, room)."""
    if not (raw or "").strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [(0.8, raw.strip()[:500], "", "")]

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        if isinstance(data, list):
            results = data
        else:
            return [(0.8, raw.strip()[:500], "", "")]

    out: List[Tuple[float, str, str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or item.get("content") or "").strip()
        if not text:
            continue
        sim = item.get("similarity", item.get("score", 0.75))
        try:
            sim_f = float(sim)
        except (TypeError, ValueError):
            sim_f = 0.75
        wing = str(item.get("wing") or "")
        room = str(item.get("room") or "")
        out.append((sim_f, text, wing, room))
    return out


def _format_inject_block(
    project_slug: str, hits: List[Tuple[float, str, str, str]]
) -> str:
    wing = project_wing(project_slug)
    lines = [
        f"\n\n## MemPalace navigation (progetto `{project_slug}`, wing `{wing}`)",
        "Project set by chat-ui: do not pass `wing` on MemPalace tools.",
        "Verified paths/JOINs/entry points — reuse before exploring schema:\n",
    ]
    for sim, text, wing_h, room in hits:
        loc = f"{wing_h}/{room}" if wing_h and room else (room or wing_h or wing)
        preview = text.replace("\n", " ")[:450]
        lines.append(f"- [sim={sim:.2f} {loc}] {preview}")
    return "\n".join(lines)


def _skip_nav_when_sql_injected(ctx: HookContext) -> bool:
    if os.getenv("AION_MEMPALACE_NAV_SKIP_WHEN_SQL_INJECT", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return False
    merged = ctx.modified_payload or {}
    return bool((merged.get("sql_query_memory_inject") or "").strip())


async def _pre_turn_mempalace_navigation(ctx: HookContext) -> None:
    if not mempalace_nav_enabled():
        return
    profile = ctx.profile or ""
    if not profile_wants_mempalace_navigation(profile):
        return
    try:
        from src.runtime.datasource_memory_mode import (
            datasource_nav_pre_turn_enabled,
            datasource_orchestrator_enabled,
        )

        if datasource_orchestrator_enabled():
            if not datasource_nav_pre_turn_enabled():
                return
        elif not nav_pre_turn_inject_enabled():
            return
    except Exception:
        if not nav_pre_turn_inject_enabled():
            return
    if _skip_nav_when_sql_injected(ctx):
        logger.debug("mempalace nav pre_turn skipped: QueryMemory SQL already injected")
        return
    user_input = (ctx.payload.get("user_input") or "").strip()
    if not user_input or LTMOrchestrator.is_small_talk(user_input):
        return

    if user_requests_navigation_docs_only(user_input):
        try:
            from src.runtime.sql_query_memory_context import (
                set_mempalace_writes_allowed,
            )

            set_mempalace_writes_allowed(False)
            logger.info("mempalace writes blocked for read-only navigation doc turn")
        except Exception:
            pass

    project = resolve_project_slug(ctx.payload.get("sql_query_project"))
    wing = project_wing(project)
    session_id = ctx.conversation_id
    limit = nav_search_limit()
    threshold = nav_inject_threshold()

    all_hits: List[Tuple[float, str, str, str]] = []
    try:
        raw = await _call_mempalace(
            session_id,
            "mempalace_search",
            {"query": user_input, "wing": wing, "limit": limit},
        )
        all_hits.extend(_parse_search_hits(raw or ""))

        for room in room_hints_from_query(user_input)[:2]:
            raw_r = await _call_mempalace(
                session_id,
                "mempalace_search",
                {"query": user_input, "wing": wing, "room": room, "limit": 3},
            )
            for h in _parse_search_hits(raw_r or ""):
                if h not in all_hits:
                    all_hits.append(h)
    except Exception as exc:
        logger.warning("mempalace nav pre_turn search failed: %s", exc)
        return

    good = [h for h in all_hits if h[0] >= threshold]
    good.sort(key=lambda x: x[0], reverse=True)
    good = good[:limit]
    if not good:
        return

    block = _format_inject_block(project, good)
    merged = dict(ctx.modified_payload or ctx.payload)
    existing = (merged.get("mempalace_nav_inject") or "").strip()
    merged["mempalace_nav_inject"] = (
        (existing + "\n" + block).strip() if existing else block
    )
    ctx.modified_payload = merged


def _extract_sql_from_tool_input(inp: Any) -> Optional[str]:
    if isinstance(inp, str):
        text = inp.strip()
        if "SELECT" in text.upper():
            return text
        try:
            inp = json.loads(text)
        except json.JSONDecodeError:
            return None
    if isinstance(inp, dict):
        for key in ("sql", "query", "statement", "text"):
            val = inp.get(key)
            if isinstance(val, str) and "SELECT" in val.upper():
                return val
    return None


def _tables_from_sql(sql: str) -> List[str]:
    found = re.findall(
        r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        sql,
        flags=re.I,
    )
    return list(dict.fromkeys(t.lower() for t in found))[:6]


def _nav_autolearn_skip_reason(
    *,
    ok: bool,
    tables: List[str],
    error_hint: str,
    output_preview: str,
) -> Optional[str]:
    """Return skip reason string when auto-learn should not persist."""
    err_low = (error_hint or "").lower()
    out_low = (output_preview or "").lower()
    if not ok:
        if "mcperror" in err_low or "mcperror" in out_low:
            return "mcperror"
        if "invalid response" in err_low or "invalid response" in out_low:
            return "invalid_mcp_response"
        if len((error_hint or "").strip()) < 12:
            return "empty_error"
        return None
    if not tables or tables == ["unknown"]:
        return "unknown_tables"
    return None


def _build_nav_drawer_content(
    *,
    user_request: str,
    sql: str,
    ok: bool,
    output_preview: str,
    error_hint: str,
) -> Tuple[str, str]:
    """Return (room, narrative content) for auto-learn drawer — no full SQL."""
    tables = _tables_from_sql(sql)
    tables_s = ", ".join(tables) if tables else ""
    req = user_request[:120].strip()
    if ok and len(tables) >= 2:
        room = "join_paths"
        content = (
            f"Verified path for «{req}»: join tra {tables_s}. "
            f"SQL riutilizzabile in QueryMemory del progetto."
        )
    elif ok and tables:
        room = "entry_points"
        content = (
            f"Entry point for «{req}»: partire da {tables_s}. "
            f"Query validata salvata in QueryMemory."
        )
    else:
        room = "pitfalls"
        lesson = (error_hint or output_preview or "errore query")[:180]
        content = (
            f"«{req}» — lesson: {lesson}. "
            f"Tables involved: {tables_s or 'non identificate'}."
        )
    return normalize_nav_room(room), content[:500]


async def _maybe_add_nav_kg_join(
    session_id: Optional[str],
    tables: List[str],
) -> None:
    if not mempalace_nav_auto_kg_enabled() or len(tables) < 2:
        return
    from src.memory.ltm_orchestrator import _call_mcp

    subj, obj = tables[0], tables[1]
    try:
        await _call_mcp(
            session_id,
            "mempalace_kg_add",
            {
                "subject": subj,
                "predicate": "joins_via",
                "object": obj,
            },
        )
        logger.info(
            "mempalace_nav_auto_kg joins_via %s -> %s session=%s",
            subj,
            obj,
            (session_id or "")[:12],
        )
    except Exception as exc:
        logger.warning("mempalace_nav_auto_kg failed: %s", exc)


async def _maybe_add_nav_drawer(
    session_id: str,
    wing: str,
    room: str,
    content: str,
) -> None:
    if len(content.strip()) < 10:
        return
    dup_raw = await _call_mempalace(
        session_id,
        "mempalace_check_duplicate",
        {"content": content, "threshold": duplicate_check_threshold()},
    )
    if dup_raw:
        try:
            dup = json.loads(dup_raw)
            if isinstance(dup, dict) and dup.get("is_duplicate"):
                logger.debug("mempalace nav skip duplicate wing=%s room=%s", wing, room)
                return
        except json.JSONDecodeError:
            pass

    from src.memory.ltm_orchestrator import _call_mcp

    try:
        await _call_mcp(
            session_id,
            "mempalace_add_drawer",
            {
                "wing": wing,
                "room": room,
                "content": content,
                "added_by": "aion_nav_hook",
            },
        )
        logger.info("mempalace nav auto-learn wing=%s room=%s", wing, room)
    except Exception as exc:
        logger.warning("mempalace_add_drawer nav failed: %s", exc)


async def _post_tool_mempalace_auto_learn(ctx: HookContext) -> None:
    # Deprecated: generic Italian template drawers pollute MemPalace. Keep env off;
    # agents persist rich navigation via mempalace_add_drawer (datasource_memory_protocol).
    if not mempalace_nav_enabled() or not mempalace_nav_auto_learn_enabled():
        return
    profile = ctx.profile or ""
    if not profile_wants_mempalace_navigation(profile):
        return

    tool_name = (ctx.payload.get("tool_name") or "").strip()
    base_name = tool_name.split("-")[-1] if tool_name else ""
    if base_name not in _SQL_QUERY_TOOL_NAMES and not any(
        x in tool_name.lower() for x in ("postgres", "mysql", "sql")
    ):
        return
    if ctx.payload.get("event_type") not in ("tool_end", "tool_error"):
        return

    sql = _extract_sql_from_tool_input(ctx.payload.get("tool_input"))
    if not sql or not re.search(r"\bSELECT\b", sql, re.I):
        return

    output = ctx.payload.get("output") or ctx.payload.get("error") or ""
    text = str(output)
    is_err, err_msg = classify_tool_result_text(text, base_name or "query")
    ok = not is_err and len(text.strip()) > 2
    tables = _tables_from_sql(sql)

    skip = _nav_autolearn_skip_reason(
        ok=ok,
        tables=tables,
        error_hint=err_msg or text[:200],
        output_preview=text[:200],
    )
    if skip:
        logger.info(
            "mempalace_nav_auto_learn skipped reason=%s project=%s",
            skip,
            resolve_project_slug(ctx.payload.get("sql_query_project")),
        )
        return

    if not ok:
        return

    user_request = (
        ctx.payload.get("user_input") or ctx.payload.get("last_user_message") or ""
    ).strip()
    if not user_request:
        user_request = "Query navigazione PostgreSQL"

    project = resolve_project_slug(ctx.payload.get("sql_query_project"))
    wing = project_wing(project)
    session_id = ctx.conversation_id

    room, content = _build_nav_drawer_content(
        user_request=user_request,
        sql=sql,
        ok=ok,
        output_preview=text[:200],
        error_hint=err_msg or text[:200],
    )
    await _maybe_add_nav_drawer(session_id, wing, room, content)
    if len(tables) >= 2:
        await _maybe_add_nav_kg_join(session_id, tables)


def register_db_navigation_mempalace_hooks() -> None:
    try:
        from src.runtime.datasource_memory_mode import datasource_orchestrator_enabled

        if not datasource_orchestrator_enabled():
            hook_registry.register(
                "pre_turn", _pre_turn_mempalace_navigation, priority=35
            )
    except Exception:
        hook_registry.register("pre_turn", _pre_turn_mempalace_navigation, priority=35)
    hook_registry.register("post_tool", _post_tool_mempalace_auto_learn, priority=35)


register_db_navigation_mempalace_hooks()
