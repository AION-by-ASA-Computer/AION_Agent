"""Track DB exploration per turn; remind agent to persist when prior turn skipped saves."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from src.runtime.hooks import HookContext, hook_registry

logger = logging.getLogger("aion.exploration_tracker")

_EXPLORATION_TOOL_SUFFIXES = frozenset(
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
_SAVE_TOOL_SUFFIXES = frozenset(
    {
        "mempalace_add_drawer",
        "sql_memory_save",
        "save_successful_sql",
        "mempalace_kg_add",
    }
)

_REMINDER = (
    "\n\n[exploration_reminder] Previous data turn explored the database but did not persist "
    "discoveries — follow datasource_memory_protocol step 5 (sql_memory_save + mempalace_add_drawer) "
    "before the final answer.\n"
)


@dataclass
class _TurnState:
    list_tables: bool = False
    sql_success: bool = False
    saved: bool = False
    cache_only: bool = False


@dataclass
class _SessionTracker:
    current: _TurnState = field(default_factory=_TurnState)
    pending_reminder: bool = False


_trackers: Dict[str, _SessionTracker] = {}


def _tracker(session_id: Optional[str]) -> _SessionTracker:
    key = (session_id or "default").strip() or "default"
    return _trackers.setdefault(key, _SessionTracker())


def _profile_tracks_exploration(profile_slug: Optional[str]) -> bool:
    if not profile_slug:
        return True
    try:
        from src.runtime.datasource_memory_mode import (
            profile_slug_wants_datasource_workflow,
        )

        return profile_slug_wants_datasource_workflow(profile_slug)
    except Exception:
        return True


def begin_exploration_turn(session_id: Optional[str]) -> Optional[str]:
    """Reset turn state; return one-line reminder if previous turn skipped persistence."""
    tr = _tracker(session_id)
    reminder = _REMINDER if tr.pending_reminder else None
    tr.pending_reminder = False
    tr.current = _TurnState()
    return reminder


def finish_exploration_turn(session_id: Optional[str]) -> None:
    """Flag next turn when this turn explored successfully but did not save."""
    tr = _tracker(session_id)
    cur = tr.current
    if (cur.list_tables or cur.sql_success) and not cur.saved and not cur.cache_only:
        tr.pending_reminder = True
        logger.info(
            "exploration_tracker: session=%s explored without persist (list_tables=%s sql_ok=%s)",
            (session_id or "")[:12],
            cur.list_tables,
            cur.sql_success,
        )


def mark_cache_only_turn(session_id: Optional[str]) -> None:
    """Turn reused server SQL cache only — do not require persist reminder."""
    _tracker(session_id).current.cache_only = True


def needs_persist_reminder(session_id: Optional[str]) -> bool:
    cur = _tracker(session_id).current
    if cur.saved or cur.cache_only:
        return False
    return cur.list_tables or cur.sql_success


def _tool_base(tool_name: str) -> str:
    return (tool_name or "").split("-")[-1].strip().lower()


def record_exploration_tool(
    *,
    session_id: Optional[str],
    tool_name: str,
    event_type: str,
    output: object,
    profile_slug: Optional[str] = None,
) -> None:
    if not _profile_tracks_exploration(profile_slug):
        return
    if event_type not in ("tool_end", "tool_error"):
        return
    base = _tool_base(tool_name)
    cur = _tracker(session_id).current
    if base in _SAVE_TOOL_SUFFIXES and event_type == "tool_end":
        cur.saved = True
        return
    if base in ("list_tables", "list_schemas") and event_type == "tool_end":
        cur.list_tables = True
        return
    if base not in _EXPLORATION_TOOL_SUFFIXES:
        return
    if event_type != "tool_end":
        return
    from src.runtime.mcp_tool_result import classify_tool_result_text

    text = str(output or "")
    is_err, _ = classify_tool_result_text(text, base or "query")
    if not is_err and len(text.strip()) > 2:
        cur.sql_success = True


async def _pre_turn_exploration_reminder(ctx: HookContext) -> None:
    if not _profile_tracks_exploration(ctx.profile):
        return
    reminder = begin_exploration_turn(ctx.conversation_id)
    if not reminder:
        return
    merged = dict(ctx.modified_payload or ctx.payload)
    existing = (merged.get("exploration_reminder") or "").strip()
    merged["exploration_reminder"] = (
        (existing + reminder).strip() if existing else reminder.strip()
    )
    ctx.modified_payload = merged


async def _post_turn_exploration_finish(ctx: HookContext) -> None:
    if not _profile_tracks_exploration(ctx.profile):
        return
    finish_exploration_turn(ctx.conversation_id)


def register_exploration_tracker_hooks() -> None:
    hook_registry.register("pre_turn", _pre_turn_exploration_reminder, priority=5)
    hook_registry.register("post_turn", _post_turn_exploration_finish, priority=5)


register_exploration_tracker_hooks()
