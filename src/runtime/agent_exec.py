"""Agent execution mode: legacy thread pool vs async-native Haystack run_async (P1.2)."""
from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, List, Optional, TypeVar

T = TypeVar("T")

SyncRunner = Callable[[List[Any]], T]
AsyncRunner = Callable[[List[Any]], Awaitable[T]]


def legacy_thread_execution_enabled() -> bool:
    """When on, force sync Agent.run via asyncio.to_thread (rollback path)."""
    if os.getenv("AION_AGENT_EXEC_LEGACY_THREAD") is not None:
        raw = (os.getenv("AION_AGENT_EXEC_LEGACY_THREAD") or "0").strip().lower()
        return raw in ("1", "true", "yes", "on")
    try:
        from src.settings import get_settings

        return bool(get_settings().agent_exec_legacy_thread)
    except Exception:
        return False


async def run_agent_turn(
    messages: List[Any],
    *,
    sync_runner: SyncRunner[T],
    async_runner: Optional[AsyncRunner[T]] = None,
) -> T:
    """
    Execute one agent turn. Default path uses Haystack ``run_async`` when provided;
    legacy flag falls back to ``asyncio.to_thread`` + ``Agent.run``.
    """
    if legacy_thread_execution_enabled() or async_runner is None:
        return await asyncio.to_thread(sync_runner, messages)
    return await async_runner(messages)
