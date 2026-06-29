"""OpenCode-style <system-reminder> injects for datasource SQL turns."""
from __future__ import annotations

from typing import Optional


def _is_short_follow_up(user_input: str) -> bool:
    text = (user_input or "").strip()
    if len(text) < 48:
        return True
    low = text.lower()
    starters = (
        "yes",
        "no",
        "ok",
        "thanks",
        "grazie",
        "si",
        "sì",
        "continue",
        "go on",
        "proceed",
    )
    return any(low == s or low.startswith(s + " ") or low.startswith(s + ",") for s in starters)


def should_skip_nav_inject(*, cache_hit: bool, user_input: str) -> bool:
    if cache_hit:
        return True
    return False


def should_skip_session_entity_cache(*, user_input: str, cache_hit: bool) -> bool:
    if cache_hit:
        return True
    return _is_short_follow_up(user_input)


def build_turn_state_reminder(
    *,
    cache_hit: bool,
    has_sql_inject: bool,
    needs_persist: bool,
    user_input: str,
) -> Optional[str]:
    """One synthetic reminder per turn (max ~3 lines)."""
    if needs_persist:
        return (
            "<system-reminder>\n"
            "Step PERSIST: you explored or verified a new SQL path. Before the final answer call "
            "`sql_memory_save` (verified SQL) and `mempalace_add_drawer` when a reusable join path applies.\n"
            "</system-reminder>"
        )
    if cache_hit or has_sql_inject:
        return (
            "<system-reminder>\n"
            "QueryMemory cache hit: adapt the cached SQL and call execute_sql. "
            "Skip broad list_tables unless the cache SQL fails.\n"
            "Next assistant message: ONE tool call or a concise answer.\n"
            "</system-reminder>"
        )
    if _is_short_follow_up(user_input):
        return None
    return (
        "<system-reminder>\n"
        "Step SEARCH: call `sql_memory_search` and `mempalace_search` unless the turn header already "
        "includes QueryMemory cache. Then ONE exploration or execute tool — no long thinking loops.\n"
        "</system-reminder>"
    )
