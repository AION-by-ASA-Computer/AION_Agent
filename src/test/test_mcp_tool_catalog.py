"""list_tools catalog is per user/server and skips session-scoped servers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.mcp_manager import _DEFAULT_SESSION_SCOPED_SERVERS
from src.runtime.mcp_tool_catalog import McpToolCatalog, clear_mcp_tool_catalog
from src.settings import AionSettings


def test_catalog_roundtrip_and_fingerprint():
    cat = McpToolCatalog()
    cfg = {"type": "stdio", "command": "python", "args": ["-u", "x.py"]}
    key = cat.key(
        user_id="default", tenant_id="default", server_name="grafana", server_config=cfg
    )
    cat.put(key, [{"name": "query", "description": "", "input_schema": {}}])
    assert cat.get(key)[0]["name"] == "query"
    other = dict(cfg)
    other["command"] = "uv"
    assert (
        cat.key(
            user_id="default",
            tenant_id="default",
            server_name="grafana",
            server_config=other,
        )
        != key
    )


def test_session_scoped_defaults_keep_query_memory_and_drop_memory():
    assert "session_sandbox" in _DEFAULT_SESSION_SCOPED_SERVERS
    assert "query_memory" in _DEFAULT_SESSION_SCOPED_SERVERS
    assert "grafana" not in _DEFAULT_SESSION_SCOPED_SERVERS
    assert "geocoding" not in _DEFAULT_SESSION_SCOPED_SERVERS
    assert "memory" not in _DEFAULT_SESSION_SCOPED_SERVERS
    assert "mempalace" not in _DEFAULT_SESSION_SCOPED_SERVERS
    default = AionSettings.model_fields["mcp_session_scoped_servers"].default
    assert "memory" not in [p.strip() for p in default.split(",")]


@pytest.mark.anyio
async def test_second_session_reuses_schema_and_builds_a_new_wrapper(monkeypatch):
    from src.main import build_mcp_tools
    from src.mcp_manager import mcp_manager

    calls = {"n": 0}

    class _Result:
        def __init__(self):
            calls["n"] += 1
            self.tools = [
                SimpleNamespace(
                    name="query",
                    description="q",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]

    class _Session:
        async def list_tools(self):
            return _Result()

    class _Ctx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(mcp_manager, "stdio_entrypoint_missing", lambda *_a, **_k: None)
    monkeypatch.setattr(mcp_manager, "session_context", lambda *_a, **_k: _Ctx())
    monkeypatch.setattr(
        "src.mcp_manager.is_session_scoped_server", lambda _name: False
    )
    clear_mcp_tool_catalog()
    cfg = {"type": "stdio", "command": "python", "args": ["-u", "grafana/server.py"]}
    try:
        first = await build_mcp_tools("grafana", cfg, "session-a", user_id="default")
        second = await build_mcp_tools("grafana", cfg, "session-b", user_id="default")
    finally:
        clear_mcp_tool_catalog()
    assert calls["n"] == 1
    assert first[0].name == "query"
    assert second[0].name == "query"
    assert first[0].function is not second[0].function
