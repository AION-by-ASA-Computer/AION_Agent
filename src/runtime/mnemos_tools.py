"""Built-in in-process Mnemos memory tools."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, List, Optional

from haystack.tools import Tool

from src.memory.mnemos.orchestrator import mnemos_orchestrator
from src.runtime.mnemos_context import get_mnemos_turn_context


MNEMOS_BUILTIN_TOOL_NAMES = (
    "memory_recall",
    "memory_note",
    "memory_forget",
)


def mnemos_native_tools_enabled() -> bool:
    return os.getenv("AION_MNEMOS_NATIVE_TOOLS", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def profile_wants_mnemos(profile) -> bool:
    groups = getattr(profile, "native_tool_groups", None) or []
    return "mnemos" in groups


def _run_async(coro) -> Any:
    from src.main import _GLOBAL_LOOP

    loop = _GLOBAL_LOOP
    if not loop:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            pass
    if not loop:
        raise RuntimeError("No event loop for Mnemos tools")
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=float(os.getenv("AION_MNEMOS_TOOL_TIMEOUT_SEC", "60")))


def _resolve_ctx(
    session_id: str,
    user_id: str,
    profile_slug: str,
) -> tuple[str, str, str, Optional[str]]:
    turn = get_mnemos_turn_context(session_id)
    if turn and turn.session_id == session_id:
        return turn.tenant_id, turn.user_id, turn.profile_slug, turn.project_slug
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    return tenant, user_id, profile_slug, None


def build_memory_recall_tool(
    session_id: str, user_id: str, profile=None
) -> Tool:
    _ = profile

    def memory_recall(
        query: str,
        scope: str = "auto",
        mode: str = "current",
    ) -> str:
        tenant, uid, _prof, project = _resolve_ctx(session_id, user_id, "")
        rows = _run_async(
            mnemos_orchestrator.recall_notes(
                tenant_id=tenant,
                user_id=uid,
                query=query,
                scope_name=scope,
                mode=mode,
                active_project_slug=project,
            )
        )
        return json.dumps({"results": rows}, ensure_ascii=False)

    return Tool(
        name="memory_recall",
        description=(
            "Search long-term Mnemos memory notes by text. Default scope=auto searches "
            "user + active project. Use for stored facts/lessons (e.g. product features). "
            "Do NOT use for raw chat history (use session_search on memory MCP)."
        ),
        function=memory_recall,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search query"},
                "scope": {
                    "type": "string",
                    "enum": ["auto", "user", "project", "global"],
                    "default": "auto",
                    "description": "auto = user + active project (recommended)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["current", "historical"],
                    "default": "current",
                },
            },
            "required": ["query"],
        },
    )


def build_memory_note_tool(
    session_id: str, user_id: str, profile=None
) -> Tool:
    _ = profile

    def memory_note(
        text: str,
        scope: str = "user",
        category: str = "fact",
        importance: int = 4,
    ) -> str:
        tenant, uid, _prof, project = _resolve_ctx(session_id, user_id, "")
        out = _run_async(
            mnemos_orchestrator.add_note(
                tenant_id=tenant,
                user_id=uid,
                text=text,
                scope_name=scope,
                category=category,
                importance=importance,
                active_project_slug=project,
                source_session_id=session_id,
            )
        )
        return json.dumps(out, ensure_ascii=False)

    return Tool(
        name="memory_note",
        description=(
            "Persist a durable memory note when the user explicitly asks to remember "
            "something in this turn."
        ),
        function=memory_note,
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "One-line note, max 500 chars"},
                "scope": {
                    "type": "string",
                    "enum": ["user", "project", "global"],
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "preference",
                        "fact",
                        "event",
                        "decision",
                        "pitfall",
                        "task",
                    ],
                },
                "importance": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["text"],
        },
    )


def build_memory_forget_tool(
    session_id: str, user_id: str, profile=None
) -> Tool:
    _ = session_id, user_id, profile

    def memory_forget(note_id: int) -> str:
        ok = _run_async(mnemos_orchestrator.forget(note_id, hard=False))
        return json.dumps({"ok": ok, "note_id": note_id}, ensure_ascii=False)

    return Tool(
        name="memory_forget",
        description="Mark a memory note as superseded when the user requests correction/deletion.",
        function=memory_forget,
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "LTM note id to forget"},
            },
            "required": ["note_id"],
        },
    )


def load_mnemos_tools(
    profile, session_id: str, user_id: str
) -> List[Tool]:
    if not mnemos_native_tools_enabled() or not profile_wants_mnemos(profile):
        return []
    return [
        build_memory_recall_tool(session_id, user_id, profile),
        build_memory_note_tool(session_id, user_id, profile),
        build_memory_forget_tool(session_id, user_id, profile),
    ]
