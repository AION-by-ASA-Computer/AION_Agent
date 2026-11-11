"""Resident tool filter and deferred group manifest."""

from __future__ import annotations

import os

os.environ.setdefault("AION_DEFER_TOOL_GROUPS", "1")

from types import SimpleNamespace

from src.runtime.tool_exposure import (
    clear_deferred_tools,
    deferred_prompt_section,
    make_activate_tool_group_tool,
    make_tool_search_tool,
    publish_tools,
    remember_deferred_tools,
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
        _Tool("sandbox_run_python_file"),
        _Tool("sandbox_run_node_file"),
        _Tool("sandbox_install_python_packages"),
        _Tool("sandbox_install_npm_packages"),
        _Tool("sandbox_edit_workspace_file"),
        _Tool("sandbox_execute_python"),
        _Tool("sandbox_apply_patch"),
        _Tool("memory_recall"),
    ]
    kept = [t.name for t in select_resident_tools(tools)]
    assert "skill_search" in kept
    assert "sandbox_read_text_file" in kept
    assert "sandbox_run_python_file" in kept
    assert "sandbox_run_node_file" in kept
    assert "sandbox_install_python_packages" in kept
    assert "sandbox_install_npm_packages" in kept
    assert "sandbox_edit_workspace_file" in kept
    assert "memory_recall" in kept
    assert "web_search" not in kept
    assert "sandbox_execute_python" not in kept
    assert "sandbox_apply_patch" not in kept


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
    assert "tool_search" in text
    assert "activate_tool_group" not in text
    assert "input_schema" not in text


def test_activate_mcp_group_returns_tool_names(monkeypatch):
    async def _fake_mcp(*_args, **_kwargs):
        return [_Tool("list_events")]

    monkeypatch.setattr("src.runtime.tool_exposure._mcp_group_tools", _fake_mcp)
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
    mcp_manager.set_session_context(sid, ("apple_watch_assistant", "admin", "default"))
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


def test_publish_tools_keeps_resident_set_on_real_haystack_context():
    """Haystack's _ExecutionContext has no ``tools``: loading must not drop tool_search."""
    from haystack.components.agents.agent import _ExecutionContext
    from haystack.components.agents.state import State

    from src.runtime.turn_compaction import (
        clear_turn_runtime,
        set_agent_execution_context,
        set_turn_runtime,
    )

    resident = [_Tool("tool_search"), _Tool("skill_view")]
    ctx = _ExecutionContext(
        state=State(schema={}),
        component_visits={},
        chat_generator_inputs={"tools": resident},
        tool_invoker_inputs={"tools": resident},
    )

    class _Agent:
        def __init__(self):
            self.tools = list(resident)
            self.max_agent_steps = 5

    sid = "publish-real-haystack-ctx"
    set_turn_runtime(
        session_id=sid,
        loop=None,
        queue=None,
        stop_event=None,
        agent=_Agent(),
        profile_name="sre",
        user_id="admin",
    )
    try:
        set_agent_execution_context(ctx)
        publish_tools([_Tool("list_hosts")], session_id=sid)
        expected = ["tool_search", "skill_view", "list_hosts"]
        assert [t.name for t in ctx.chat_generator_inputs["tools"]] == expected
        assert [t.name for t in ctx.tool_invoker_inputs["tools"]] == expected
    finally:
        clear_turn_runtime(sid)


def test_tool_search_publishes_named_sandbox_tool():
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
            self.tools = [_Tool("skill_search")]
            self._aion_deferred_tools = []

    sid = "search-exec-allow"
    agent = _Agent()
    ctx = _Ctx()
    remember_deferred_tools(
        sid, [_Tool("sandbox_exec_allowlisted")], "generic_assistant"
    )
    set_turn_runtime(
        session_id=sid,
        loop=None,
        queue=None,
        stop_event=None,
        agent=agent,
        profile_name="generic_assistant",
        user_id="default",
    )
    try:
        set_agent_execution_context(ctx)
        profile = SimpleNamespace(
            slug="generic_assistant",
            mcp_servers=["skills_hub", "session_sandbox"],
            native_tool_groups=["mnemos"],
        )
        tool = make_tool_search_tool(
            session_id=sid, user_id="default", tenant_id="default", profile=profile
        )
        message = tool.function("sandbox_exec_allowlisted")
        assert "sandbox_exec_allowlisted" in message
        assert [t.name for t in ctx.tools] == [
            "skill_search",
            "sandbox_exec_allowlisted",
        ]
    finally:
        clear_turn_runtime(sid)
        clear_deferred_tools(sid)


