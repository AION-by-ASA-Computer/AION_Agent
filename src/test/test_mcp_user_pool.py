"""MCP user-scoped pool keys and chat prepare deduplication."""

import asyncio

import pytest

from src.mcp_manager import MCPManager, _parse_user_pool_key, _session_scoped_servers


def test_session_scoped_defaults():
    scoped = _session_scoped_servers()
    assert "session_sandbox" in scoped
    assert "ocr" in scoped
    assert "mempalace" not in scoped


def test_resolve_pool_key_user_vs_session(monkeypatch):
    monkeypatch.setenv("AION_MCP_USER_POOL", "1")
    mgr = MCPManager()
    sid = "conv-abc"
    mgr._session_ctx[sid] = ("postgres_metadata_assistant", "alice", "default")

    user_key_sandbox = mgr._resolve_pool_key(sid, "session_sandbox")
    assert user_key_sandbox == (sid, "session_sandbox")

    user_key_ocr = mgr._resolve_pool_key(sid, "ocr")
    assert user_key_ocr == (sid, "ocr")

    user_key = mgr._resolve_pool_key(sid, "mempalace")
    assert user_key == ("__user__alice__default", "mempalace")


def test_parse_user_pool_key():
    assert _parse_user_pool_key("__user__admin__default") == ("admin", "default")
    assert _parse_user_pool_key("__user__alice__tenant1") == ("alice", "tenant1")
    assert _parse_user_pool_key("conv-abc") is None


def test_agent_db_identity_prefers_injected_args_over_stale_env(monkeypatch):
    import src.aion_env  # noqa: F401

    from mcp_servers.agent_db.server import _resolve_effective_identity

    monkeypatch.setenv("AION_CURRENT_USER_ID", "default")
    monkeypatch.setenv("AION_CURRENT_TENANT_ID", "default")
    monkeypatch.setenv("AION_AGENT_DB_STRICT_IDENTITY", "1")

    uid, tid = _resolve_effective_identity(
        {"user_id": "admin", "tenant_id": "default"}
    )
    assert uid == "admin"
    assert tid == "default"


def test_resolve_pool_key_falls_back_without_ctx(monkeypatch):
    monkeypatch.setenv("AION_MCP_USER_POOL", "0")
    mgr = MCPManager()
    sid = "conv-xyz"
    key = mgr._resolve_pool_key(sid, "charts")
    assert key == (sid, "charts")


def test_chat_prepare_dedupes_inflight(monkeypatch):
    from src.api.v1 import chat as chat_api

    calls = 0

    async def fake_get_agent(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)

    monkeypatch.setattr(chat_api, "get_agent", fake_get_agent)

    async def run():
        from src.api.auth_login import ChatAuthIdentity

        body = chat_api.ChatPrepareBody(conversation_id="c1", profile="aion_std")
        auth = ChatAuthIdentity(via="anonymous", identifier="u1")

        r1 = await chat_api.chat_prepare(body, auth=auth, x_aion_user_id="u1")
        r2 = await chat_api.chat_prepare(body, auth=auth, x_aion_user_id="u1")

        assert r1["status"] == "warming"
        assert r2["status"] == "warming"

        task = chat_api._prepare_tasks.get("c1\0aion_std\0u1")
        assert task is not None
        await task
        assert calls == 1

    asyncio.run(run())
