"""Session charts: live store, timeline reference, SQLite persistence and cleanup.

Covers the flow chart tool → ``chart`` event → timeline segment → ``session_charts``
row → chart re-injected in the chat-ui history, and the deletion paths.
"""

import asyncio
import json
from pathlib import Path

import pytest

from src.chart_queue import SessionChartQueue
from src.runtime.timeline_builder import TimelineBuilder


@pytest.fixture(autouse=True)
def _memory_chart_store(monkeypatch):
    """Force the in-memory chart store (no Redis) and isolate it per test."""
    monkeypatch.delenv("AION_REDIS_URL", raising=False)
    monkeypatch.setattr(SessionChartQueue, "_redis", False)
    monkeypatch.setattr(SessionChartQueue, "_queues", {})


def _payload(query="cpu"):
    return {"query": query, "data": [{"index": 0, "v": 1}, {"index": 1, "v": 2}]}


def test_push_assigns_id_and_peek_is_not_destructive():
    """push() normalizes + ids the chart; peek() keeps it for reloads, flush() consumes it."""
    q = SessionChartQueue()
    chart = q.push("s1", _payload(), tool_call_id="call-1")
    assert chart["id"] and chart["tool_call_id"] == "call-1"
    assert chart["chart_kind"] == "line"
    assert [c["id"] for c in q.peek("s1")] == [chart["id"]]
    assert [c["id"] for c in q.peek("s1")] == [chart["id"]]  # still there
    assert [c["id"] for c in q.flush("s1")] == [chart["id"]]  # legacy contract
    assert q.peek("s1") == []


def test_clear_drops_live_charts():
    """clear() (conversation deleted) removes the live charts of that session only."""
    q = SessionChartQueue()
    q.push("s1", _payload())
    q.push("s2", _payload())
    q.clear("s1")
    assert q.peek("s1") == [] and len(q.peek("s2")) == 1


def test_timeline_builder_stores_chart_reference_only():
    """The persisted timeline keeps a light {kind: chart, id} segment after the tool step."""
    tb = TimelineBuilder()
    tb.apply_chunk(
        {
            "type": "tool_event",
            "event": {"type": "tool_start", "id": "c1", "name": "render_chart"},
        }
    )
    tb.apply_chunk(
        {
            "type": "tool_event",
            "event": {
                "type": "chart",
                "id": "chart-1",
                "tool_call_id": "c1",
                "chart": {"id": "chart-1", **_payload()},
            },
        }
    )
    tb.apply_chunk({"type": "token", "content": "Ecco il grafico"})
    kinds = [s["kind"] for s in tb.to_list()]
    assert kinds == ["tool", "chart", "text"]
    chart_seg = tb.to_list()[1]
    assert chart_seg == {"kind": "chart", "id": "chart-1", "toolCallId": "c1"}


def test_hydrate_chart_segments_places_charts():
    """History hydration injects payloads, re-places orphan charts after their tool, drops missing ones."""
    from src.api.chat_ui import _hydrate_chart_segments, _strip_chart_payloads

    a = {"id": "a", "query": "A", "data": []}
    b = {"id": "b", "query": "B", "data": [], "tool_call_id": "t2"}
    timeline = [
        {"kind": "tool", "id": "t1"},
        {"kind": "chart", "id": "a"},
        {"kind": "chart", "id": "gone"},
        {"kind": "tool", "id": "t2"},
        {"kind": "text", "id": "x", "content": "fine"},
    ]
    out = _hydrate_chart_segments(timeline, [a, b], {"a": a, "b": b})
    assert [(s["kind"], s["id"]) for s in out] == [
        ("tool", "t1"),
        ("chart", "a"),
        ("tool", "t2"),
        ("chart", "b"),
        ("text", "x"),
    ]
    assert out[1]["chart"]["query"] == "A"
    assert _strip_chart_payloads(out)[1] == {"kind": "chart", "id": "a"}


async def _reset_db(monkeypatch, tmp_path: Path) -> None:
    import src.data.engine as engine

    if engine._engine is not None:
        await engine._engine.dispose()
    engine._engine = None
    engine._session_factory = None
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "default")
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'aion.db'}")
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path / "data"))
    from src.settings import get_settings

    get_settings.cache_clear()


def test_persist_hydrate_and_delete_conversation(monkeypatch, tmp_path):
    """Charts persisted at turn end come back inline in the history and vanish with the chat."""
    from src.api.chat_ui import (
        delete_conversation_chat_ui,
        get_conversation_messages_chat_ui,
    )
    from src.charts_store import load_conversation_charts, persist_turn_charts
    from src.data.history_bridge import UnifiedHistoryBridge

    async def scenario():
        await _reset_db(monkeypatch, tmp_path)
        bridge = UnifiedHistoryBridge()
        await bridge.add_message(
            "conv-c", "user", "grafico cpu", user_id="bob", message_id="u1"
        )
        await bridge.add_message(
            "conv-c", "assistant", "Ecco", user_id="bob", message_id="a1"
        )

        chart = SessionChartQueue.push("conv-c", _payload(), tool_call_id="t1")
        # Timeline as written by TimelineBuilder: reference only.
        from src.data.engine import get_async_session_maker
        from src.data.history_bridge import fetch_message_by_id

        async with get_async_session_maker()() as session:
            msg = await fetch_message_by_id(session, "a1")
            msg.timeline_json = json.dumps(
                [
                    {"kind": "tool", "id": "t1", "name": "render_chart"},
                    {"kind": "chart", "id": chart["id"], "toolCallId": "t1"},
                    {"kind": "text", "id": "x", "content": "Ecco"},
                ]
            )
            await session.commit()

        assert await persist_turn_charts("conv-c", "a1", [chart]) == 1
        assert await persist_turn_charts("conv-c", "a1", [chart]) == 1  # idempotent
        assert len(await load_conversation_charts("conv-c")) == 1

        # Live store expired: the history still renders the chart from SQLite.
        SessionChartQueue.clear("conv-c")
        res = await get_conversation_messages_chat_ui("conv-c", user_id="bob")
        asst = [m for m in res["messages"] if m["id"] == "a1"][0]
        segs = asst["timeline"]
        assert [s["kind"] for s in segs] == ["tool", "chart", "text"]
        assert segs[1]["chart"]["query"] == "cpu"

        await delete_conversation_chat_ui("conv-c", user_id="bob")
        assert await load_conversation_charts("conv-c") == []

    asyncio.run(scenario())
