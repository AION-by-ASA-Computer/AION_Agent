"""MemPalace navigation memory per SQL QueryMemory project (wing_proj_{slug})."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from src.memory.project_memory_scope import (
    NAVIGATION_ROOMS,
    project_wing,
    sanitize_project_slug,
)
from src.runtime.mempalace_tool_scope import (
    _GLOBAL_WING_PREFIXES,
    is_legacy_navigation_wing,
)

logger = logging.getLogger("aion.navigation_memory")

_MEMPALACE_SERVER = "mempalace"
# MemPalace drawers: 500 chars is the agent guideline; UI edits must accept stored bodies.
_DRAWER_CONTENT_MAX_CHARS = int(
    os.getenv("AION_MEMPALACE_DRAWER_MAX_CHARS", "20000") or "20000"
)


def drawer_content_max_chars() -> int:
    return _DRAWER_CONTENT_MAX_CHARS


def _enabled() -> bool:
    return os.getenv("AION_MEMPALACE_NAV_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _normalize_drawer_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map MemPalace list/search shapes to a stable API for chat-ui."""
    if not isinstance(raw, dict):
        return {}
    did = raw.get("drawer_id") or raw.get("id")
    text = (
        raw.get("content")
        or raw.get("text")
        or raw.get("preview")
        or raw.get("content_preview")
        or raw.get("document")
        or raw.get("snippet")
        or raw.get("message")
        or raw.get("body")
        or ""
    )
    if isinstance(text, dict):
        text = (
            text.get("text")
            or text.get("content")
            or json.dumps(text, ensure_ascii=False)
        )
    text = str(text).strip()
    preview = text if len(text) <= 500 else f"{text[:500]}…"
    out: Dict[str, Any] = {
        "id": str(did) if did else None,
        "drawer_id": str(did) if did else None,
        "wing": raw.get("wing"),
        "room": raw.get("room"),
        "preview": preview,
        "content": text,
        "text": text,
    }
    if raw.get("metadata") is not None:
        out["metadata"] = raw.get("metadata")
    if raw.get("similarity") is not None:
        out["similarity"] = raw.get("similarity")
    return out


