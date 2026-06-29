"""Helpers for chat replay / UI visibility (shared by API and tests)."""

from __future__ import annotations

from typing import Any, Dict

from src.data.message_roles import (
    is_empty_technical_message,
    is_ui_visible_role,
    looks_like_internal_content,
    looks_like_raw_plan_content,
    normalize_message_role,
)


def normalize_step_visual(sd: Dict[str, Any], role: str, user_identifier: str) -> None:
    nr = normalize_message_role(role)
    if nr == "user":
        sd["type"] = "user_message"
        sd["name"] = user_identifier
    elif nr == "assistant":
        sd["type"] = "assistant_message"
        sd["name"] = "AION Agent"


def is_step_ui_visible(sd: Dict[str, Any]) -> bool:
    s_type = str(sd.get("type") or "").strip().lower()
    if s_type in ("message", "user_message", "assistant_message"):
        md = sd.get("metadata") or {}
        role = md.get("role")
        return is_ui_visible_role(role)
    return True


def is_replay_visible_message(role: str | None, content: str | None) -> bool:
    nr = normalize_message_role(role)
    if not is_ui_visible_role(nr):
        return False
    if looks_like_internal_content(content):
        return False
    if looks_like_raw_plan_content(content):
        return False
    if is_empty_technical_message(nr, content):
        return False
    return True
