"""Tests for non-destructive STM compaction (message archived_at)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_archive_messages_keeps_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("AION_UNIFIED_DB", "1")

    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_async_session_maker, init_engine
    from src.data.history_bridge import (
        UnifiedHistoryBridge,
        _archive_messages_and_children,
    )
    from src.data.ids import new_uuid7_str
    from src.data.models import Conversation, Message
    from sqlalchemy import select

    eng = init_engine()
    await ensure_bootstrap_schema(eng)

    conv_id = new_uuid7_str()
    msg_id = new_uuid7_str()
    async with get_async_session_maker()() as session:
        session.add(
            Conversation(
                id=conv_id,
                tenant_id="default",
                user_id="u1",
                profile_slug="aion_std",
                title="t",
            )
        )
        session.add(
            Message(
                id=msg_id,
                conversation_id=conv_id,
                tenant_id="default",
                seq=1,
                role="user",
                content="hello",
            )
        )
        await session.commit()

    async with get_async_session_maker()() as session:
        n = await _archive_messages_and_children(
            session, conv_id, [msg_id], reason="mid_turn_compaction"
        )
        await session.commit()
        assert n == 1

    async with get_async_session_maker()() as session:
        row = (
            await session.execute(select(Message).where(Message.id == msg_id))
        ).scalar_one()
        assert row.archived_at is not None
        assert row.archived_reason == "mid_turn_compaction"

    bridge = UnifiedHistoryBridge()
    active = await bridge.get_window(conv_id, max_turns=10)
    assert len(active) == 0
