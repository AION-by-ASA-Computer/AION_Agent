"""Context budget breakdown for chat-ui saturation bar."""

from __future__ import annotations

from haystack.dataclasses import ChatMessage

from src.memory.context_compressor import (
    build_context_budget_event,
    classify_message_tokens,
    estimate_context_breakdown,
)
from src.runtime.turn_compaction import (
    add_turn_token_estimate,
    get_turn_messages,
    set_turn_runtime,
    sync_live_turn_messages,
    try_build_context_budget_event,
)


class _FakeAgent:
    system_prompt = "You are AION."
    tools = []


def test_classify_skill_tool_result():
    msg = ChatMessage.from_tool(
        tool_result="# xlsx skill\n---\n**AION skill assets**",
        origin=ChatMessage.from_assistant("tool"),
    )
    msg.meta["tool_name"] = "skill_view"
    parts = classify_message_tokens(msg)
    assert parts.get("skills", 0) > 0
    assert "tool_results" not in parts


def test_classify_web_search_tool():
    msg = ChatMessage.from_tool(
        tool_result='{"query": "test", "results": []}',
        origin=ChatMessage.from_assistant("tool"),
    )
    msg.meta["tool_name"] = "web_search"
    parts = classify_message_tokens(msg)
    assert parts.get("web_tools", 0) > 0


def test_build_context_budget_event_shape():
    agent = _FakeAgent()
    messages = [
        ChatMessage.from_user("Crea un file Excel"),
        ChatMessage.from_assistant("Ok"),
    ]
    evt = build_context_budget_event(agent, messages, phase="preflight")
    assert evt["type"] == "context_budget"
    assert evt["phase"] == "preflight"
    assert evt["total"] > 0
    assert evt["max_prompt"] > 0
    assert isinstance(evt["parts"], list)
    assert evt["pct"] >= 0


def test_estimate_context_breakdown_includes_overhead():
    agent = _FakeAgent()
    messages = [ChatMessage.from_user("hello")]
    parts = estimate_context_breakdown(agent, messages)
    assert parts["system_prompt"] > 0
    assert parts["user"] > 0


def test_get_turn_messages_uses_live_messages_cache(monkeypatch):
    import contextvars

    import src.runtime.turn_compaction as tc

    agent = _FakeAgent()
    preflight = [ChatMessage.from_user("before")]
    live = [
        ChatMessage.from_user("before"),
        ChatMessage.from_assistant("after tool"),
    ]
    monkeypatch.setattr(
        tc, "_turn_runtime", contextvars.ContextVar("rt_test", default=None)
    )
    monkeypatch.setattr(
        tc, "_agent_exec_ctx", contextvars.ContextVar("exec_test", default=None)
    )
    tc._TURN_RUNTIME_REGISTRY.clear()
    set_turn_runtime(
        session_id="sess",
        loop=object(),
        queue=object(),
        stop_event=object(),
        agent=agent,
        profile_name="generic_assistant",
        user_id="admin",
        preflight_messages=preflight,
    )
    rt = tc._TURN_RUNTIME_REGISTRY["sess"]
    rt["live_messages"] = live

    msgs = get_turn_messages("sess")
    assert len(msgs) == 2
    assert sync_live_turn_messages("sess") is False


def test_context_budget_reads_registry_without_contextvar(monkeypatch):
    import contextvars

    import src.runtime.turn_compaction as tc

    agent = _FakeAgent()
    live = [
        ChatMessage.from_user("q"),
        ChatMessage.from_tool(
            tool_result="x" * 5000,
            origin=ChatMessage.from_assistant("t"),
        ),
    ]
    live[-1].meta["tool_name"] = "web_fetch_page"
    monkeypatch.setattr(
        tc, "_turn_runtime", contextvars.ContextVar("rt_empty", default=None)
    )
    monkeypatch.setattr(
        tc, "_agent_exec_ctx", contextvars.ContextVar("exec_empty", default=None)
    )
    tc._TURN_RUNTIME_REGISTRY.clear()
    set_turn_runtime(
        session_id="cross-task",
        loop=object(),
        queue=object(),
        stop_event=object(),
        agent=agent,
        profile_name="generic_assistant",
        user_id="admin",
        preflight_messages=live[:1],
    )
    tc._TURN_RUNTIME_REGISTRY["cross-task"]["live_messages"] = live

    evt = try_build_context_budget_event(phase="tool", session_id="cross-task")
    assert evt is not None
    assert evt["message_count"] == 2
    web_part = next(p for p in evt["parts"] if p["key"] == "web_tools")
    assert web_part["tokens"] > 100


def test_context_budget_merges_runtime_deltas_into_parts(monkeypatch):
    import contextvars

    import src.runtime.turn_compaction as tc

    agent = _FakeAgent()
    monkeypatch.setattr(
        tc, "_turn_runtime", contextvars.ContextVar("rt_empty", default=None)
    )
    monkeypatch.setattr(
        tc, "_agent_exec_ctx", contextvars.ContextVar("exec_empty", default=None)
    )
    tc._TURN_RUNTIME_REGISTRY.clear()
    set_turn_runtime(
        session_id="delta-sess",
        loop=object(),
        queue=object(),
        stop_event=object(),
        agent=agent,
        profile_name="generic_assistant",
        user_id="admin",
        preflight_messages=[ChatMessage.from_user("hello")],
    )
    tc.add_turn_token_estimate(5000, bucket="web_tools")
    tc.add_turn_token_estimate(2000, bucket="tool_results")

    evt = try_build_context_budget_event(phase="tool", session_id="delta-sess")
    assert evt is not None
    parts = {p["key"]: p["tokens"] for p in evt["parts"]}
    assert parts.get("web_tools", 0) >= 5000
    assert parts.get("tool_results", 0) >= 2000
    assert evt["total"] == sum(parts.values())
