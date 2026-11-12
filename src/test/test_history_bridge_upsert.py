import asyncio

from src.data.history_bridge import UnifiedHistoryBridge


def test_upsert_preserves_nonempty_content_and_timeline(monkeypatch, tmp_path):
    async def run():
        import src.data.engine as engine

        if engine._engine is not None:
            await engine._engine.dispose()
        engine._engine = None
        engine._session_factory = None
        monkeypatch.setenv("AION_UNIFIED_DB", "1")
        monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "default")
        monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'aion.db'}")

        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-upsert",
            "assistant",
            "",
            user_id="u1",
            message_id="assistant-1",
        )
        await bridge.upsert_message_content(
            "conv-upsert",
            "assistant-1",
            "assistant",
            "Hello from stream",
            user_id="u1",
        )
        await bridge.upsert_message_content(
            "conv-upsert",
            "assistant-1",
            "assistant",
            "",
            user_id="u1",
            timeline_json='[{"kind":"text","id":"t0","content":"Hello from stream"}]',
        )

        from src.data.engine import get_async_session_maker
        from src.data.history_bridge import fetch_message_by_id

        async with get_async_session_maker()() as session:
            row = await fetch_message_by_id(session, "assistant-1")
            assert row is not None
            assert row.content == "Hello from stream"
            assert "Hello from stream" in (row.timeline_json or "")

    asyncio.run(run())


def test_upsert_rejects_cross_conversation_id_update(monkeypatch, tmp_path):
    async def run():
        import src.data.engine as engine

        if engine._engine is not None:
            await engine._engine.dispose()
        engine._engine = None
        engine._session_factory = None
        monkeypatch.setenv("AION_UNIFIED_DB", "1")
        monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "default")
        monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'aion.db'}")

        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-a", "assistant", "in A", user_id="u1", message_id="shared-id"
        )
        ok = await bridge.upsert_message_content(
            "conv-b",
            "shared-id",
            "assistant",
            "overwrite from B",
            user_id="u1",
        )
        assert ok is False

        from src.data.engine import get_async_session_maker
        from src.data.history_bridge import fetch_message_by_id

        async with get_async_session_maker()() as session:
            row = await fetch_message_by_id(session, "shared-id")
            assert row is not None
            assert row.conversation_id == "conv-a"
            assert row.content == "in A"

    asyncio.run(run())


def test_append_message_text_replaces_placeholder_and_appends_segment(
    monkeypatch, tmp_path
):
    """append_message_text (final plan summary into the last task message):
    a placeholder body/segment is replaced, tool segments are kept and the
    summary becomes the trailing text segment rendered by the chat-ui."""

    async def run():
        import json

        import src.data.engine as engine

        if engine._engine is not None:
            await engine._engine.dispose()
        engine._engine = None
        engine._session_factory = None
        monkeypatch.setenv("AION_UNIFIED_DB", "1")
        monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "default")
        monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'aion.db'}")

        placeholder = "✅ Task completed."
        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-plan", "assistant", "", user_id="u1", message_id="task-4"
        )
        await bridge.upsert_message_content(
            "conv-plan",
            "task-4",
            "assistant",
            placeholder,
            user_id="u1",
            timeline_json=json.dumps(
                [
                    {"kind": "tool", "id": "c1", "name": "mark_task_completed"},
                    {"kind": "text", "id": "text_1", "content": placeholder},
                ]
            ),
        )
        ok = await bridge.append_message_text(
            "conv-plan",
            "task-4",
            "## Plan completed",
            replaceable_texts=frozenset({placeholder}),
        )
        assert ok is True
        # Unknown id / wrong conversation: nothing written.
        assert not await bridge.append_message_text("conv-x", "task-4", "x")

        from src.data.engine import get_async_session_maker
        from src.data.history_bridge import fetch_message_by_id

        async with get_async_session_maker()() as session:
            row = await fetch_message_by_id(session, "task-4")
            assert row.content == "## Plan completed"
            segs = json.loads(row.timeline_json)
            assert [s["kind"] for s in segs] == ["tool", "text"]
            assert segs[-1]["content"] == "## Plan completed"

    asyncio.run(run())


def test_append_message_text_keeps_real_task_output(monkeypatch, tmp_path):
    """Real text written by the task turn stays; the summary goes below it."""

    async def run():
        import src.data.engine as engine

        if engine._engine is not None:
            await engine._engine.dispose()
        engine._engine = None
        engine._session_factory = None
        monkeypatch.setenv("AION_UNIFIED_DB", "1")
        monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "default")
        monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'aion.db'}")

        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-plan", "assistant", "Docx saved.", user_id="u1", message_id="t4"
        )
        assert await bridge.append_message_text("conv-plan", "t4", "Summary")

        from src.data.engine import get_async_session_maker
        from src.data.history_bridge import fetch_message_by_id

        async with get_async_session_maker()() as session:
            row = await fetch_message_by_id(session, "t4")
            assert row.content == "Docx saved.\n\nSummary"

    asyncio.run(run())