def test_tool_search_warms_only_ocr(monkeypatch):
    seen = []

    async def _fake_mcp(server_name, *_args, **_kwargs):
        seen.append(server_name)
        return [_Tool("ocr_file")]

    monkeypatch.setattr("src.runtime.tool_exposure._mcp_group_tools", _fake_mcp)
    sid = "search-ocr-only"
    profile = SimpleNamespace(
        slug="generic_assistant",
        mcp_servers=["skills_hub", "session_sandbox", "ocr", "charts"],
        native_tool_groups=["mnemos"],
    )
    tool = make_tool_search_tool(
        session_id=sid, user_id="default", tenant_id="default", profile=profile
    )
    try:
        message = tool.function("ocr")
        assert seen == ["ocr"]
        assert "ocr_file" in message
    finally:
        clear_deferred_tools(sid)


def test_tool_search_unknown_lists_names_without_publishing():
    from src.runtime.turn_compaction import (
        clear_turn_runtime,
        set_agent_execution_context,
        set_turn_runtime,
    )

    class _Ctx:
        def __init__(self):
            self.tools = [_Tool("skill_search")]
            self.tool_execution_inputs = {}

    sid = "search-miss"
    ctx = _Ctx()
    remember_deferred_tools(sid, [_Tool("sandbox_apply_patch")], "generic_assistant")
    set_turn_runtime(
        session_id=sid,
        loop=None,
        queue=None,
        stop_event=None,
        agent=None,
        profile_name="generic_assistant",
        user_id="default",
    )
    try:
        set_agent_execution_context(ctx)
        profile = SimpleNamespace(
            slug="generic_assistant",
            mcp_servers=["skills_hub", "session_sandbox"],
            native_tool_groups=["mnemos"],
        )
        tool = make_tool_search_tool(
            session_id=sid, user_id="default", tenant_id="default", profile=profile
        )
        message = tool.function("not_a_real_tool")
        assert "sandbox_apply_patch" in message
        assert "No tool matched" in message
        assert [t.name for t in ctx.tools] == ["skill_search"]
    finally:
        clear_turn_runtime(sid)
        clear_deferred_tools(sid)


def test_tool_search_group_names_tools_beyond_limit(monkeypatch):
    names = [
        "list_hosts",
        "get_os_info",
        "get_package_version",
        "list_listening_ports",
        "get_health",
        "list_pending_updates",
        "get_reboot_status",
    ]

    async def _fake_mcp(_server_name, *_args, **_kwargs):
        return [_Tool(n) for n in names]

    monkeypatch.setattr("src.runtime.tool_exposure._mcp_group_tools", _fake_mcp)
    monkeypatch.setattr(
        "src.runtime.tool_exposure.publish_tools",
        lambda tools, session_id="": list(tools),
    )
    sid = "search-group-rest"
    profile = SimpleNamespace(
        slug="sre_ssh",
        mcp_servers=["skills_hub", "session_sandbox", "aion_sre_ssh"],
        native_tool_groups=[],
    )
    tool = make_tool_search_tool(
        session_id=sid, user_id="default", tenant_id="default", profile=profile
    )
    try:
        message = tool.function("aion_sre_ssh")
        assert "Loaded 5 tool(s)" in message
        assert "not loaded yet: list_pending_updates, get_reboot_status" in message
        follow_up = tool.function("list_pending_updates")
        assert "Loaded 1 tool(s): list_pending_updates" in follow_up
    finally:
        clear_deferred_tools(sid)


def test_tool_search_emits_tool_events(monkeypatch):
    events = []
    monkeypatch.setattr(
        "src.runtime.native_tool_events.emit_native_tool_event",
        lambda session_id, payload: events.append((session_id, payload)),
    )

    async def _fake_mcp(_server_name, *_args, **_kwargs):
        return [_Tool("list_hosts")]

    monkeypatch.setattr("src.runtime.tool_exposure._mcp_group_tools", _fake_mcp)
    monkeypatch.setattr(
        "src.runtime.tool_exposure.publish_tools",
        lambda tools, session_id="": list(tools),
    )
    sid = "search-events"
    profile = SimpleNamespace(
        slug="sre_ssh",
        mcp_servers=["skills_hub", "session_sandbox", "aion_sre_ssh"],
        native_tool_groups=[],
    )
    tool = make_tool_search_tool(
        session_id=sid, user_id="default", tenant_id="default", profile=profile
    )
    try:
        message = tool.function("list_hosts")
    finally:
        clear_deferred_tools(sid)
    assert "list_hosts" in message
    types = [(p["type"], p["name"]) for _, p in events]
    assert types == [("tool_start", "tool_search"), ("tool_end", "tool_search")]
    start, end = events[0][1], events[1][1]
    assert start["input"] == {"query": "list_hosts"}
    assert start["id"] == end["id"]
    assert all(s == sid for s, _ in events)


