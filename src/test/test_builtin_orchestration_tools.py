"""Orchestration mark_task_completed is built-in for every profile."""

from types import SimpleNamespace

import pytest

from src.main import build_all_tools
from src.runtime.orchestration_tools import ORCHESTRATION_BUILTIN_TOOL_NAMES


@pytest.mark.anyio
async def test_build_all_tools_includes_orchestration_without_profile_entry(
    monkeypatch,
):
    """Profiles without orchestration in mcp_servers still get mark_task_completed."""

    async def _no_mcp(*_a, **_k):
        return []

    monkeypatch.setattr(
        "src.runtime.native_tools.load_native_tools", lambda *_a, **_k: []
    )
    monkeypatch.setattr("src.main.build_mcp_tools", _no_mcp)

    profile = SimpleNamespace(
        name="Coding Workspace",
        mcp_servers=["session_sandbox", "code", "skills_hub", "memory"],
    )

    tools = await build_all_tools("sess-test-1", profile, user_id="u1")
    names = {getattr(t, "name", None) for t in tools}

    assert set(ORCHESTRATION_BUILTIN_TOOL_NAMES).issubset(names), (
        f"missing built-in tools: {set(ORCHESTRATION_BUILTIN_TOOL_NAMES) - names}"
    )


@pytest.mark.anyio
async def test_merge_builtin_orchestration_dedupes(monkeypatch):
    from haystack.tools import Tool

    from src.runtime.orchestration_tools import merge_builtin_orchestration_tools

    def _fake_mark(plan_id: str, task_id: str) -> str:
        return "ok"

    existing = [
        Tool(
            name="mark_task_completed",
            description="already",
            function=_fake_mark,
            parameters={"type": "object", "properties": {}},
        )
    ]
    merged = merge_builtin_orchestration_tools(existing, "s1", "u1")
    assert sum(1 for t in merged if t.name == "mark_task_completed") == 1
