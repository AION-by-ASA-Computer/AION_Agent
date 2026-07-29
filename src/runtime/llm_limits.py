"""Shared LLM token/context limits for Haystack agent and Pi long-run."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict


def resolve_chat_max_tokens(*, long_run: bool = False) -> int:
    """Resolve max output tokens; Long Run may override via AION_LONG_RUN_MAX_TOKENS."""
    from src.settings import get_settings

    settings = get_settings()
    if long_run:
        override = settings.long_run_max_tokens
        if override is not None:
            try:
                val = int(override)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass
        raw = (os.getenv("AION_LONG_RUN_MAX_TOKENS") or "").strip()
        if raw:
            try:
                return max(256, int(raw))
            except ValueError:
                pass
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


def resolve_pi_compaction_reserve_tokens() -> int:
    raw = (os.getenv("AION_PI_COMPACTION_RESERVE_TOKENS") or "49152").strip()
    try:
        return max(1024, int(raw))
    except ValueError:
        return 49152


def resolve_pi_compaction_keep_tokens() -> int:
    raw = (os.getenv("AION_PI_COMPACTION_KEEP_RECENT_TOKENS") or "12000").strip()
    try:
        return max(512, int(raw))
    except ValueError:
        return 12000


def pi_runtime_config_snapshot() -> Dict[str, Any]:
    """Values written into Pi session files; used for refresh fingerprinting."""
    return {
        "max_tokens": resolve_chat_max_tokens(long_run=True),
        "context_window": resolve_context_window(),
        "reserve_tokens": resolve_pi_compaction_reserve_tokens(),
        "keep_recent_tokens": resolve_pi_compaction_keep_tokens(),
    }


def pi_runtime_config_fingerprint() -> str:
    payload = pi_runtime_config_snapshot()
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest[:16]
