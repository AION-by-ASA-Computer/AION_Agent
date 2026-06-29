"""Deep Research tools are built-in for every profile when AION_DEEP_RESEARCH_ENABLED=1."""

from types import SimpleNamespace

import pytest

from src.main import build_all_tools
from src.runtime.deep_research_tools import (
    DEEP_RESEARCH_BUILTIN_TOOL_NAMES,
    merge_builtin_deep_research_tools,
)


@pytest.mark.anyio
async def test_build_all_tools_includes_deep_research_without_profile_bundle(monkeypatch):
    """Profiles without deep_research native_tool_group still get trigger_research."""

    async def _no_mcp(*_a, **_k):
        return []

    monkeypatch.setattr("src.runtime.native_tools.load_native_tools", lambda *_a, **_k: [])
    monkeypatch.setattr("src.main.build_mcp_tools", _no_mcp)
    monkeypatch.setattr("src.research.handler.deep_research_enabled", lambda: True)

    profile = SimpleNamespace(
        name="mysql_metadata_assistant",
        mcp_servers=[],
        native_tool_groups=["sql_query_memory"],
    )

    tools = await build_all_tools("sess-dr-1", profile, user_id="u1")
    names = {getattr(t, "name", None) for t in tools}

    assert set(DEEP_RESEARCH_BUILTIN_TOOL_NAMES).issubset(names), (
        f"missing built-in deep research tools: {set(DEEP_RESEARCH_BUILTIN_TOOL_NAMES) - names}"
    )


@pytest.mark.anyio
async def test_merge_builtin_deep_research_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr("src.research.handler.deep_research_enabled", lambda: False)
    merged = merge_builtin_deep_research_tools([], "s1", "u1")
    assert merged == []


@pytest.mark.anyio
async def test_merge_builtin_deep_research_dedupes(monkeypatch):
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
    merged = merge_builtin_deep_research_tools(existing, "s1", "u1")
    assert sum(1 for t in merged if t.name == "trigger_research") == 1
