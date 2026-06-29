"""Native tools: trigger_research and manage_research."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _parse_args(content: str) -> Dict[str, Any]:
    if not content or not str(content).strip():
        return {}
    raw = str(content).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"topic": raw}


def run_trigger_research(
    content: str,
    *,
    session_id: str = "",
    user_id: str = "",
) -> str:
    """Start a deep research job (in-process). Returns JSON string."""
    from src.research.handler import deep_research_enabled, get_research_handler, new_research_session_id

    if not deep_research_enabled():
        return json.dumps(
            {"error": "Deep research disabled (AION_DEEP_RESEARCH_ENABLED=0)", "exit_code": 1},
            ensure_ascii=False,
        )
    args = _parse_args(content)
    topic = (args.get("topic") or args.get("query") or "").strip()
    if not topic:
        return json.dumps({"error": "topic (or query) is required", "exit_code": 1}, ensure_ascii=False)

    max_rounds = args.get("max_rounds")
    max_time = args.get("max_time")
    category = args.get("category")

    rid = new_research_session_id()
    handler = get_research_handler()
    owner = (user_id or "default").strip() or "default"
    try:
        kwargs: Dict[str, Any] = {"owner": owner}
        if max_rounds is not None:
            try:
                n = int(max_rounds)
                if n > 0:
                    kwargs["max_rounds"] = n
            except (TypeError, ValueError):
                pass
        if max_time is not None:
            try:
                n = int(max_time)
                if n > 0:
                    kwargs["max_time"] = n
            except (TypeError, ValueError):
                pass
        if category:
            kwargs["category"] = str(category)
        if session_id:
            kwargs["chat_session_id"] = session_id.strip()
        handler.start_research(rid, topic, **kwargs)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "exit_code": 1}, ensure_ascii=False)

    payload = {
        "output": (
            f"Deep research started: [{topic}](#research-{rid}). "
            "Open the Deep Research panel to watch progress and read the report."
        ),
        "session_id": rid,
        "research_session_id": rid,
        "anchor": f"[{topic}](#research-{rid})",
        "ui_event": "research_started",
        "query": topic,
        "exit_code": 0,
    }
    return json.dumps(payload, ensure_ascii=False)


def run_manage_research(content: str, *, user_id: str = "") -> str:
    """List, read, or delete saved research. Returns JSON string."""
    from src.research.handler import get_research_handler

    args = _parse_args(content)
    action = (args.get("action") or "list").strip().lower()
    owner = user_id or "anonymous"
    handler = get_research_handler()

    if action in ("delete", "remove"):
        rid = (args.get("id") or args.get("session_id") or "").strip()
        if not rid:
            return json.dumps({"error": "id required for delete", "exit_code": 1}, ensure_ascii=False)
        if not handler.owns(rid, owner):
            return json.dumps({"error": "not found", "exit_code": 1}, ensure_ascii=False)
        handler.delete_research(rid)
        return json.dumps({"output": f"Deleted research {rid}.", "exit_code": 0}, ensure_ascii=False)

    if action in ("read", "open", "view", "get"):
        rid = (args.get("id") or args.get("session_id") or "").strip()
        if not rid:
            return json.dumps({"error": "id required for read", "exit_code": 1}, ensure_ascii=False)
        if not handler.owns(rid, owner):
            return json.dumps({"error": "not found", "exit_code": 1}, ensure_ascii=False)
        result = handler.get_result(rid) or ""
        sources = handler.get_sources(rid) or []
        lines = [result, "", "**Sources:**"]
        for s in sources:
            lines.append(f"- [{s.get('title', s.get('url'))}]({s.get('url')})")
        return json.dumps(
            {
                "output": "\n".join(lines),
                "report_url": f"/research/report/{rid}",
                "exit_code": 0,
            },
            ensure_ascii=False,
        )

    search = (args.get("search") or "").strip()
    items = handler.list_library(owner, search=search, sort="recent", limit=50)
    if not items:
        return json.dumps(
            {"output": "No research found in the library.", "exit_code": 0},
            ensure_ascii=False,
        )
    rows = []
    for it in items:
        q = it.get("query") or "(untitled)"
        sid = it.get("id")
        n = it.get("source_count") or 0
        rows.append(f"- [{q}](#research-{sid}) — {n} sources")
    return json.dumps(
        {"output": "Research library:\n" + "\n".join(rows), "exit_code": 0},
        ensure_ascii=False,
    )
