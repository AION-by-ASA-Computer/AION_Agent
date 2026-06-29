"""Resolve active SQL QueryMemory project slug for a chat turn."""

from __future__ import annotations

import os
from typing import Optional


def resolve_sql_query_project(
    *,
    request_project: Optional[str] = None,
    conversation_project: Optional[str] = None,
    env_default: Optional[str] = None,
) -> str:
    """
    Priority: explicit request (chat-ui selector) > conversation metadata > env default.
    """
    explicit = (request_project or "").strip()
    if explicit:
        return explicit
    stored = (conversation_project or "").strip()
    if stored:
        return stored
    fallback = (
        env_default or os.getenv("AION_SQL_QM_DEFAULT_PROJECT") or "default"
    ).strip()
    return fallback or "default"
