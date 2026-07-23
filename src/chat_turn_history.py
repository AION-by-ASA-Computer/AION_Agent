"""Collapse spurious per-step assistant rows when serving chat history."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence, TypeVar

from src.data.message_roles import normalize_message_role

T = TypeVar("T")


def _message_metadata_dict(row: Any) -> Dict[str, Any]:
    raw_meta = getattr(row, "metadata_json", None)
    if not raw_meta:
        return {}
    try:
        parsed = json.loads(raw_meta)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _assistant_rank(
    row: Any,
    *,
    steps_by_msg: Dict[str, List[Any]],
    atts_by_msg: Dict[str, List[Any]],
) -> tuple[int, int, int, int, int]:
    mid = str(getattr(row, "id", "") or "")
    return (
        len(steps_by_msg.get(mid, [])),
        len(atts_by_msg.get(mid, [])),
        len((getattr(row, "reasoning", None) or "").strip()),
        len((getattr(row, "content", None) or "").strip()),
        len((getattr(row, "timeline_json", None) or "").strip()),
    )


def _is_memorization_assistant(row: Any) -> bool:
    meta = _message_metadata_dict(row)
    return bool((meta.get("memorized_message_id") or "").strip())


def _group_messages_by_user_turn(messages: Sequence[T]) -> List[List[T]]:
    if not messages:
        return []
    turns: List[List[T]] = []
    current: List[T] = []
    for row in messages:
        if normalize_message_role(getattr(row, "role", None)) == "user" and current:
            turns.append(current)
            current = [row]
        else:
            current.append(row)
    if current:
        turns.append(current)
    return turns


def collapse_redundant_assistant_fragments(
    messages: Sequence[T],
    *,
    steps_by_msg: Dict[str, List[Any]],
    atts_by_msg: Dict[str, List[Any]],
) -> List[T]:
    """Keep one primary assistant per user turn; always retain memorization replies."""
    if not messages:
        return []

    collapsed: List[T] = []
    for turn in _group_messages_by_user_turn(messages):
        assistants = [
            m
            for m in turn
            if normalize_message_role(getattr(m, "role", None)) == "assistant"
        ]
        if len(assistants) <= 1:
            collapsed.extend(turn)
            continue

        keep_ids: set[str] = set()
        for row in assistants:
            if _is_memorization_assistant(row):
                keep_ids.add(str(row.id))

        non_memo = [row for row in assistants if str(row.id) not in keep_ids]
        if len(non_memo) > 1:
            anchor = max(
                non_memo,
                key=lambda row: _assistant_rank(
                    row, steps_by_msg=steps_by_msg, atts_by_msg=atts_by_msg
                ),
            )
            keep_ids.add(str(anchor.id))
        else:
            keep_ids.update(str(row.id) for row in non_memo)

        for row in turn:
            if normalize_message_role(getattr(row, "role", None)) != "assistant":
                collapsed.append(row)
            elif str(row.id) in keep_ids:
                collapsed.append(row)
    return collapsed
