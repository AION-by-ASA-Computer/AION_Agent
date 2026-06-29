"""Tests for idempotent timeline backfill."""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.data.history_bridge import UnifiedHistoryBridge
from src.runtime.timeline_backfill import backfill_message_timelines


async def _reset_unified_db(monkeypatch, tmp_path: Path) -> None:
    import src.data.engine as engine

    if engine._engine is not None:
        await engine._engine.dispose()
    engine._engine = None
    engine._session_factory = None
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "default")
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'aion.db'}")
    monkeypatch.delenv("AION_CHAT_UI_INTERNAL_SECRET", raising=False)


def test_timeline_backfill_is_idempotent(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        await bridge.add_message("conv-bf", "user", "Hi", user_id="u1", message_id="u1")
        await bridge.add_message(
            "conv-bf",
            "assistant",
            "Done",
            user_id="u1",
            reasoning="thought",
            message_id="a1",
        )
        await bridge.add_step(
            "conv-bf",
            name="web_search",
            type="tool",
            input="{}",
            output="{}",
            message_id="a1",
        )
        n1 = await backfill_message_timelines()
        assert n1 >= 1
        n2 = await backfill_message_timelines()
        assert n2 == 0

    asyncio.run(run())