def test_tool_search_same_step_name_waits_for_group(monkeypatch):
    """tool_search("aion_sre_ssh") and tool_search("<tool>") in one step run in parallel."""
    import asyncio
    import time
    from concurrent.futures import ThreadPoolExecutor

    async def _slow_mcp(_server_name, *_args, **_kwargs):
        await asyncio.sleep(0.3)
        return [_Tool(n) for n in ("list_hosts", "get_reboot_status")]

    monkeypatch.setattr("src.runtime.tool_exposure._mcp_group_tools", _slow_mcp)
    monkeypatch.setattr(
        "src.runtime.tool_exposure.publish_tools",
        lambda tools, session_id="": list(tools),
    )
    sid = "search-same-step"
    profile = SimpleNamespace(
        slug="sre_ssh",
        mcp_servers=["skills_hub", "session_sandbox", "aion_sre_ssh"],
        native_tool_groups=[],
    )
    tool = make_tool_search_tool(
        session_id=sid, user_id="default", tenant_id="default", profile=profile
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            group = pool.submit(tool.function, "aion_sre_ssh")
            time.sleep(0.05)
            by_name = pool.submit(tool.function, "get_reboot_status")
            assert "Loaded 2 tool(s)" in group.result()
            assert by_name.result() == (
                "Loaded 1 tool(s): get_reboot_status. You can call them on the next step."
            )
    finally:
        clear_deferred_tools(sid)


def test_tool_search_loads_cold_server_from_learned_tool_name(monkeypatch):
    """A server built once in this process resolves its tool names in a new chat."""
    from src.runtime import tool_exposure

    loaded_groups = []

    async def _fake_mcp(server_name, *_args, **_kwargs):
        loaded_groups.append(server_name)
        return [_Tool(n) for n in ("list_hosts", "list_pending_updates")]

    monkeypatch.setattr("src.runtime.tool_exposure._mcp_group_tools", _fake_mcp)
    monkeypatch.setattr(
        "src.runtime.tool_exposure.publish_tools",
        lambda tools, session_id="": list(tools),
    )
    monkeypatch.setitem(
        tool_exposure._LEARNED_COLD_TOOLS, "list_pending_updates", "aion_sre_ssh"
    )
    sid = "search-learned-name"
    profile = SimpleNamespace(
        slug="sre_ssh",
        mcp_servers=["skills_hub", "session_sandbox", "aion_sre_ssh"],
        native_tool_groups=[],
    )
    tool = make_tool_search_tool(
        session_id=sid, user_id="default", tenant_id="default", profile=profile
    )
    try:
        message = tool.function("list_pending_updates")
    finally:
        clear_deferred_tools(sid)
    assert loaded_groups == ["aion_sre_ssh"]
    assert message.startswith("Loaded 1 tool(s): list_pending_updates.")


def test_tool_search_ignores_tools_deferred_by_another_profile():
    """Regression: the default aion_std warm-up must not leak web_search.

    One chat session builds an aion_std agent (with web_research) before the
    profile the user picked. tool_search on a profile without web_research must
    not find web_search, even if it sits in the aion_std pool of the session.
    """
    sid = "search-cross-profile"
    remember_deferred_tools(sid, [_Tool("web_search")], "aion_std")
    profile = SimpleNamespace(
        slug="generic_assistant",
        mcp_servers=["skills_hub", "session_sandbox"],
        native_tool_groups=["mnemos"],
    )
    tool = make_tool_search_tool(
        session_id=sid, user_id="default", tenant_id="default", profile=profile
    )
    try:
        message = tool.function("web_search")
        assert message.startswith("No tool matched")
    finally:
        clear_deferred_tools(sid)


def test_tool_search_drops_native_tools_of_groups_not_on_profile():
    """Even a pool entry under the right profile key is refused without its group."""
    sid = "search-native-filter"
    remember_deferred_tools(sid, [_Tool("web_search")], "generic_assistant")
    profile = SimpleNamespace(
        slug="generic_assistant",
        mcp_servers=["skills_hub", "session_sandbox"],
        native_tool_groups=["mnemos"],
    )
    tool = make_tool_search_tool(
        session_id=sid, user_id="default", tenant_id="default", profile=profile
    )
    try:
        assert tool.function("web_search").startswith("No tool matched")
    finally:
        clear_deferred_tools(sid)
