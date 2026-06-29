import asyncio
from pathlib import Path

from sqlalchemy import func, select

from src.api.chat_ui import get_conversation_messages_chat_ui
from src.data.history_bridge import UnifiedHistoryBridge
from src.data.models import Attachment


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


def test_chat_ui_history_preserves_steps_artifacts_and_reasoning(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-1", "user", "Crea uno script", user_id="u1", message_id="user-1"
        )
        await bridge.add_message(
            "conv-1",
            "assistant",
            "Ecco lo script.",
            user_id="u1",
            reasoning="Ho creato un file Python.",
            message_id="assistant-1",
        )
        await bridge.add_step(
            "conv-1",
            name="sandbox_write_workspace_file",
            type="tool",
            input='{"relative_path":"workspace/fib.py"}',
            output="workspace/fib.py",
            message_id="assistant-1",
        )
        await bridge.add_attachment(
            "conv-1",
            storage_key="workspace/fib.py",
            original_name="fib.py",
            mime="python",
            size_bytes=42,
            kind="artifact",
            message_id="assistant-1",
        )

        payload = await get_conversation_messages_chat_ui("conv-1", x_aion_user_id="u1")
        assistant = payload["messages"][1]
        assert assistant["id"] == "assistant-1"
        assert assistant["reasoning"] == "Ho creato un file Python."
        assert assistant["steps"][0]["name"] == "sandbox_write_workspace_file"
        assert assistant["artifacts"][0]["storage_key"] == "workspace/fib.py"
        assert "timeline" in assistant
        assert isinstance(assistant["timeline"], list)
        assert assistant["timeline"][0]["kind"] == "reasoning"
        tool_kinds = [
            s["kind"]
            for s in assistant["timeline"]
            if s["kind"] in ("tool", "artifact")
        ]
        assert "tool" in tool_kinds

    asyncio.run(run())


def test_chat_ui_history_shows_empty_assistant_with_steps(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-empty", "user", "Run tool", user_id="u1", message_id="user-1"
        )
        await bridge.add_message(
            "conv-empty",
            "assistant",
            "",
            user_id="u1",
            message_id="assistant-1",
        )
        await bridge.add_step(
            "conv-empty",
            name="web_search",
            type="tool",
            input="{}",
            output='{"results":[]}',
            message_id="assistant-1",
        )

        payload = await get_conversation_messages_chat_ui(
            "conv-empty", x_aion_user_id="u1"
        )
        assert len(payload["messages"]) == 2
        assistant = payload["messages"][1]
        assert assistant["id"] == "assistant-1"
        assert assistant["steps"][0]["name"] == "web_search"

    asyncio.run(run())


def test_chat_ui_history_missing_conversation_returns_empty(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        from src.data.history_bridge import UnifiedHistoryBridge

        bridge = UnifiedHistoryBridge()
        await bridge.init()
        payload = await get_conversation_messages_chat_ui(
            "conv-does-not-exist",
            x_aion_user_id="u1",
        )
        assert payload["messages"] == []

    asyncio.run(run())


def test_chat_ui_history_shows_terminal_empty_assistant(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-term", "user", "Ciao", user_id="u1", message_id="user-1"
        )
        await bridge.add_message(
            "conv-term",
            "assistant",
            "",
            user_id="u1",
            message_id="assistant-1",
        )

        payload = await get_conversation_messages_chat_ui(
            "conv-term", x_aion_user_id="u1"
        )
        assert len(payload["messages"]) == 2
        assert payload["messages"][1]["role"] == "assistant"
        assert payload["messages"][1]["id"] == "assistant-1"

    asyncio.run(run())


def test_chat_ui_history_404_for_wrong_user(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-own", "user", "Hi", user_id="owner", message_id="user-1"
        )

        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await get_conversation_messages_chat_ui("conv-own", x_aion_user_id="other")
        assert exc.value.status_code == 404

    asyncio.run(run())


def test_chat_ui_history_attaches_orphans_only_to_next_assistant(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-2", "user", "Prima domanda", user_id="u1", message_id="user-1"
        )
        await bridge.add_step(
            "conv-2", name="legacy_tool", type="tool", output="legacy"
        )
        await bridge.add_attachment(
            "conv-2",
            storage_key="workspace/legacy.txt",
            original_name="legacy.txt",
            mime="text/plain",
            size_bytes=6,
            kind="artifact",
        )
        await bridge.add_message(
            "conv-2", "user", "Seconda domanda", user_id="u1", message_id="user-2"
        )
        await bridge.add_message(
            "conv-2", "assistant", "Risposta", user_id="u1", message_id="assistant-1"
        )

        payload = await get_conversation_messages_chat_ui("conv-2", x_aion_user_id="u1")
        first_user, second_user, assistant = payload["messages"]
        assert first_user["steps"] == []
        assert second_user["steps"] == []
        assert assistant["steps"][0]["name"] == "legacy_tool"
        assert assistant["artifacts"][0]["storage_key"] == "workspace/legacy.txt"

    asyncio.run(run())


def test_attachment_persistence_is_idempotent(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-3", "user", "Ciao", user_id="u1", message_id="user-1"
        )
        await bridge.add_message(
            "conv-3", "assistant", "Fatto", user_id="u1", message_id="assistant-1"
        )
        for _ in range(2):
            await bridge.add_attachment(
                "conv-3",
                storage_key="workspace/once.py",
                original_name="once.py",
                mime="python",
                size_bytes=10,
                kind="artifact",
                message_id="assistant-1",
            )

        from src.data.engine import get_async_session_maker

        async with get_async_session_maker()() as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(Attachment)
                    .where(
                        Attachment.conversation_id == "conv-3",
                        Attachment.message_id == "assistant-1",
                        Attachment.storage_key == "workspace/once.py",
                    )
                )
            ).scalar_one()
        assert count == 1

    asyncio.run(run())


