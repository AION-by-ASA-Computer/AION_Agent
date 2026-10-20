"""mcp-remote non parte senza token e i server per utente non ricadono su 'default'."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

import src.mcp_manager as mm
from src.mcp_manager import (
    BOOTSTRAP_SESSION_ID,
    MCPManager,
    MCPStdioWorker,
    _remote_bridge_auth_missing,
    _server_needs_user_credentials,
)

KHUB_CFG: Dict[str, Any] = {
    "type": "remote-bridge",
    "command": "node",
    "args": [
        "node_modules/mcp-remote/dist/proxy.js",
        "https://khub.example.com/mcp",
        "--header",
        "Authorization: Bearer ${AION_USER_KHUB__OAUTH_TOKEN}",
    ],
    "env": {"AION_USER_KHUB__OAUTH_TOKEN": "${AION_USER_KHUB__OAUTH_TOKEN}"},
    "auth_env_var": "AION_USER_KHUB__OAUTH_TOKEN",
}
SYSTEM_CFG: Dict[str, Any] = {"type": "stdio", "command": "python", "args": ["x.py"]}


def _manager(monkeypatch: pytest.MonkeyPatch, **cfgs: Dict[str, Any]) -> MCPManager:
    mgr = MCPManager()
    monkeypatch.setattr(mgr, "get_server_config", lambda name: cfgs.get(name))
    return mgr


def test_remote_bridge_auth_missing() -> None:
    msg = _remote_bridge_auth_missing("khub", KHUB_CFG, {})
    assert msg and "OAuth non connesso per khub" in msg
    assert "credenziali mancanti" in msg
    blank = {"AION_USER_KHUB__OAUTH_TOKEN": "  "}
    assert _remote_bridge_auth_missing("khub", KHUB_CFG, blank)
    ok = {"AION_USER_KHUB__OAUTH_TOKEN": "tok"}
    assert _remote_bridge_auth_missing("khub", KHUB_CFG, ok) is None
    assert _remote_bridge_auth_missing("sys", SYSTEM_CFG, {}) is None


def test_remote_bridge_detected_from_args_and_header() -> None:
    cfg = {k: v for k, v in KHUB_CFG.items() if k not in ("type", "auth_env_var")}
    assert _remote_bridge_auth_missing("khub", cfg, {})


def test_server_needs_user_credentials() -> None:
    assert _server_needs_user_credentials(KHUB_CFG)
    assert not _server_needs_user_credentials(SYSTEM_CFG)
    assert not _server_needs_user_credentials(None)
    assert _server_needs_user_credentials({"env": {"K": "${AION_USER_X__API_KEY}"}})
    assert not _server_needs_user_credentials({"env": {"K": "static"}})


def test_pool_key_does_not_borrow_bootstrap_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AION_MCP_USER_POOL", "1")
    monkeypatch.setattr(mm, "_USE_POOL", True)
    mgr = _manager(monkeypatch, khub=KHUB_CFG, charts=SYSTEM_CFG)
    mgr._session_ctx[BOOTSTRAP_SESSION_ID] = ("generic_assistant", "admin", "default")

    assert mgr._resolve_pool_key("conv-x", "khub") == ("conv-x", "khub")
    assert mgr._resolve_pool_key("conv-x", "charts") == (
        "__user__admin__default",
        "charts",
    )
    assert mgr._resolve_pool_key(BOOTSTRAP_SESSION_ID, "khub") == (
        "__user__admin__default",
        "khub",
    )


def test_warm_credentials_missing_without_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = _manager(monkeypatch, khub=KHUB_CFG)
    msg = asyncio.run(mgr._warm_credentials_missing("conv-x", "khub"))
    assert msg and "contesto utente mancante" in msg


def _run_worker(
    monkeypatch: pytest.MonkeyPatch, mgr: MCPManager, make_worker, env
) -> tuple:
    spawned: list = []

    def fake_stdio_client(params):
        spawned.append(params)
        raise AssertionError("mcp-remote non doveva partire")

    async def fake_resolve(*_a, **_k):
        return dict(env)

    import src.runtime.credential_store as cs

    monkeypatch.setattr(mm, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(cs, "resolve_mcp_env_for_user", fake_resolve)
    monkeypatch.setattr(mm, "_apply_mcp_home_isolation", lambda env, uid: None)
    monkeypatch.setattr(
        mgr, "resolve_stdio_spawn_command", lambda n, c: (c["command"], c["args"])
    )

    async def run() -> MCPStdioWorker:
        worker = make_worker()
        await worker._run()
        return worker

    return spawned, asyncio.run(run())


def test_worker_without_token_does_not_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AION_USER_KHUB__OAUTH_TOKEN", raising=False)
    mgr = _manager(monkeypatch, khub=KHUB_CFG)
    spawned, worker = _run_worker(
        monkeypatch,
        mgr,
        lambda: MCPStdioWorker(mgr, "khub", "", pool_user_id="default"),
        env={},
    )
    assert spawned == []
    assert "OAuth non connesso" in str(worker._init_error)


def test_worker_without_context_does_not_fall_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = _manager(monkeypatch, khub=KHUB_CFG)
    mgr._session_ctx[BOOTSTRAP_SESSION_ID] = ("generic_assistant", "admin", "default")
    spawned, worker = _run_worker(
        monkeypatch,
        mgr,
        lambda: MCPStdioWorker(mgr, "khub", "conv-x"),
        env={"AION_USER_KHUB__OAUTH_TOKEN": "tok"},
    )
    assert spawned == []
    assert "contesto utente mancante" in str(worker._init_error)


def test_ephemeral_session_without_token_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AION_USER_KHUB__OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(mm, "_USE_POOL", False)
    mgr = _manager(monkeypatch, khub=KHUB_CFG)
    monkeypatch.setattr(mgr, "load_registry", lambda *a, **k: None)
    mgr._session_ctx["conv-x"] = ("generic_assistant", "alice", "default")
    spawned = []
    monkeypatch.setattr(mm, "stdio_client", lambda p: spawned.append(p))

    async def fake_resolve(*_a, **_k):
        return {}

    import src.runtime.credential_store as cs

    monkeypatch.setattr(cs, "resolve_mcp_env_for_user", fake_resolve)
    monkeypatch.setattr(mm, "_apply_mcp_home_isolation", lambda env, uid: None)
    monkeypatch.setattr(
        mgr, "resolve_stdio_spawn_command", lambda n, c: (c["command"], c["args"])
    )

    async def run() -> None:
        async with mgr.session_context("khub", chat_session_id="conv-x"):
            pass

    with pytest.raises(RuntimeError, match="OAuth non connesso"):
        asyncio.run(run())
    assert spawned == []


def test_startup_preload_skips_servers_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main_mod
    from src.agent_profile import profile_manager
    from src.runtime import mcp_startup_warm as warm

    class _Profile:
        mcp_servers = ["khub"]

    monkeypatch.setattr(profile_manager, "load_all_if_stale", lambda: None)
    monkeypatch.setattr(profile_manager, "get_profile", lambda slug: _Profile())
    mgr = mm.mcp_manager
    monkeypatch.setattr(mgr, "get_server_config", lambda name: KHUB_CFG)

    async def fake_missing(sid, name):
        return "credenziali mancanti per khub"

    monkeypatch.setattr(mgr, "_warm_credentials_missing", fake_missing)
    built = []

    async def fake_build(*a, **k):
        built.append(a)

    monkeypatch.setattr(main_mod, "build_mcp_tools", fake_build)
    asyncio.run(warm._preload_shared_tool_catalog(["default"]))
    assert built == []
