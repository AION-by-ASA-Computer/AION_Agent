import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.api.chat_ui import (
    SideThreadCreateBody,
    create_side_thread_chat_ui,
    delete_conversation_chat_ui,
    get_conversation_chat_ui,
    list_conversations_chat_ui,
    list_side_threads_chat_ui,
)
from src.data.history_bridge import UnifiedHistoryBridge
from src.runtime.turn.side_thread_context import build_side_thread_context


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
    from src.settings import get_settings

    get_settings.cache_clear()


async def _seed_parent() -> None:
    bridge = UnifiedHistoryBridge()
    await bridge.add_message("parent", "user", "Come funziona Raft?", user_id="u1", message_id="m-user")
    await bridge.add_message(
        "parent",
        "assistant",
        "Raft elegge un leader tramite un quorum e replica un log di comandi.",
        user_id="u1",
        message_id="m-asst",
    )


def _body(quote="quorum", **kw):
    return SideThreadCreateBody(
        parent_message_id=kw.get("parent_message_id", "m-asst"),
        quote=quote,
        prefix="leader tramite un ",
        suffix=" e replica",
    )


async def _list(**kw):
    return await list_conversations_chat_ui(
        limit=40, exclude_scheduled=True, include_threads=False, x_aion_user_id="u1", **kw
    )


def test_create_dedup_list_and_details(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        await _seed_parent()

        t1 = await create_side_thread_chat_ui("parent", _body(), x_aion_user_id="u1")
        assert t1["created"] is True
        assert t1["parent_conversation_id"] == "parent"
        assert t1["anchor"]["quote"] == "quorum"
        assert t1["title"] == "quorum"

        again = await create_side_thread_chat_ui("parent", _body(), x_aion_user_id="u1")
        assert again["created"] is False and again["id"] == t1["id"]

        threads = await list_side_threads_chat_ui("parent", x_aion_user_id="u1")
        assert [t["id"] for t in threads["data"]] == [t1["id"]]

        listed = (await _list())["data"]
        assert [c["id"] for c in listed] == ["parent"]
        assert listed[0]["thread_count"] == 1

        details = await get_conversation_chat_ui(t1["id"], x_aion_user_id="u1")
        assert details["parent_conversation_id"] == "parent"
        assert details["parent_message_id"] == "m-asst"
        assert details["anchor"]["quote"] == "quorum"

    asyncio.run(run())


def test_ownership_nesting_and_missing_message(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        await _seed_parent()

        with pytest.raises(HTTPException) as other_user:
            await create_side_thread_chat_ui("parent", _body(), x_aion_user_id="u2")
        assert other_user.value.status_code == 404

        with pytest.raises(HTTPException) as bad_msg:
            await create_side_thread_chat_ui(
                "parent", _body(parent_message_id="nope"), x_aion_user_id="u1"
            )
        assert bad_msg.value.status_code == 404

        t1 = await create_side_thread_chat_ui("parent", _body(), x_aion_user_id="u1")
        with pytest.raises(HTTPException) as nested:
            await create_side_thread_chat_ui(t1["id"], _body(), x_aion_user_id="u1")
        assert nested.value.status_code == 409

    asyncio.run(run())


def test_delete_parent_archives_threads(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        await _seed_parent()
        t1 = await create_side_thread_chat_ui("parent", _body(), x_aion_user_id="u1")

        await delete_conversation_chat_ui("parent", x_aion_user_id="u1")

        assert (await list_side_threads_chat_ui("parent", x_aion_user_id="u1"))["data"] == []
        everything = await list_conversations_chat_ui(
            limit=40, exclude_scheduled=True, include_threads=True, x_aion_user_id="u1"
        )
        assert t1["id"] not in [c["id"] for c in everything["data"]]

    asyncio.run(run())


def test_side_thread_context_block(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        await _seed_parent()
        t1 = await create_side_thread_chat_ui("parent", _body(), x_aion_user_id="u1")

        ctx = await build_side_thread_context(t1["id"], "u1")
        assert "<side-thread-context>" in ctx
        assert "«quorum»" in ctx
        assert "replica un log di comandi" in ctx
        assert "[user] Come funziona Raft?" in ctx

        assert await build_side_thread_context("parent", "u1") == ""

    asyncio.run(run())
