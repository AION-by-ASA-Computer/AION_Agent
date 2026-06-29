"""Stable turn message IDs for streaming, Redis recovery, and incremental DB persist."""
from __future__ import annotations

from typing import Optional, Tuple

from src.data.ids import new_uuid7_str


def ensure_turn_message_ids(
    user_message_id: Optional[str],
    assistant_message_id: Optional[str],
) -> Tuple[str, str]:
    """Return non-empty IDs (generate any missing) for every agent turn."""
    uid = (user_message_id or "").strip() or new_uuid7_str()
    aid = (assistant_message_id or "").strip() or new_uuid7_str()
    return uid, aid