def _parse_mcp_json(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
    if hasattr(raw, "content"):
        parts = []
        for block in getattr(raw, "content", []) or []:
            t = getattr(block, "text", None)
            if t:
                parts.append(t)
        if parts:
            return _parse_mcp_json("".join(parts))
    return {}


async def _call_mempalace(
    chat_session_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    from src.mcp_manager import mcp_manager

    result = await mcp_manager.call_tool_pooled(
        chat_session_id,
        _MEMPALACE_SERVER,
        tool_name,
        arguments,
    )
    return _parse_mcp_json(result)


async def list_wings(chat_session_id: str) -> Dict[str, int]:
    data = await _call_mempalace(chat_session_id, "mempalace_list_wings", {})
    wings = data.get("wings") or {}
    if isinstance(wings, dict):
        return {str(k): int(v) for k, v in wings.items()}
    return {}


async def list_drawers_for_wing(
    chat_session_id: str,
    *,
    wing: str,
    room: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """List drawers for an explicit MemPalace wing (incl. legacy names)."""
    args: Dict[str, Any] = {"wing": wing, "limit": limit}
    if room:
        args["room"] = room
    data = await _call_mempalace(chat_session_id, "mempalace_list_drawers", args)
    drawers = data.get("drawers") or data.get("results") or []
    if isinstance(drawers, list):
        return [_normalize_drawer_row(d) for d in drawers if isinstance(d, dict)]
    return []


async def list_drawers(
    chat_session_id: str,
    *,
    project_slug: str,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    resolved_wing = wing or project_wing(sanitize_project_slug(project_slug))
    args: Dict[str, Any] = {"wing": resolved_wing, "limit": limit}
    if room:
        args["room"] = room
    data = await _call_mempalace(chat_session_id, "mempalace_list_drawers", args)
    drawers = data.get("drawers") or data.get("results") or []
    if isinstance(drawers, list):
        return [_normalize_drawer_row(d) for d in drawers if isinstance(d, dict)]
    return []


async def get_drawer(
    chat_session_id: str,
    *,
    drawer_id: str,
) -> Dict[str, Any]:
    """Full drawer body (for chat-ui edit)."""
    data = await _call_mempalace(
        chat_session_id,
        "mempalace_get_drawer",
        {"drawer_id": drawer_id},
    )
    if data.get("error"):
        raise ValueError(str(data.get("error")))
    return _normalize_drawer_row(
        {
            "drawer_id": data.get("drawer_id") or drawer_id,
            "wing": data.get("wing"),
            "room": data.get("room"),
            "content": data.get("content"),
            "metadata": data.get("metadata"),
        }
    )


async def search_drawers(
    chat_session_id: str,
    *,
    project_slug: str,
    wing: Optional[str] = None,
    query: str,
    room: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    resolved_wing = wing or project_wing(sanitize_project_slug(project_slug))
    lim = limit or int(os.getenv("AION_MEMPALACE_NAV_SEARCH_LIMIT", "5"))
    args: Dict[str, Any] = {"wing": resolved_wing, "query": query, "limit": lim}
    if room:
        args["room"] = room
    data = await _call_mempalace(chat_session_id, "mempalace_search", args)
    hits = data.get("results") or data.get("drawers") or []
    if isinstance(hits, list):
        return [_normalize_drawer_row(h) for h in hits if isinstance(h, dict)]
    return []


async def delete_drawer(
    chat_session_id: str,
    *,
    drawer_id: str,
) -> Dict[str, Any]:
    return await _call_mempalace(
        chat_session_id,
        "mempalace_delete_drawer",
        {"drawer_id": drawer_id},
    )


async def add_drawer(
    chat_session_id: str,
    *,
    project_slug: str,
    room: str,
    content: str,
) -> Dict[str, Any]:
    slug = sanitize_project_slug(project_slug)
    wing = project_wing(slug)
    room_norm = (room or "discoveries").strip().lower()
    if room_norm not in NAVIGATION_ROOMS:
        room_norm = "discoveries"
    return await _call_mempalace(
        chat_session_id,
        "mempalace_add_drawer",
        {
            "wing": wing,
            "room": room_norm,
            "content": (content or "").strip()[:_DRAWER_CONTENT_MAX_CHARS],
            "added_by": "chat_ui",
        },
    )


async def upsert_drawer(
    chat_session_id: str,
    *,
    project_slug: str,
    room: str,
    content: str,
    drawer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """MemPalace has no update API: replace drawer by delete + add."""
    if drawer_id:
        await delete_drawer(chat_session_id, drawer_id=drawer_id)
    return await add_drawer(
        chat_session_id,
        project_slug=project_slug,
        room=room,
        content=content,
    )


async def prune_legacy_wings(
    chat_session_id: str,
    *,
    dry_run: bool = True,
    include_agent_procedures: bool = False,
) -> Tuple[List[str], List[str]]:
    """
    Remove drawers in wings that are not wing_proj_* and not global user/session wings.
    Returns (would_delete_or_deleted_wing_names, skipped_global_wings).
    """
    wings = await list_wings(chat_session_id)
    to_prune: List[str] = []
    skipped: List[str] = []
    for wing_name in wings:
        w = wing_name.strip().lower()
        if any(w.startswith(p) for p in _GLOBAL_WING_PREFIXES):
            skipped.append(wing_name)
            continue
        if w.startswith("wing_proj_"):
            skipped.append(wing_name)
            continue
        if w == "agent_procedures" and not include_agent_procedures:
            skipped.append(wing_name)
            continue
        if is_legacy_navigation_wing(wing_name) or not w.startswith("wing_proj_"):
            to_prune.append(wing_name)

    deleted: List[str] = []
    if dry_run:
        return to_prune, skipped

    for wing_name in to_prune:
        drawers = await _call_mempalace(
            chat_session_id,
            "mempalace_list_drawers",
            {"wing": wing_name, "limit": 500},
        )
        items = drawers.get("drawers") or []
        for d in items:
            did = d.get("id") or d.get("drawer_id")
            if did:
                await delete_drawer(chat_session_id, drawer_id=str(did))
        deleted.append(wing_name)
        logger.info("pruned legacy wing %s", wing_name)
    return deleted, skipped


def navigation_status(
    *,
    project_slug: str,
    drawer_count: int = 0,
) -> Dict[str, Any]:
    slug = sanitize_project_slug(project_slug)
    return {
        "enabled": _enabled(),
        "project_slug": slug,
        "wing": project_wing(slug),
        "rooms": list(NAVIGATION_ROOMS),
        "drawer_count": drawer_count,
    }
