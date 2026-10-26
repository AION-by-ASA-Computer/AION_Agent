"""Remote MCP install helpers."""

import json
from pathlib import Path

from src.mcp_remote_install import (
    MCP_REMOTE_VERSION,
    build_remote_bridge_registry_config,
    resolve_remote_bridge_spawn,
)


def test_build_remote_bridge_oauth():
    cfg = build_remote_bridge_registry_config(
        "https://mcp.example.com/mcp", "my_svc", auth_type="oauth2"
    )
    assert cfg["type"] == "remote-bridge"
    assert cfg["remote_url"] == "https://mcp.example.com/mcp"
    assert cfg["auth_env_var"] == "AION_USER_MY_SVC__OAUTH_TOKEN"
    assert "Authorization: Bearer" in " ".join(cfg["args"])


def test_build_remote_bridge_none():
    cfg = build_remote_bridge_registry_config(
        "https://mcp.example.com/mcp", "public", auth_type="none"
    )
    assert "auth_env_var" not in cfg
    assert not any("Authorization" in str(a) for a in cfg["args"])


def test_resolve_remote_bridge_spawn_uses_npx_when_local_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr("src.mcp_remote_install.mcp_remote_proxy_path", lambda: None)
    cfg = build_remote_bridge_registry_config(
        "https://mcp.clickup.com/mcp", "clickup", auth_type="oauth2"
    )
    command, args = resolve_remote_bridge_spawn(cfg)
    assert command == "npx"
    assert args[0:2] == ["-y", f"mcp-remote@{MCP_REMOTE_VERSION}"]
    assert args[2] == "https://mcp.clickup.com/mcp"
    assert "--header" in args


def test_resolve_remote_bridge_spawn_uses_local_proxy(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.mcp_remote_install.mcp_remote_proxy_path",
        lambda: "/app/node_modules/mcp-remote/dist/proxy.js",
    )
    cfg = build_remote_bridge_registry_config(
        "https://mcp.clickup.com/mcp", "clickup", auth_type="oauth2"
    )
    command, args = resolve_remote_bridge_spawn(cfg)
    assert command == "node"
    assert args[0] == "/app/node_modules/mcp-remote/dist/proxy.js"
    assert args[1] == "https://mcp.clickup.com/mcp"


def test_build_remote_bridge_org_shared_auth_env_var() -> None:
    cfg = build_remote_bridge_registry_config(
        "http://broker:8080/mcp",
        "ssh_broker",
        auth_type="api-key",
        credential_mode="org_shared",
    )
    assert cfg["auth_env_var"] == "API_KEY"
    assert cfg["env"] == {"API_KEY": "${API_KEY}"}
    assert "Authorization: Bearer ${API_KEY}" in cfg["args"]


def test_mcp_remote_version_matches_docker_package() -> None:
    docker = Path(__file__).resolve().parents[2] / "docker"
    pkg = json.loads((docker / "package.mcp-remote.json").read_text())
    lock = json.loads((docker / "package-lock.mcp-remote.json").read_text())
    assert pkg["dependencies"]["mcp-remote"] == MCP_REMOTE_VERSION
    assert lock["packages"]["node_modules/mcp-remote"]["version"] == MCP_REMOTE_VERSION


def _broker_cfg(**extra):
    cfg = build_remote_bridge_registry_config(
        "http://ssh-broker:8080/mcp",
        "ssh_broker",
        auth_type="api-key",
        credential_mode="org_shared",
    )
    cfg.update(extra)
    return cfg


def test_allow_http_appends_flag_after_header(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.mcp_remote_install.mcp_remote_proxy_path",
        lambda: "/app/node_modules/mcp-remote/dist/proxy.js",
    )
    cfg = _broker_cfg(allow_http=True)
    _, args = resolve_remote_bridge_spawn(cfg)
    assert args[-1] == "--allow-http"
    assert args.index("--header") < args.index("--allow-http")
    assert "--allow-http" not in cfg["args"]


def test_allow_http_with_npx_fallback(monkeypatch) -> None:
    monkeypatch.setattr("src.mcp_remote_install.mcp_remote_proxy_path", lambda: None)
    monkeypatch.setattr(
        "src.mcp_remote_install.shutil.which", lambda _c: "/usr/bin/npx"
    )
    _, args = resolve_remote_bridge_spawn(_broker_cfg(allow_http=True))
    assert args[-1] == "--allow-http"


def test_allow_http_absent_or_false_adds_nothing(monkeypatch) -> None:
    monkeypatch.setattr("src.mcp_remote_install.mcp_remote_proxy_path", lambda: None)
    monkeypatch.setattr(
        "src.mcp_remote_install.shutil.which", lambda _c: "/usr/bin/npx"
    )
    for cfg in (_broker_cfg(), _broker_cfg(allow_http=False)):
        _, args = resolve_remote_bridge_spawn(cfg)
        assert "--allow-http" not in args
