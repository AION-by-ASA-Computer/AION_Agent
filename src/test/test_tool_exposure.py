"""Resident tool filter and deferred group manifest."""

from __future__ import annotations

import os

os.environ.setdefault("AION_DEFER_TOOL_GROUPS", "1")

from types import SimpleNamespace

from src.runtime.tool_exposure import (
    deferred_prompt_section,
    make_activate_tool_group_tool,
    publish_tools,
    resident_mcp_servers,
    select_resident_tools,
)


class _Tool:
    def __init__(self, name: str):
        self.name = name


def test_first_build_skips_ocr_charts_and_grafana():
    kept = resident_mcp_servers(
        ["skills_hub", "session_sandbox", "ocr", "charts", "grafana"]
    )
    assert kept == ["skills_hub", "session_sandbox"]


def test_select_resident_keeps_memory_and_skill_search():
    tools = [
        _Tool("skill_search"),
        _Tool("web_search"),
        _Tool("sandbox_read_text_file"),
        _Tool("sandbox_execute_python"),
        _Tool("memory_recall"),
    ]
    kept = [t.name for t in select_resident_tools(tools)]
    assert "skill_search" in kept
    assert "sandbox_read_text_file" in kept
    assert "memory_recall" in kept
    assert "web_search" not in kept
    assert "sandbox_execute_python" not in kept


def test_activate_lists_deferred_and_remaining_sandbox_tools():
    profile = SimpleNamespace(
        slug="generic_assistant",
        mcp_servers=["skills_hub", "session_sandbox", "charts", "ocr"],
        native_tool_groups=["mnemos", "web_research"],
    )
    tool = make_activate_tool_group_tool(
        session_id="s", user_id="default", tenant_id="default", profile=profile
    )
    message = tool.function("")
    assert "charts" in message
    assert "session_sandbox" in message
    assert "web_research" in message
    assert "mnemos" not in message


def test_deferred_section_lists_grafana_without_schema():
    profile = SimpleNamespace(
        slug="aion_std",
        mcp_servers=["skills_hub", "grafana", "ocr"],
        native_tool_groups=["mnemos", "web_research"],
    )
    text = deferred_prompt_section(profile)
    assert "grafana" in text
    assert "activate_tool_group" in text
    assert "input_schema" not in text


def test_activate_mcp_group_returns_tool_names(monkeypatch):
    async def _fake_mcp(*_args, **_kwargs):
        return [_Tool("list_events")]

    monkeypatch.setattr(
        "src.runtime.tool_exposure._mcp_group_tools", _fake_mcp
    )
    monkeypatch.setattr(
        "src.runtime.tool_exposure.publish_tools",
        lambda tools, session_id="": list(tools),
    )
    profile = SimpleNamespace(
        slug="apple_watch_assistant",
        mcp_servers=["skills_hub", "ms365"],
        native_tool_groups=["mnemos"],
    )
    tool = make_activate_tool_group_tool(
        session_id="s", user_id="admin", tenant_id="default", profile=profile
    )
    message = tool.function("ms365")
    assert "list_events" in message
    assert "Activated group 'ms365'" in message


def test_build_mcp_tools_keeps_warmed_profile():
    from src.main import _keep_session_profile
    from src.mcp_manager import mcp_manager

    sid = "keep-profile-session"
    mcp_manager.set_session_context(
        sid, ("apple_watch_assistant", "admin", "default")
    )
    try:
        _keep_session_profile(sid, "admin")
        ctx = mcp_manager.get_session_context(sid)
        assert ctx is not None
        assert ctx.profile_slug == "apple_watch_assistant"
    finally:
        mcp_manager._session_ctx.pop(sid, None)


def test_publish_tools_updates_haystack_invoker_snapshot():
    from src.runtime.turn_compaction import (
        clear_turn_runtime,
        set_agent_execution_context,
        set_turn_runtime,
    )

    class _State:
        def __init__(self):
            self.data = {"tools": []}

        def set(self, key, value):
            self.data[key] = value

    class _Ctx:
        def __init__(self):
            self.tools = []
            self.state = _State()
            self.chat_generator_inputs = {}
            self.tool_execution_inputs = {}

    class _Agent:
        def __init__(self):
            self.tools = []
            self.max_agent_steps = 5

    agent = _Agent()
    ctx = _Ctx()
    sid = "publish-outlook"
    set_turn_runtime(
        session_id=sid,
        loop=None,
        queue=None,
        stop_event=None,
        agent=agent,
        profile_name="apple_agent",
        user_id="admin",
    )
    try:
        set_agent_execution_context(ctx)
        attached = publish_tools(
            [_Tool("MicrosoftOutlookMail_ListEmails")], session_id=sid
        )
        assert [t.name for t in attached] == ["MicrosoftOutlookMail_ListEmails"]
        assert ctx.tools[0].name == "MicrosoftOutlookMail_ListEmails"
        assert ctx.state.data["tools"][0].name == "MicrosoftOutlookMail_ListEmails"
        assert ctx.tool_execution_inputs["tools"][0].name == (
            "MicrosoftOutlookMail_ListEmails"
        )
    finally:
        clear_turn_runtime(sid)


def test_publish_tools_injects_cached_agent_tools_into_current_run():
    """A previous turn left ClickUp on agent.tools; this run still has the resident set."""
    from src.runtime.turn_compaction import (
        clear_turn_runtime,
        set_agent_execution_context,
        set_turn_runtime,
    )

    class _Ctx:
        def __init__(self):
            self.tools = [_Tool("skill_search")]
            self.chat_generator_inputs = {}
            self.tool_execution_inputs = {}

    class _Agent:
        def __init__(self):
            self.tools = [_Tool("skill_search"), _Tool("clickup_filter_tasks")]
            self.max_agent_steps = 5

    agent = _Agent()
    ctx = _Ctx()
    sid = "publish-clickup-cached"
    set_turn_runtime(
        session_id=sid,
        loop=None,
        queue=None,
        stop_event=None,
        agent=agent,
        profile_name="apple_watch_assistant",
        user_id="admin",
    )
    try:
        set_agent_execution_context(ctx)
        attached = publish_tools([_Tool("clickup_filter_tasks")], session_id=sid)
        assert [t.name for t in attached] == ["clickup_filter_tasks"]
        assert [t.name for t in ctx.tools] == ["skill_search", "clickup_filter_tasks"]
    finally:
        clear_turn_runtime(sid)
