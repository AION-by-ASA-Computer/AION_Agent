"""Shared LLM token/context limits for Haystack agent."""

from __future__ import annotations

import os


def resolve_chat_max_tokens() -> int:
    """Resolve max output tokens for chat generation."""
    from src.settings import get_settings

    settings = get_settings()
    return max(256, int(settings.chat_max_tokens))


def resolve_context_window() -> int:
    """Model context window (input + output budget)."""
    from src.settings import get_settings

    settings = get_settings()
    try:
        return max(4096, int(settings.context_window))
    except (TypeError, ValueError):
        raw = (os.getenv("AION_CONTEXT_WINDOW") or "131072").strip()
        try:
            return max(4096, int(raw))
        except ValueError:
            return 131072
