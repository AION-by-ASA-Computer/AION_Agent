"""I server MCP stdio non ereditano i segreti del backend (FIX-03)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

import src.mcp_manager as mm
from src.mcp_manager import MCPManager, MCPStdioWorker, _is_first_party_stdio
from src.security.session_env import build_mcp_stdio_base_env

SECRETS = {
    "AION_CHAT_AUTH_SECRET": "sign-me",
    "AION_CHAT_UI_INTERNAL_SECRET": "internal",
    "AION_SETUP_CHAT_PASSWORD": "pw",
    "AION_CREDENTIAL_ENCRYPTION_KEY": "enc",
    "AION_DB_URL": "sqlite:///x.db",
    "AION_LLM_API_KEY": "llm",
    "OPENAI_API_KEY": "sk-x",
}
BROKER_CFG: Dict[str, Any] = {
    "type": "remote-bridge",
    "command": "node",
    "args": [
        "node_modules/mcp-remote/dist/proxy.js",
        "https://broker.local/mcp",
        "--header",
        "Authorization: Bearer ${API_KEY}",
    ],
    "env": {"API_KEY": "${API_KEY}"},
    "remote_url": "https://broker.local/mcp",
}
NPX_CFG: Dict[str, Any] = {"command": "npx", "args": ["-y", "some-mcp"]}
LOCAL_CFG: Dict[str, Any] = {
    "command": "python",
    "args": ["-u", str(mm._repo_root() / "mcp_servers" / "charts" / "server.py")],
}


@pytest.fixture
def secrets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:3128")
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", "/etc/ca.pem")
    monkeypatch.delenv("AION_MCP_ENV_SCRUB", raising=False)
    monkeypatch.delenv("AION_MCP_ENV_ALLOWLIST", raising=False)


def test_first_party_detection() -> None:
    assert _is_first_party_stdio("/usr/bin/python3", LOCAL_CFG["args"], LOCAL_CFG)
    assert _is_first_party_stdio(
        "python", ["-m", "mcp_servers.agent_db.server"], {"command": "python"}
    )
    assert not _is_first_party_stdio("python", ["-m", "other_pkg"], {})
    assert not _is_first_party_stdio("python", ["-u", "/opt/ext/server.py"], {})
    assert not _is_first_party_stdio("npx", NPX_CFG["args"], NPX_CFG)
    assert not _is_first_party_stdio("node", BROKER_CFG["args"], BROKER_CFG)


def test_third_party_base_env_is_allowlisted(secrets_env, monkeypatch) -> None:
    env = build_mcp_stdio_base_env(first_party=False)
    assert not [k for k in env if k.startswith("AION_")]
    assert "OPENAI_API_KEY" not in env
    assert env["HTTPS_PROXY"] == "http://proxy:3128"
    assert env["NODE_EXTRA_CA_CERTS"] == "/etc/ca.pem"
    assert "PATH" in env

    monkeypatch.setenv("AION_MCP_ENV_ALLOWLIST", "OPENAI_API_KEY")
    assert build_mcp_stdio_base_env(first_party=False)["OPENAI_API_KEY"] == "sk-x"


def test_first_party_base_env_drops_only_signing_secrets(secrets_env) -> None:
    env = build_mcp_stdio_base_env(first_party=True)
    assert "AION_CHAT_AUTH_SECRET" not in env
    assert "AION_CHAT_UI_INTERNAL_SECRET" not in env
    assert "AION_SETUP_CHAT_PASSWORD" not in env
    assert env["AION_DB_URL"] == "sqlite:///x.db"
    assert env["AION_CREDENTIAL_ENCRYPTION_KEY"] == "enc"
    assert env["AION_LLM_API_KEY"] == "llm"


def test_scrub_can_be_disabled(secrets_env, monkeypatch) -> None:
    monkeypatch.setenv("AION_MCP_ENV_SCRUB", "0")
    assert build_mcp_stdio_base_env(first_party=False)["AION_CHAT_AUTH_SECRET"]


def _spawned_env(
    monkeypatch: pytest.MonkeyPatch, cfg: Dict[str, Any], resolved: Dict[str, str]
) -> Dict[str, str]:
    spawned: List[Any] = []

    def fake_stdio_client(params):
        spawned.append(params)
        raise RuntimeError("stop after spawn")

    async def fake_resolve(*_a, **_k):
        return dict(resolved)

    import src.runtime.credential_store as cs

    mgr = MCPManager()
    monkeypatch.setattr(mgr, "get_server_config", lambda name: cfg)
    monkeypatch.setattr(
        mgr, "resolve_stdio_spawn_command", lambda n, c: (c["command"], c["args"])
    )
    monkeypatch.setattr(mm, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(cs, "resolve_mcp_env_for_user", fake_resolve)
    monkeypatch.setattr(mm, "_apply_mcp_home_isolation", lambda env, uid: None)

    async def run() -> None:
        worker = MCPStdioWorker(mgr, "srv", "", pool_user_id="sre-bot")
        await worker._run()

    asyncio.run(run())
    assert len(spawned) == 1
    return dict(spawned[0].env)


def test_remote_bridge_gets_token_but_no_backend_secrets(
    secrets_env, monkeypatch
) -> None:
    env = _spawned_env(monkeypatch, BROKER_CFG, {"API_KEY": "broker-token"})
    assert env["API_KEY"] == "broker-token"
    assert env["MCP_REMOTE_URL"] == BROKER_CFG["remote_url"]
    assert env["HTTPS_PROXY"] == "http://proxy:3128"
    aion = {k for k in env if k.startswith("AION_")}
    assert aion <= {
        "AION_CHAT_SESSION_ID",
        "AION_CURRENT_PROFILE_SLUG",
        "AION_CURRENT_USER_ID",
        "AION_CURRENT_TENANT_ID",
    }


def test_local_server_keeps_config_without_signing_secret(
    secrets_env, monkeypatch
) -> None:
    env = _spawned_env(monkeypatch, LOCAL_CFG, {})
    assert "AION_CHAT_AUTH_SECRET" not in env
    assert env["AION_DB_URL"] == "sqlite:///x.db"
