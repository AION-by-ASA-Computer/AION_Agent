"""Datasource Memory Workflow: standard agent process for SQL metadata profiles."""
from __future__ import annotations

import os
from typing import FrozenSet, Optional

DEFAULT_DATASOURCE_BLOCKED_PROMQL_TOOLS: FrozenSet[str] = frozenset(
    {
        "search_known_query",
        "save_successful_query",
        "mark_query_as_successful",
        "list_saved_queries",
        "update_memory_entry",
        "delete_memory_entry",
    }
)

_SAME_TURN_REMINDER = (
    "\n\n[datasource_persist_reminder] You explored or verified a new SQL path but have not "
    "persisted yet. Before the final answer: call `sql_memory_save` (parameterized SQL, "
    "`is_verified=true`) and `mempalace_add_drawer` when a reusable join path or convention "
    "was discovered. Do not dump raw list_tables output into MemPalace."
)


def datasource_memory_workflow_enabled(profile=None) -> bool:
    raw = os.getenv("AION_DATASOURCE_MEMORY_WORKFLOW", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if profile is None:
        return True
    from src.runtime.sql_query_memory_tools import profile_wants_sql_query_memory

    return profile_wants_sql_query_memory(profile)


def datasource_max_list_tables() -> int:
    raw = (os.getenv("AION_DATASOURCE_MAX_LIST_TABLES") or "3").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 3
    return max(0, n)


def datasource_persist_reminder_enabled() -> bool:
    return os.getenv("AION_DATASOURCE_PERSIST_REMINDER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def datasource_blocked_promql_tool_names() -> set[str]:
    raw = (os.getenv("AION_DATASOURCE_BLOCKED_PROMQL_TOOLS") or "").strip()
    if raw:
        return {t.strip() for t in raw.split(",") if t.strip()}
    return set(DEFAULT_DATASOURCE_BLOCKED_PROMQL_TOOLS)


def datasource_orchestrator_enabled() -> bool:
    return os.getenv("AION_DATASOURCE_MEMORY_ORCHESTRATOR", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def datasource_nav_pre_turn_enabled() -> bool:
    """MemPalace nav inject on for datasource profiles (overrides global opt-in default)."""
    if os.getenv("AION_DATASOURCE_NAV_PRE_TURN_INJECT", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return False
    return True


def same_turn_persist_reminder_text() -> str:
    return _SAME_TURN_REMINDER


def profile_uses_wren_engine(profile) -> bool:
    """True when the profile routes SQL through Wren CLI instead of toolbox MCP."""
    if profile is None:
        return False
    skills = set(profile.skills or [])
    if "wren" in skills or "wren_guide" in skills:
        return True
    return bool(getattr(profile, "wren_project_path", None))


def build_datasource_memory_system_prompt(profile=None) -> str:
    max_lt = datasource_max_list_tables()
    if profile_uses_wren_engine(profile):
        return (
            "\n\n## DATASOURCE MEMORY WORKFLOW (mandatory — Wren Engine)\n"
            "Wren semantic-layer assistant: follow this process every data turn.\n\n"
            "### Required flow\n"
            "1. **SEARCH** — `sql_memory_search` + `mempalace_search` (skip only when the turn "
            "header includes **QueryMemory — server cache**).\n"
            "2. **EXPLORE** — `sandbox_exec_allowlisted([\"wren\", \"context\", \"show\"])` "
            "or `wren memory fetch` when memory extra is installed; max **2** Wren context "
            "calls per turn before asking the user.\n"
            "3. **EXECUTE** — `sandbox_exec_allowlisted([\"wren\", \"--sql\", \"<SELECT>\", "
            "\"-o\", \"table\"], timeout_sec=180)` — SQL targets MDL model names.\n"
            "4. **PERSIST** — before the final answer when this turn verified a **new reusable** path:\n"
            "   - `sql_memory_save` / `save_successful_sql`: parameterized SQL + intent template "
            "(`is_verified=true`)\n"
            "   - `mempalace_add_drawer`: ONE concise lesson (`join_paths` / `heuristics` / `pitfalls`)\n"
            "5. **ANSWER** — after step 4 when steps 2–3 involved new exploration.\n\n"
            "### What to persist (you decide)\n"
            "- Reusable join path for a **class** of questions (not one person's name)\n"
            "- Schema convention (e.g. operational schema for asset queries)\n"
            "- Pitfall (wrong model name, apostrophe in names)\n\n"
            "### What NOT to persist\n"
            "- Raw `wren context show` dumps / full column lists for every model\n"
            "- Every successful query automatically\n"
            "- Duplicate drawers (`mempalace_check_duplicate` first)\n\n"
            "### Tool disambiguation\n"
            "- `sql_memory_save` / `save_successful_sql` — SQL only; **do not pass `project`** (fixed by chat-ui)\n"
            "- `search_known_query` / `save_successful_query` — **PromQL only** (not on this profile)\n"
            "- Do **not** use `toolbox-postgres` on this profile — Wren only.\n"
            "See skills `wren` and `datasource_memory_protocol`.\n"
        )
    return (
        "\n\n## DATASOURCE MEMORY WORKFLOW (mandatory)\n"
        "Relational datasource assistant: follow this process every data turn.\n\n"
        "### Required flow\n"
        "1. **SEARCH** — `sql_memory_search` + `mempalace_search` (skip only when the turn "
        "header includes **QueryMemory — server cache**).\n"
        f"2. **EXPLORE** — targeted `list_tables` with `schema_name` from project description; "
        f"max **{max_lt}** `list_tables` calls per turn before asking the user.\n"
        "3. **EXECUTE** — read-only `execute_sql` (SELECT).\n"
        "4. **PERSIST** — before the final answer when this turn verified a **new reusable** path:\n"
        "   - `sql_memory_save` / `save_successful_sql`: parameterized SQL + intent template "
        "(`is_verified=true`)\n"
        "   - `mempalace_add_drawer`: ONE concise lesson (`join_paths` / `heuristics` / `pitfalls`)\n"
        "5. **ANSWER** — after step 4 when steps 2–3 involved new exploration.\n\n"
        "### What to persist (you decide)\n"
        "- Reusable join path for a **class** of questions (not one person's name)\n"
        "- Schema convention (e.g. operational schema for asset queries)\n"
        "- Pitfall (wrong table name, apostrophe in names)\n\n"
        "### What NOT to persist\n"
        "- Raw `list_tables` dumps / full column lists for every table\n"
        "- Every successful query automatically\n"
        "- Duplicate drawers (`mempalace_check_duplicate` first)\n\n"
        "### Tool disambiguation\n"
        "- `sql_memory_save` / `save_successful_sql` — SQL only; **do not pass `project`** (fixed by chat-ui)\n"
        "- `sql_memory_update` / `update_sql_memory_entry` — fix saved SQL by id (`sql_memory_list_saved` for ids)\n"
        "- `sql_memory_delete` / `delete_sql_memory_entry` — remove obsolete saved SQL by id\n"
        "- `search_known_query` / `save_successful_query` — **PromQL only** (not on this profile)\n"
        "- You **cannot** list or switch QueryMemory projects — only the active chat-ui project is available.\n"
        "See skill `datasource_memory_protocol` for drawer format and examples.\n"
    )


def profile_slug_wants_datasource_workflow(profile_slug: str) -> bool:
    try:
        from src.agent_profile import profile_manager
        from src.runtime.query_memory_hooks import profile_wants_sql_query_memory_by_slug

        if not profile_wants_sql_query_memory_by_slug(profile_slug):
            return False
        return datasource_memory_workflow_enabled()
    except Exception:
        return False


def maybe_append_same_turn_reminder(
    *,
    session_id: Optional[str],
    profile_slug: Optional[str],
    tool_name: str,
    event_type: str,
    output: object,
) -> str:
    """Soft nudge appended to tool output when exploration happened without persist."""
    text = str(output or "")
    if not datasource_persist_reminder_enabled():
        return text
    if event_type != "tool_end":
        return text
    if not profile_slug_wants_datasource_workflow(profile_slug or ""):
        return text
    from src.runtime.exploration_tracker import needs_persist_reminder

    if not needs_persist_reminder(session_id):
        return text
    base = _tool_base(tool_name)
    if base not in _EXPLORATION_NOTIFY_SUFFIXES:
        return text
    if _SAME_TURN_REMINDER.strip() in text:
        return text
    return text + _SAME_TURN_REMINDER


_EXPLORATION_NOTIFY_SUFFIXES = frozenset(
    {
        "list_tables",
        "list_schemas",
        "execute_sql",
        "query",
        "run_sql",
        "sql_query",
        "mysql_query",
        "postgres_query",
    }
)


def _tool_base(tool_name: str) -> str:
    return (tool_name or "").split("-")[-1].strip().lower()


def block_list_tables_if_budget_exceeded(
    server_name: str,
    tool_name: str,
    session_id: str,
) -> Optional[str]:
    """Soft block when list_tables budget exceeded for datasource workflow turns."""
    base = _tool_base(tool_name)
    if base not in ("list_tables", "list_schemas"):
        return None
    ctx = None
    try:
        from src.runtime.sql_query_memory_context import get_sql_qm_turn_context

        ctx = get_sql_qm_turn_context(session_id)
    except Exception:
        return None
    if ctx is None:
        return None
    if not profile_slug_wants_datasource_workflow(ctx.profile_slug):
        return None
    max_lt = datasource_max_list_tables()
    if max_lt <= 0:
        return None
    if ctx.list_tables_count >= max_lt:
        return (
            f"Blocked `{server_name}/{tool_name}`: datasource workflow allows at most "
            f"{max_lt} `list_tables` calls per turn. Search `sql_memory_search` and "
            f"`mempalace_search` first, or ask the user to disambiguate schema/table."
        )
    return None


def record_list_tables_call(session_id: str) -> None:
    from src.runtime.sql_query_memory_context import increment_list_tables_count

    increment_list_tables_count(session_id)
