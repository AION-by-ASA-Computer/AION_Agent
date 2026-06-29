"""Pipeline hooks: SQL QueryMemory pre-turn inject and post-tool auto-learn."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from src.memory.sql_query_memory import sql_query_memory, sql_query_memory_enabled
from src.memory.sql_query_memory.fingerprint import normalize_sql
from src.runtime.hooks import HookContext, hook_registry
from src.runtime.sql_query_memory_gate import extract_schemas_from_sql_text
from src.runtime.sql_query_memory_tools import profile_wants_sql_query_memory

logger = logging.getLogger("aion.sql_qm.hooks")

_SQL_QUERY_TOOL_NAMES = frozenset(
    {"query", "execute_sql", "run_sql", "sql_query", "mysql_query", "postgres_query"}
)


def sql_qm_auto_learn_enabled(*, tenant_sql_auto_learn: bool) -> bool:
    """Env master switch (default off). Tenant DB flag applies only when env is on."""
    raw = os.getenv("AION_SQL_QM_AUTO_LEARN", "0").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return bool(tenant_sql_auto_learn)
    return False


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _inject_threshold() -> float:
    return _env_float("AION_SQL_QM_INJECT_THRESHOLD", 0.80)


def _inject_verified_only() -> bool:
    return os.getenv("AION_SQL_QM_INJECT_VERIFIED_ONLY", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


async def _search_inject_candidates(
    *,
    user_input: str,
    project: str,
    tenant_id: str,
    user_id: str,
    profile: str,
) -> list:
    verified_only = _inject_verified_only()
    hits = await sql_query_memory.search(
        request_text=user_input,
        project_slug=project,
        tenant_id=tenant_id,
        user_id=user_id or "default",
        profile_slug=profile,
        limit=5,
        verified_only=verified_only,
    )
    threshold = _inject_threshold()
    good = [h for h in hits if h.score >= threshold]
    if good or verified_only:
        return good
    # Draft/suggested rows are still useful for inject when score is high (common after auto-learn off).
    hits_all = await sql_query_memory.search(
        request_text=user_input,
        project_slug=project,
        tenant_id=tenant_id,
        user_id=user_id or "default",
        profile_slug=profile,
        limit=5,
        verified_only=False,
    )
    return [h for h in hits_all if h.score >= threshold]


async def _pre_turn_sql_query_memory(ctx: HookContext) -> None:
    if not sql_query_memory_enabled():
        return
    try:
        from src.runtime.datasource_memory_mode import datasource_orchestrator_enabled

        if datasource_orchestrator_enabled():
            return
    except Exception:
        pass
    await _run_pre_turn_sql_query_memory(ctx)


async def _run_pre_turn_sql_query_memory(ctx: HookContext) -> None:
    if not sql_query_memory_enabled():
        return
    profile = ctx.profile or ""
    if not profile_wants_sql_query_memory_by_slug(profile):
        return
    settings = await sql_query_memory.get_tenant_settings(ctx.tenant_id)
    if not settings.sql_search_before_run:
        return
    user_input = (ctx.payload.get("user_input") or "").strip()
    if not user_input:
        return
    project = (ctx.payload.get("sql_query_project") or os.getenv("AION_SQL_QM_DEFAULT_PROJECT") or "default").strip()
    try:
        good = await _search_inject_candidates(
            user_input=user_input,
            project=project,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id or "default",
            profile=profile,
        )
    except Exception as exc:
        logger.warning("sql_qm pre_turn search failed: %s", exc)
        return
    if not good:
        return
    good = good[:3]
    max_sql_chars = int(os.getenv("AION_SQL_QM_INJECT_MAX_SQL_CHARS", "2000"))
    all_sql = "\n".join((h.sql_text or "") for h in good)
    schemas = extract_schemas_from_sql_text(all_sql)
    schema_line = ""
    if schemas:
        schema_line = (
            f"\n**Database schemas in cached SQL:** `{', '.join(schemas)}` "
            f"(use these — not other schemas on the same server unless the query fails).\n"
        )
    lines = [
        "\n\n## QueryMemory — server cache (this turn)",
        f"**Active project:** `{project}` — search/save only in this drawer; other projects are ignored.",
        "**Mandatory:** run `execute_sql` with the best cached SQL below before any other tool. "
        "`list_tables`, `sql_memory_search`, `search_known_sql`, and `mempalace_search` are "
        "**blocked** until you get a successful SQL result (server guard).",
        schema_line,
        "Adapt `?` placeholders, then answer. Save only via `sql_memory_save` / `save_successful_sql` if needed.\n",
    ]
    for h in good:
        sql_body = (h.sql_text or "").strip()
        if len(sql_body) > max_sql_chars:
            sql_body = sql_body[: max_sql_chars - 3] + "..."
        lines.append(f"### Cached query id={h.id} score={h.score:.2f}")
        lines.append(f"Original request: \"{h.user_request}\"")
        lines.append(f"```sql\n{sql_body}\n```")
    block = "\n".join(lines)
    merged = dict(ctx.modified_payload or ctx.payload)
    merged["sql_query_memory_inject"] = block
    merged["sql_query_memory_cache_hit"] = True
    merged["sql_query_memory_cache_schemas"] = list(schemas)
    merged["sql_query_memory_cache_hit_ids"] = [h.id for h in good]
    ctx.modified_payload = merged
    logger.info(
        "sql_qm pre_turn inject project=%s hits=%s schemas=%s top_score=%.2f",
        project,
        len(good),
        schemas,
        good[0].score,
    )


def profile_wants_sql_query_memory_by_slug(profile_slug: str) -> bool:
    try:
        from src.agent_profile import profile_manager

        p = profile_manager.get_profile(profile_slug)
        return profile_wants_sql_query_memory(p)
    except Exception:
        return False


def profile_has_memory_capability_by_slug(profile_slug: str) -> bool:
    try:
        from src.agent_profile import profile_manager

        p = profile_manager.get_profile(profile_slug)
        if not p:
            return False
        groups = getattr(p, "native_tool_groups", None) or []
        if "sql_query_memory" in groups:
            return True
        servers = getattr(p, "mcp_servers", None) or []
        return any(s in servers for s in ("memory", "query_memory", "sql_query_memory"))
    except Exception:
        return False


def _extract_sql_from_tool_input(inp: Any) -> Optional[str]:
    if isinstance(inp, str):
        text = inp.strip()
        if text.upper().startswith("SELECT") or "SELECT" in text.upper():
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


def _tool_output_ok(output: Any) -> bool:
    from src.runtime.mcp_tool_result import classify_tool_result_text

    text = str(output or "")
    tool_name = "query"
    is_err, _ = classify_tool_result_text(text, tool_name)
    if is_err:
        return False
    if text.strip().startswith("["):
        return True
    return len(text.strip()) > 2


async def _post_tool_sql_auto_learn(ctx: HookContext) -> None:
    # Deprecated for agent-driven persistence: keep AION_SQL_QM_AUTO_LEARN=0;
    # agents save via sql_memory_save with full SQL (datasource_memory_protocol).
    if not sql_query_memory_enabled():
        return
    profile = ctx.profile or ""
    if not profile_wants_sql_query_memory_by_slug(profile):
        return
    settings = await sql_query_memory.get_tenant_settings(ctx.tenant_id)
    if not sql_qm_auto_learn_enabled(tenant_sql_auto_learn=settings.sql_auto_learn):
        return
    tool_name = (ctx.payload.get("tool_name") or "").strip()
    base_name = tool_name.split("-")[-1] if tool_name else ""
    if base_name not in _SQL_QUERY_TOOL_NAMES and not any(
        x in tool_name.lower() for x in ("postgres", "mysql", "sql")
    ):
        return
    event_type = ctx.payload.get("event_type")
    if event_type not in ("tool_end", "tool_error"):
        return
    output = ctx.payload.get("output") or ctx.payload.get("error")
    if not _tool_output_ok(output):
        return
    sql = _extract_sql_from_tool_input(ctx.payload.get("tool_input"))
    if not sql or not re.search(r"\bSELECT\b", sql, re.I):
        return
    user_request = (ctx.payload.get("user_input") or ctx.payload.get("last_user_message") or "").strip()
    if not user_request:
        user_request = "Query SQL automatica"
    project = (ctx.payload.get("sql_query_project") or os.getenv("AION_SQL_QM_DEFAULT_PROJECT") or "default").strip()
    sql_to_store = normalize_sql(sql) if os.getenv("AION_SQL_QM_PARAMETERIZE", "1").lower() not in (
        "0",
        "false",
        "no",
    ) else sql
    try:
        await sql_query_memory.save(
            request_text=user_request,
            sql_text=sql_to_store,
            project_slug=project,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id or "default",
            profile_slug=profile,
            is_verified=False,
        )
    except Exception as exc:
        logger.debug("sql_qm auto-learn skipped: %s", exc)


def register_query_memory_hooks() -> None:
    try:
        from src.runtime.datasource_memory_mode import datasource_orchestrator_enabled

        if not datasource_orchestrator_enabled():
            hook_registry.register("pre_turn", _pre_turn_sql_query_memory, priority=30)
    except Exception:
        hook_registry.register("pre_turn", _pre_turn_sql_query_memory, priority=30)
    hook_registry.register("post_tool", _post_tool_sql_auto_learn, priority=40)


register_query_memory_hooks()
