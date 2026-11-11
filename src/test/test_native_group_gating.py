"""Native tool groups (web_research, deep_research, mnemos) gate behaviour per profile.

Removing a group from a profile must remove the capability, not only hide the
tool in admin-ui: these tests cover the profile-level checks used by the agent
factory and the Mnemos turn pipeline.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.runtime.deep_research_tools import (
    deep_research_tools_allowed,
    profile_wants_deep_research,
)
from src.runtime.mnemos_tools import profile_name_wants_mnemos, profile_wants_mnemos


def test_profile_wants_deep_research_follows_connector():
    """The connector is the deep_research group or the legacy deep_research MCP slug."""
    assert profile_wants_deep_research(
        SimpleNamespace(native_tool_groups=["deep_research"])
    )
    assert profile_wants_deep_research(
        SimpleNamespace(native_tool_groups=[], mcp_servers=["deep_research"])
    )
    assert not profile_wants_deep_research(
        SimpleNamespace(native_tool_groups=["web_research"], mcp_servers=["ocr"])
    )
    assert not profile_wants_deep_research(SimpleNamespace(native_tool_groups=None))
    assert not profile_wants_deep_research(None)


def test_deep_research_tools_allowed_rules(monkeypatch):
    """Normal mode needs the connector; Deep Research mode never does; kill switch wins."""
    monkeypatch.setattr("src.research.handler.deep_research_enabled", lambda: True)
    with_conn = SimpleNamespace(native_tool_groups=["deep_research"])
    without = SimpleNamespace(native_tool_groups=["web_research"], mcp_servers=[])
    assert deep_research_tools_allowed(with_conn, "normal")
    assert not deep_research_tools_allowed(without, "normal")
    assert not deep_research_tools_allowed(without, "plan")
    assert deep_research_tools_allowed(without, "deep_research")
    assert deep_research_tools_allowed(None, "deep_research")
    monkeypatch.setattr("src.research.handler.deep_research_enabled", lambda: False)
    assert not deep_research_tools_allowed(with_conn, "deep_research")


def test_deep_research_tools_are_resident(monkeypatch):
    """trigger_research is never deferred, so Deep Research mode can call it on step one."""
    from haystack.tools import Tool

    from src.runtime.tool_exposure import activatable_groups, partition_resident_tools

    monkeypatch.setenv("AION_DEFER_TOOL_GROUPS", "1")

    def _fn(topic: str) -> str:
        return topic

    tools = [
        Tool(
            name=n,
            description=n,
            function=_fn,
            parameters={"type": "object", "properties": {}},
        )
        for n in ("trigger_research", "manage_research", "web_search")
    ]
    kept, deferred = partition_resident_tools(tools)
    assert {t.name for t in kept} == {"trigger_research", "manage_research"}
    assert {t.name for t in deferred} == {"web_search"}
    profile = SimpleNamespace(
        native_tool_groups=["deep_research", "web_research"],
        mcp_servers=["deep_research"],
    )
    groups = activatable_groups(profile)
    assert "deep_research" not in groups
    assert "web_research" in groups


def test_deep_research_mode_prompt_starts_job_immediately():
    """The mode prompt asks for trigger_research first, with no own-knowledge fallback."""
    from src.runtime.deep_research_mode import build_deep_research_system_prompt

    text = build_deep_research_system_prompt()
    assert "first and only action" in text
    assert "trigger_research" in text
    assert "own knowledge" in text
    assert "clarifying" in text


def test_refresh_turn_context_keeps_mode_prompt_and_catalog(monkeypatch):
    """Per-turn refresh adds the Deep Research prompt on any profile and keeps the catalog."""
    from src.runtime.context_builder import refresh_agent_turn_context

    profile = SimpleNamespace(
        native_tool_groups=[],
        mcp_servers=[],
        generate_system_prompt=lambda user_id="": "BASE",
    )
    monkeypatch.setattr(
        "src.agent_profile.profile_manager.get_profile", lambda _name: profile
    )
    agent = SimpleNamespace(system_prompt="", _aion_deferred_catalog="\nCATALOG")
    refresh_agent_turn_context(agent, profile_name="p", agent_mode="deep_research")
    assert agent.system_prompt.startswith("BASE")
    assert "DEEP RESEARCH MODE ACTIVE" in agent.system_prompt
    assert agent.system_prompt.endswith("\nCATALOG")


def test_profile_name_wants_mnemos_resolves_profile(monkeypatch):
    """Profile names resolve via profile_manager; unknown names keep legacy behaviour."""
    profiles = {
        "with_mem": SimpleNamespace(native_tool_groups=["mnemos"]),
        "no_mem": SimpleNamespace(native_tool_groups=["web_research"]),
    }
    monkeypatch.setattr(
        "src.agent_profile.profile_manager.get_profile",
        lambda name: profiles.get(name),
    )
    assert profile_name_wants_mnemos("with_mem")
    assert not profile_name_wants_mnemos("no_mem")
    assert profile_name_wants_mnemos("unknown_profile")
    assert profile_name_wants_mnemos(None)
    assert profile_wants_mnemos(profiles["with_mem"])


@pytest.mark.anyio
async def test_ltm_extraction_skipped_for_profile_without_mnemos(monkeypatch):
    """extract_and_persist must not call the extraction LLM when the profile lacks mnemos."""
    from src.memory import ltm_orchestrator as ltm_mod

    calls: list = []

    async def _fake_complete(*_a, **_k):
        calls.append(1)
        return {}

    monkeypatch.setenv("AION_LTM_EXTRACT", "1")
    monkeypatch.setattr(ltm_mod, "complete_json_async", _fake_complete)
    monkeypatch.setattr(
        "src.runtime.mnemos_tools.profile_name_wants_mnemos", lambda _name: False
    )

    await ltm_mod.ltm_orchestrator.extract_and_persist(
        "sess", "user", "hello", "world", profile_slug="no_mem"
    )
    assert calls == []
