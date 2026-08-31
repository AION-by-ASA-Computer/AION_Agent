"""Remote MCP install helpers."""

from src.mcp_remote_install import (
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
    monkeypatch.setattr(
        "src.mcp_remote_install.mcp_remote_proxy_path", lambda: None
    )
    cfg = build_remote_bridge_registry_config(
        "https://mcp.clickup.com/mcp", "clickup", auth_type="oauth2"
    )
    command, args = resolve_remote_bridge_spawn(cfg)
    assert command == "npx"
    assert args[0:2] == ["-y", "mcp-remote"]
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
