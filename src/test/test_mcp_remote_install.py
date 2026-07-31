"""Remote MCP install helpers."""

from src.mcp_remote_install import build_remote_bridge_registry_config


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
