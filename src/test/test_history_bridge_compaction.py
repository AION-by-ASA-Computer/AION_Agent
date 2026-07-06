import asyncio
import json

from sqlalchemy import func, select

from src.data.history_bridge import UnifiedHistoryBridge
from src.data.models import Attachment, Message, Step
from src.memory.context_compressor import (
    COMPACTION_MARKER,
    LAST_ASSISTANT_SECTION,
    format_compaction_block,
)


async def _reset_unified_db(monkeypatch, tmp_path):
    import src.data.engine as engine

    if engine._engine is not None:
        await engine._engine.dispose()
    engine._engine = None
    engine._session_factory = None
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "default")
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'aion.db'}")
    from src.settings import get_settings

    get_settings.cache_clear()


def test_compaction_deletes_orphan_steps_and_attachments(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        cid = "conv-compact-1"
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            await bridge.add_message(
                cid, role, f"msg-{i}", user_id="u1", message_id=f"m-{i}"
            )
        pruned_assistant = "m-5"
        await bridge.add_step(
            cid,
            name="tool_a",
            type="tool",
            output="out",
            message_id=pruned_assistant,
        )
        await bridge.add_attachment(
            cid,
            storage_key="workspace/a.txt",
            original_name="a.txt",
            mime="text/plain",
            size_bytes=1,
            kind="artifact",
            message_id=pruned_assistant,
        )

        from src.data.engine import get_async_session_maker
        from src.data.ids import new_uuid7_str

        async with get_async_session_maker()() as session:
            session.add(
                Step(
                    id=new_uuid7_str(),
                    conversation_id=cid,
                    tenant_id="default",
                    message_id=None,
                    name="orphan_tool",
                    type="tool",
                    output="x",
                    is_error=0,
                )
            )
            await session.commit()

        summary = format_compaction_block("summary body", source_messages=4)
        await bridge.persist_stm_compaction(
            cid, profile_name="default", summary_content=summary, keep_last_n=3
        )

        from src.data.engine import get_async_session_maker

        async with get_async_session_maker()() as session:
            step_count = (
                await session.execute(
                    select(func.count()).select_from(Step).where(
                        Step.conversation_id == cid
                    )
                )
            ).scalar_one()
            att_count = (
                await session.execute(
                    select(func.count()).select_from(Attachment).where(
                        Attachment.conversation_id == cid
                    )
                )
            ).scalar_one()
            orphan_steps = (
                await session.execute(
                    select(func.count()).select_from(Step).where(
                        Step.conversation_id == cid,
                        Step.message_id.is_(None),
                    )
                )
            ).scalar_one()
        assert step_count == 0
        assert att_count == 0
        assert orphan_steps == 0

    asyncio.run(run())


def test_compaction_recalculates_message_count(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        cid = "conv-compact-2"
        for i in range(8):
            role = "user" if i % 2 == 0 else "assistant"
            await bridge.add_message(
                cid, role, f"body-{i}", user_id="u1", message_id=f"n-{i}"
            )

        summary = format_compaction_block("tail summary", source_messages=5)
        await bridge.persist_stm_compaction(
            cid, profile_name="default", summary_content=summary, keep_last_n=2
        )

        from src.data.engine import get_async_session_maker
        from src.data.models import Conversation

        async with get_async_session_maker()() as session:
            conv = await session.get(Conversation, cid)
            msg_count = (
                await session.execute(
                    select(func.count()).select_from(Message).where(
                        Message.conversation_id == cid
                    )
                )
            ).scalar_one()
        assert conv is not None
        assert conv.message_count == msg_count
        assert msg_count == 3  # summary user + 2 kept tail messages

    asyncio.run(run())


def test_compaction_preserves_tail_timeline_not_inflated(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        cid = "conv-compact-3"
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            await bridge.add_message(
                cid, role, f"x-{i}", user_id="u1", message_id=f"t-{i}"
            )

        huge_timeline = json.dumps(
            [
                {"kind": "tool", "id": f"s{idx}", "name": "mcp", "input": "", "output": "x"}
                for idx in range(200)
            ]
        )
        from src.data.engine import get_async_session_maker

        async with get_async_session_maker()() as session:
            row = (
                await session.execute(
                    select(Message).where(Message.id == "t-5")
                )
            ).scalar_one()
            row.content = ""
            row.timeline_json = huge_timeline
            await session.commit()

        summary = format_compaction_block("compact", source_messages=3)
        await bridge.persist_stm_compaction(
            cid, profile_name="default", summary_content=summary, keep_last_n=2
        )

        async with get_async_session_maker()() as session:
            kept = (
                await session.execute(
                    select(Message).where(
                        Message.conversation_id == cid,
                        Message.role == "assistant",
                    )
                )
            ).scalars().all()
        for row in kept:
            if not (row.content or "").strip():
                assert row.timeline_json is None or len(row.timeline_json or "") < 50_000

    asyncio.run(run())


def test_compaction_summary_includes_last_assistant_text(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        cid = "conv-compact-4"
        await bridge.add_message(
            cid, "user", "old", user_id="u1", message_id="u-old"
        )
        await bridge.add_message(
            cid,
            "assistant",
            "Ho creato con successo il documento Word.",
            user_id="u1",
            message_id="a-old",
        )
        await bridge.add_message(
            cid, "user", "recent", user_id="u1", message_id="u-new"
        )
        await bridge.add_message(
            cid, "assistant", "ok", user_id="u1", message_id="a-new"
        )

        summary = format_compaction_block("riepilogo", source_messages=2)
        await bridge.persist_stm_compaction(
            cid, profile_name="default", summary_content=summary, keep_last_n=2
        )

        from src.data.engine import get_async_session_maker

        async with get_async_session_maker()() as session:
            summary_row = (
                await session.execute(
                    select(Message.content).where(
                        Message.conversation_id == cid,
                        Message.content.contains(COMPACTION_MARKER),
                    )
                )
            ).scalar_one()
        assert LAST_ASSISTANT_SECTION in summary_row
        assert "Ho creato con successo" in summary_row

    asyncio.run(run())
