"""Force MemPalace navigation tools to use the active SQL QueryMemory project wing."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional, Set

from src.memory.project_memory_scope import project_wing

logger = logging.getLogger("aion.mempalace.scope")

# Tools where `wing` must match the chat-ui project (agent must not pick another wing).
_WING_SCOPED_TOOLS: Set[str] = {
    "mempalace_search",
    "mempalace_add_drawer",
    "mempalace_list_drawers",
    "mempalace_list_rooms",
    "mempalace_check_duplicate",
    "mempalace_sync",
    "mempalace_delete_drawer",
}

_GLOBAL_WING_PREFIXES = (
    "wing_user_",
    "wing_session_context",
    "wing_aion_system",
)

_LEGACY_WING_NAMES = frozenset({"alibr", "navigation", "db_alibr"})

_MEMPALACE_WRITE_TOOLS: Set[str] = {
    "mempalace_add_drawer",
    "mempalace_delete_drawer",
    "mempalace_kg_add",
    "mempalace_kg_invalidate",
    "mempalace_sync",
}


def mempalace_write_blocked_message(tool_name: str) -> Optional[str]:
    """Return user-visible error when mutating MemPalace tools are blocked for this turn."""
    if tool_name not in _MEMPALACE_WRITE_TOOLS:
        return None
    try:
        from src.runtime.sql_query_memory_context import get_sql_qm_turn_context

        ctx = get_sql_qm_turn_context()
    except Exception:
        return None
    if ctx is None or ctx.mempalace_writes_allowed:
        return None
    return (
        f"Tool `{tool_name}` is disabled for this turn (read-only / paste-text request). "
        "Use `mempalace_search` or `mempalace_list_drawers` to read navigation memory; "
        "do not add or delete drawers until the user asks for an explicit update."
    )


def is_global_wing(wing: str) -> bool:
    w = (wing or "").strip().lower()
    return any(w.startswith(p) for p in _GLOBAL_WING_PREFIXES)


def is_project_wing(wing: str, project_slug: Optional[str] = None) -> bool:
    w = (wing or "").strip().lower()
    if not w.startswith("wing_proj_"):
        return False
    if project_slug:
        return w == project_wing(project_slug).lower()
    return True


def is_legacy_navigation_wing(wing: str) -> bool:
    w = (wing or "").strip().lower()
    if w in _LEGACY_WING_NAMES:
        return True
    return bool(w) and not is_global_wing(w) and not w.startswith("wing_proj_")


def apply_mempalace_project_scope(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    force: bool = True,
) -> Dict[str, Any]:
    """
    Override `wing` on navigation tools from turn context (sql_query_project from chat-ui).
    """
    if tool_name not in _WING_SCOPED_TOOLS:
        return arguments
    try:
        from src.runtime.sql_query_memory_context import get_sql_qm_turn_context

        ctx = get_sql_qm_turn_context()
    except Exception:
        ctx = None
    if not ctx or not ctx.project_slug:
        return arguments
    out = dict(arguments or {})
    prev = out.get("wing")
    prev_s = str(prev or "").strip()
    if is_global_wing(prev_s):
        return out
    wing = project_wing(ctx.project_slug)
    if prev_s and (
        is_legacy_navigation_wing(prev_s)
        or (prev_s.lower().startswith("wing_proj_") and prev_s.lower() != wing.lower())
    ):
        logger.info(
            "mempalace scope: wing %s -> %s (tool=%s project=%s)",
            prev,
            wing,
            tool_name,
            ctx.project_slug,
        )
    if force or not prev or is_legacy_navigation_wing(prev_s):
        out["wing"] = wing
    elif prev_s.lower().startswith("wing_proj_") and prev_s.lower() != wing.lower():
        out["wing"] = wing
    return out


def weak_memory_similarity_threshold() -> float:
    try:
        return float(os.getenv("AION_MEMPALACE_WEAK_MEMORY_THRESHOLD", "0.4"))
    except ValueError:
        return 0.4


def enrich_mempalace_tool_result(tool_name: str, result_text: str) -> str:
    """Annotate weak mempalace_search hits so the agent explores instead of trusting noise."""
    if tool_name != "mempalace_search":
        return result_text
    raw = (result_text or "").strip()
    if not raw:
        return result_text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return result_text
    if not isinstance(data, dict):
        return result_text
    results = data.get("results")
    if not isinstance(results, list) or not results:
        data["no_relevant_memory"] = True
        data["suggested_action"] = (
            "No prior navigation memory — explore schema per project description, then persist."
        )
        return json.dumps(data, ensure_ascii=False)
    best = 0.0
    for item in results:
        if not isinstance(item, dict):
            continue
        sim = item.get("similarity", item.get("score", 0.0))
        try:
            best = max(best, float(sim))
        except (TypeError, ValueError):
            continue
    threshold = weak_memory_similarity_threshold()
    if best < threshold:
        data["no_relevant_memory"] = True
        data["best_similarity"] = round(best, 4)
        data["suggested_action"] = (
            "No prior navigation memory above threshold — explore schema per project description, "
            "then persist via sql_memory_save and mempalace_add_drawer."
        )
        return json.dumps(data, ensure_ascii=False)
    return result_text
