"""Tests for OAuth PKCE helpers and /oauth/start."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from src.api.auth_login import ChatAuthIdentity
from src.api.v1 import mcp_integrations as mod
from src.test.mcp_oauth_test_helpers import insert_mcp_server_config


def test_generate_pkce_pair() -> None:
    verifier, challenge = mod._generate_pkce_pair()
    assert len(verifier) >= 43
    assert challenge
    assert "=" not in challenge


@pytest.mark.asyncio
async def test_oauth_start_builds_authorization_url(oauth_db: str) -> None:
    await insert_mcp_server_config(
        "clickup",
        oauth_config={
            "authorization_server": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/oauth/authorize",
            "token_url": "https://auth.example.com/oauth/token",
            "client_id": "client-abc",
            "scope": "read",
        },
    )

    auth = ChatAuthIdentity(via="chat_token", identifier="alice", user_row_id="1")

    with patch.object(mod, "_cleanup_expired_states"):
        result = await mod.oauth_start(
            server_slug="clickup",
            redirect_uri="http://localhost:8001/v1/integrations/oauth/callback",
            auth=auth,
        )

    assert "authorization_url" in result
    assert "state" in result
    assert result["state"] in mod._oauth_pending

    pending = mod._oauth_pending[result["state"]]
    assert pending["server_slug"] == "clickup"
    assert pending["user_id"]
    assert pending["code_verifier"]

    parsed = urlparse(result["authorization_url"])
    params = parse_qs(parsed.query)
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["client-abc"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["read"]
    assert params["state"] == [result["state"]]

    mod._oauth_pending.pop(result["state"], None)


@pytest.mark.asyncio
async def test_oauth_start_skips_dynamic_registration_when_disabled(
    oauth_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AION_MCP_OAUTH_DYNAMIC_REGISTRATION", "0")
    await insert_mcp_server_config(
        "remote-svc",
        oauth_config={
            "authorization_server": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/oauth/authorize",
            "token_url": "https://auth.example.com/oauth/token",
            "client_id": "manual-client",
            "registration_endpoint": "https://auth.example.com/oauth/register",
        },
    )

    auth = ChatAuthIdentity(via="chat_token", identifier="alice", user_row_id="1")

    with patch("httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        client_cls.return_value.__aenter__.return_value = client
        client.post = AsyncMock()
        result = await mod.oauth_start(
            server_slug="remote-svc", redirect_uri=None, auth=auth
        )

    client.post.assert_not_called()
    assert "authorization_url" in result
    mod._oauth_pending.pop(result["state"], None)


def test_apply_catalog_oauth_defaults_for_gmail() -> None:
    reg_cfg = {
        "type": "remote-bridge",
        "remote_url": "https://gmailmcp.googleapis.com/mcp/v1",
        "aion_connector_id": "gmail",
    }
    out = mod._apply_catalog_oauth_defaults({}, "gmail", reg_cfg)
    assert out["authorization_server"] == "https://accounts.google.com"
    assert (
        out["authorization_endpoint"] == "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert out["token_url"] == "https://oauth2.googleapis.com/token"
    assert out.get("client_credentials_required") is True
    assert any("gmail.readonly" in s for s in out.get("scopes", []))


def test_apply_catalog_oauth_defaults_for_github() -> None:
    reg_cfg = {
        "type": "remote-bridge",
        "remote_url": "https://api.githubcopilot.com/mcp",
        "aion_connector_id": "github",
    }
    out = mod._apply_catalog_oauth_defaults(
        {
            "authorization_server": "https://api.githubcopilot.com",
            "token_url": "https://api.githubcopilot.com/token",
        },
        "github",
        reg_cfg,
    )
    assert out["authorization_endpoint"] == "https://github.com/login/oauth/authorize"
    assert out["token_url"] == "https://github.com/login/oauth/access_token"
    assert out.get("resource") == "https://api.githubcopilot.com/mcp"


def test_apply_catalog_oauth_defaults_for_sharepoint_resolves_tenant() -> None:
    tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    reg_cfg = {
        "type": "remote-bridge",
        "remote_url": (
            f"https://agent365.svc.cloud.microsoft/agents/tenants/{tenant}"
            "/servers/mcp_SharePointRemoteServer"
        ),
        "aion_connector_id": "microsoft_sharepoint",
    }
    out = mod._apply_catalog_oauth_defaults({}, "microsoft_sharepoint", reg_cfg)
    assert tenant in out["authorization_endpoint"]
    assert out.get("client_credentials_required") is True


@pytest.mark.asyncio
async def test_oauth_start_rejects_microsoft_without_client_id(oauth_db: str) -> None:
    tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    await insert_mcp_server_config(
        "microsoft_sharepoint",
        oauth_config={
            "authorization_endpoint": (
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
            ),
            "token_url": f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            "client_credentials_required": True,
        },
    )
    auth = ChatAuthIdentity(via="chat_token", identifier="alice", user_row_id="1")
    with pytest.raises(Exception) as exc:
        await mod.oauth_start(
            server_slug="microsoft_sharepoint", redirect_uri=None, auth=auth
        )
    assert "client ID" in str(exc.value.detail)
