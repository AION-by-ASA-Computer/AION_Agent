"""Deep Research tools gating (trigger_research / manage_research).

Rules (see src/runtime/deep_research_tools.py):
- normal mode: merged only when the profile has the Deep Research connector
  (``deep_research`` native group or legacy ``deep_research`` MCP slug);
- Deep Research mode: always merged, whatever the profile;
- AION_DEEP_RESEARCH_ENABLED=0 disables them everywhere.
"""

from types import SimpleNamespace

import pytest

from src.main import build_all_tools
from src.runtime.deep_research_tools import (
    DEEP_RESEARCH_BUILTIN_TOOL_NAMES,
    merge_builtin_deep_research_tools,
)


async def _tool_names_for(
    monkeypatch,
    groups: list[str],
    sid: str,
    agent_mode: str = "normal",
    mcp_servers: list[str] | None = None,
) -> set:
    """Build the tool list for a fake profile with ``groups`` in ``agent_mode``."""

    async def _no_mcp(*_a, **_k):
        return []

    monkeypatch.setattr(
        "src.runtime.native_tools.load_native_tools", lambda *_a, **_k: []
    )
    monkeypatch.setattr("src.main.build_mcp_tools", _no_mcp)
    monkeypatch.setattr("src.research.handler.deep_research_enabled", lambda: True)

    profile = SimpleNamespace(
        name="mysql_metadata_assistant",
        mcp_servers=mcp_servers or [],
        native_tool_groups=groups,
    )
    tools = await build_all_tools(sid, profile, user_id="u1", agent_mode=agent_mode)
    return {getattr(t, "name", None) for t in tools}


@pytest.mark.anyio
async def test_build_all_tools_omits_deep_research_without_profile_bundle(
    monkeypatch,
):
    """A profile without the deep_research group gets no trigger/manage_research."""
    names = await _tool_names_for(monkeypatch, ["sql_query_memory"], "sess-dr-1")
    assert not set(DEEP_RESEARCH_BUILTIN_TOOL_NAMES) & names


@pytest.mark.anyio
async def test_build_all_tools_includes_deep_research_with_profile_bundle(
    monkeypatch,
):
    """A profile with the deep_research group gets both deep research tools."""
    names = await _tool_names_for(monkeypatch, ["deep_research"], "sess-dr-2")
    assert set(DEEP_RESEARCH_BUILTIN_TOOL_NAMES).issubset(names)


@pytest.mark.anyio
async def test_merge_builtin_deep_research_skipped_when_disabled(monkeypatch):
    """AION_DEEP_RESEARCH_ENABLED=0 wins even when the profile has the group."""
    monkeypatch.setattr("src.research.handler.deep_research_enabled", lambda: False)
    profile = SimpleNamespace(native_tool_groups=["deep_research"])
    merged = merge_builtin_deep_research_tools([], "s1", "u1", profile)
    assert merged == []


@pytest.mark.anyio
async def test_merge_builtin_deep_research_skipped_without_profile(monkeypatch):
    """Normal mode: no profile (or no connector) means no deep research tools."""
    monkeypatch.setattr("src.research.handler.deep_research_enabled", lambda: True)
    assert merge_builtin_deep_research_tools([], "s1", "u1") == []
    profile = SimpleNamespace(native_tool_groups=["web_research"])
    assert merge_builtin_deep_research_tools([], "s1", "u1", profile) == []


@pytest.mark.anyio
async def test_merge_builtin_deep_research_dedupes(monkeypatch):
    """An already-present trigger_research is not duplicated."""
    from haystack.tools import Tool

    monkeypatch.setattr("src.research.handler.deep_research_enabled", lambda: True)

    def _fake_trigger(topic: str) -> str:
        return topic

    existing = [
        Tool(
            name="trigger_research",
            description="already",
            function=_fake_trigger,
            parameters={"type": "object", "properties": {}},
        )
    ]
    profile = SimpleNamespace(native_tool_groups=["deep_research"])
    merged = merge_builtin_deep_research_tools(existing, "s1", "u1", profile)
    assert sum(1 for t in merged if t.name == "trigger_research") == 1


@pytest.mark.anyio
async def test_build_all_tools_deep_research_mode_without_connector(monkeypatch):
    """Deep Research mode adds the tools even when the profile has no connector."""
    names = await _tool_names_for(
        monkeypatch, ["sql_query_memory"], "sess-dr-3", agent_mode="deep_research"
    )
    assert set(DEEP_RESEARCH_BUILTIN_TOOL_NAMES).issubset(names)


@pytest.mark.anyio
async def test_build_all_tools_legacy_mcp_slug_is_connector(monkeypatch):
    """A profile listing the legacy deep_research MCP slug gets the tools in normal mode."""
    names = await _tool_names_for(
        monkeypatch, [], "sess-dr-4", mcp_servers=["deep_research"]
    )
    assert set(DEEP_RESEARCH_BUILTIN_TOOL_NAMES).issubset(names)


@pytest.mark.anyio
async def test_merge_deep_research_mode_without_profile(monkeypatch):
    """Deep Research mode works even without a profile object."""
    monkeypatch.setattr("src.research.handler.deep_research_enabled", lambda: True)
    merged = merge_builtin_deep_research_tools(
        [], "s1", "u1", None, agent_mode="deep_research"
    )
    assert {t.name for t in merged} == set(DEEP_RESEARCH_BUILTIN_TOOL_NAMES)


@pytest.mark.anyio
async def test_merge_deep_research_mode_disabled_globally(monkeypatch):
    """The global kill switch wins over Deep Research mode."""
    monkeypatch.setattr("src.research.handler.deep_research_enabled", lambda: False)
    assert (
        merge_builtin_deep_research_tools(
            [], "s1", "u1", None, agent_mode="deep_research"
        )
        == []
    )
