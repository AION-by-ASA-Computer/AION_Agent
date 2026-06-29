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
