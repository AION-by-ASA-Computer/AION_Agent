"""P2 Sprint 2–3 — MCP settings, registry cache, session-scoped pool."""

from pathlib import Path

import src.mcp_manager as mm
from src.mcp_manager import MCPManager, _pool_enabled, _session_scoped_servers
from src.runtime.session_context import SessionContext


def test_mcp_registry_mtime_cache(tmp_path: Path):
    reg = tmp_path / "mcp_registry.yaml"
    reg.write_text("server_a:\n  command: echo\n", encoding="utf-8")
    local = tmp_path / "mcp_registry.local.yaml"
    local.write_text("{}\n", encoding="utf-8")
    mgr = MCPManager(registry_path=str(reg), local_registry_path=str(local))
    assert "server_a" in mgr._registry
    before = dict(mgr._registry)
    mgr.load_registry()
    assert mgr._registry == before
    reg.write_text("server_b:\n  command: echo\n", encoding="utf-8")
    mgr.load_registry()
    assert "server_b" in mgr._registry
    assert "server_a" not in mgr._registry


def test_session_scoped_pool_two_conversations(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mm, "_USE_POOL", True)
    monkeypatch.setenv("AION_MCP_USER_POOL", "1")
    monkeypatch.setenv("AION_MCP_SESSION_SCOPED_SERVERS", "session_sandbox")
    reg = tmp_path / "mcp_registry.yaml"
    reg.write_text("session_sandbox:\n  command: echo\n", encoding="utf-8")
    mgr = MCPManager(
        registry_path=str(reg), local_registry_path=str(tmp_path / "local.yaml")
    )
    server = "session_sandbox"
    assert server in _session_scoped_servers()
    k1 = mgr._resolve_pool_key("conv-a", server)
    k2 = mgr._resolve_pool_key("conv-b", server)
    assert k1 == ("conv-a", server)
    assert k2 == ("conv-b", server)
    assert k1 != k2
    mgr.set_session_context(
        "conv-a",
        SessionContext(
            profile_slug="aion_std", user_id="alice", conversation_id="conv-a"
        ),
    )
    k_user = mgr._resolve_pool_key("conv-a", "other_server")
    assert k_user[0].startswith("__user__alice")


def test_mcp_pool_default_on(monkeypatch):
    monkeypatch.delenv("AION_MCP_POOL", raising=False)
    assert _pool_enabled() is True
