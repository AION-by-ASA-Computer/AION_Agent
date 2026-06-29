"""Best-effort timeline reconstruction from legacy flat message fields."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from src.runtime.plan_display import strip_plan_blocks_for_chat_display


def _parse_json_input(raw: Any) -> Any:
    if raw is None:
        return {}
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _sort_key(created_at: Any) -> float:
    if created_at is None:
        return 0.0
    if isinstance(created_at, datetime):
        return created_at.timestamp()
    if isinstance(created_at, str):
        try:
            return datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def reconstruct_timeline_from_legacy(
    *,
    reasoning: Optional[str] = None,
    content: Optional[str] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build TurnSegment-like dicts: reasoning → tools/artifacts by created_at → text."""
    segments: List[Dict[str, Any]] = []

    if (reasoning or "").strip():
        segments.append(
            {
                "kind": "reasoning",
                "id": "reasoning_0",
                "content": reasoning.strip(),
            }
        )

    merged: List[tuple[float, str, Dict[str, Any]]] = []
    for s in steps or []:
        meta: Dict[str, Any] = {}
        meta_raw = s.get("metadata_json")
        if meta_raw:
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else dict(meta_raw)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        merged.append(
            (
                _sort_key(s.get("created_at")),
                "tool",
                {
                    "kind": "tool",
                    "id": str(s.get("id") or ""),
                    "name": str(s.get("name") or "tool"),
                    "input": _parse_json_input(s.get("input")),
                    "output": s.get("output"),
                    "status": "error" if s.get("is_error") else "done",
                    "isError": bool(s.get("is_error")),
                    "tokens_in": meta.get("tokens_in") if isinstance(meta.get("tokens_in"), int) else None,
                    "tokens_out": meta.get("tokens_out") if isinstance(meta.get("tokens_out"), int) else None,
                },
            )
        )

    for a in artifacts or []:
        storage_key = a.get("storage_key") or ""
        merged.append(
            (
                _sort_key(a.get("created_at")),
                "artifact",
                {
                    "kind": "artifact",
                    "id": str(a.get("id") or ""),
                    "title": str(a.get("original_name") or a.get("id") or "artifact"),
                    "artType": str(a.get("mime") or a.get("kind") or "text"),
                    "buffer": "",
                    "savedPath": storage_key,
                },
            )
        )

    merged.sort(key=lambda x: (x[0], 0 if x[1] == "tool" else 1))
    for _, _, seg in merged:
        if seg.get("id"):
            segments.append(seg)

    visible = strip_plan_blocks_for_chat_display(content or "")
    if visible:
        segments.append({"kind": "text", "id": "text_0", "content": visible})

    return segments


def timeline_json_from_legacy(
    *,
    reasoning: Optional[str] = None,
    content: Optional[str] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None,
) -> str:
    segs = reconstruct_timeline_from_legacy(
        reasoning=reasoning,
        content=content,
        steps=steps,
        artifacts=artifacts,
    )
    return json.dumps(segs, ensure_ascii=False)


def parse_timeline_json(raw: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    return data
