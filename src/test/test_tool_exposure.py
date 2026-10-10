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


def test_publish_tools_updates_haystack_invoker_snapshot():
    from src.runtime.turn_compaction import (
        clear_turn_runtime,
        set_agent_execution_context,
        set_turn_runtime,
    )

    class _Ctx:
        def __init__(self):
            self.chat_generator_inputs = {"tools": []}
            self.tool_invoker_inputs = {"tools": []}

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
        assert ctx.tool_invoker_inputs["tools"][0].name == (
            "MicrosoftOutlookMail_ListEmails"
        )
        assert ctx.chat_generator_inputs["tools"][0].name == (
            "MicrosoftOutlookMail_ListEmails"
        )
    finally:
        clear_turn_runtime(sid)