def test_chat_ui_history_get_last_assistant_steps(monkeypatch, tmp_path):
    async def run():
        import aiosqlite

        # 1. Test Unified Mode
        await _reset_unified_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()

        await bridge.add_message(
            "conv-steps", "user", "Ciao", user_id="u1", message_id="user-1"
        )
        await bridge.add_message(
            "conv-steps", "assistant", "Ecco", user_id="u1", message_id="assistant-1"
        )
        await bridge.add_step(
            "conv-steps",
            name="read_file",
            type="tool",
            input='{"path":"test.txt"}',
            output="file content",
            message_id="assistant-1",
        )

        steps = await bridge.get_last_assistant_steps("conv-steps")
        assert len(steps) == 1
        assert steps[0]["name"] == "read_file"
        assert steps[0]["output"] == "file content"

        # 2. Test Non-Unified Mode Fallback
        monkeypatch.setenv("AION_UNIFIED_DB", "0")
        from src.api.history import ChatHistoryManager

        db_file = tmp_path / "chat_memory.db"
        history_mgr = ChatHistoryManager(db_path=str(db_file))
        await history_mgr.add_message(
            "conv-fallback", "user", "Ciao", user_id="u1", message_id="user-fb-1"
        )
        await history_mgr.add_message(
            "conv-fallback",
            "assistant",
            "Ecco",
            user_id="u1",
            message_id="assistant-fb-1",
        )

        # Manually create steps table and insert step in non-unified sqlite
        async with aiosqlite.connect(str(db_file)) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS steps ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "conversation_id TEXT NOT NULL,"
                "message_id TEXT,"
                "name TEXT NOT NULL,"
                "type TEXT NOT NULL,"
                "input TEXT,"
                "output TEXT,"
                "is_error INTEGER DEFAULT 0"
                ")"
            )
            await db.execute(
                "INSERT INTO steps (conversation_id, message_id, name, type, input, output, is_error) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (
                    "conv-fallback",
                    "temp-id",
                    "execute_command",
                    "tool",
                    '{"cmd":"ls"}',
                    "file1\nfile2",
                ),
            )
            await db.commit()

            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id FROM messages WHERE session_id = 'conv-fallback' AND role = 'assistant'"
            ) as cur:
                r = await cur.fetchone()
                last_db_msg_id = r[0]

            await db.execute(
                "UPDATE steps SET message_id = ? WHERE conversation_id = ?",
                (str(last_db_msg_id), "conv-fallback"),
            )
            await db.commit()

        fallback_steps = await history_mgr.get_last_assistant_steps("conv-fallback")
        assert len(fallback_steps) == 1
        assert fallback_steps[0]["name"] == "execute_command"
        assert fallback_steps[0]["output"] == "file1\nfile2"

    asyncio.run(run())
