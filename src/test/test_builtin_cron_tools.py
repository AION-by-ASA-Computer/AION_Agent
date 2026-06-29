"""Cron tools are built-in when AION_CRON_ENABLED=1."""

from types import SimpleNamespace

import pytest

from src.main import build_all_tools
from src.runtime.cron_tools import CRON_BUILTIN_TOOL_NAMES


@pytest.mark.anyio
async def test_build_all_tools_includes_cron_when_enabled(monkeypatch):
    monkeypatch.setenv("AION_CRON_ENABLED", "1")

    async def _no_mcp(*_a, **_k):
        return []

    monkeypatch.setattr(
        "src.runtime.native_tools.load_native_tools", lambda *_a, **_k: []
    )
    monkeypatch.setattr("src.main.build_mcp_tools", _no_mcp)

    profile = SimpleNamespace(
        name="Generic Assistant",
        mcp_servers=["session_sandbox"],
    )

    tools = await build_all_tools("sess-cron-1", profile, user_id="u1")
    names = {getattr(t, "name", None) for t in tools}
    assert set(CRON_BUILTIN_TOOL_NAMES).issubset(names)


@pytest.mark.anyio
async def test_merge_builtin_cron_dedupes(monkeypatch):
    from haystack.tools import Tool

    from src.runtime.cron_tools import merge_builtin_cron_tools

    monkeypatch.setenv("AION_CRON_ENABLED", "1")

    def _fake_create(name: str, cron_expression: str, prompt: str) -> str:
        return "ok"

    existing = [
        Tool(
            name="create_scheduled_job",
            description="already",
            function=_fake_create,
            parameters={"type": "object", "properties": {}},
        )
    ]
    merged = merge_builtin_cron_tools(existing, "s1", "u1")
    assert sum(1 for t in merged if t.name == "create_scheduled_job") == 1
