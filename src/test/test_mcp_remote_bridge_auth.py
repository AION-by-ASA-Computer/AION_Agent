"""Tests for remote-bridge auth_env_var resolution."""

from __future__ import annotations

from src.mcp_credential_discovery import (
    _extract_remote_bridge_token_key,
    discover_mcp_credentials,
    resolve_remote_bridge_auth_env_var,
)


def test_resolve_remote_bridge_prefers_explicit_auth_env_var() -> None:
    cfg = {
        "type": "remote-bridge",
        "auth_env_var": "AION_USER_CLICKUP__OAUTH_TOKEN",
        "args": [
            "--header",
            "Authorization: Bearer ${AION_USER_OTHER__API_KEY}",
        ],
    }
    assert resolve_remote_bridge_auth_env_var(cfg) == "AION_USER_CLICKUP__OAUTH_TOKEN"


def test_extract_remote_bridge_token_key_from_args() -> None:
    cfg = {
        "args": [
            "node_modules/mcp-remote/dist/proxy.js",
            "https://mcp.example.com",
            "--header",
            "Authorization: Bearer ${AION_USER_CLICKUP__OAUTH_TOKEN}",
        ]
    }
    assert _extract_remote_bridge_token_key(cfg) == "AION_USER_CLICKUP__OAUTH_TOKEN"


def test_discover_remote_bridge_uses_auth_env_var(monkeypatch) -> None:
    cfg = {
        "type": "remote-bridge",
        "auth_env_var": "AION_USER_CLICKUP__OAUTH_TOKEN",
        "remote_url": "https://mcp.example.com",
        "args": ["--header", "Authorization: Bearer ${AION_USER_CLICKUP__OAUTH_TOKEN}"],
    }
    monkeypatch.setattr(
        "src.mcp_credential_discovery.probe_remote_url_sync",
        lambda *_a, **_k: {"type": "oauth2", "credential_mode": "per_user"},
    )
    result = discover_mcp_credentials("clickup", cfg)
    assert any(s.get("key") == "OAUTH_TOKEN" for s in result.schema)
