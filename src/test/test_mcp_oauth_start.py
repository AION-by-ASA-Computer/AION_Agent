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


@pytest.fixture
def oauth_request() -> MagicMock:
    req = MagicMock()
    req.url.scheme = "http"
    req.headers = {"host": "localhost:8001"}
    return req


def test_generate_pkce_pair() -> None:
    verifier, challenge = mod._generate_pkce_pair()
    assert len(verifier) >= 43
    assert challenge
    assert "=" not in challenge


def test_resolve_oauth_redirect_uri_absolute_passthrough() -> None:
    out = mod._resolve_oauth_redirect_uri(
        "https://client.example.com/api/v1/integrations/oauth/callback"
    )
    assert out == "https://client.example.com/api/v1/integrations/oauth/callback"


def test_resolve_oauth_redirect_uri_relative_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AION_OAUTH_REDIRECT_BASE_URL", "https://client.example.com/api")
    out = mod._resolve_oauth_redirect_uri("/api/v1/integrations/oauth/callback")
    assert out == "https://client.example.com/api/v1/integrations/oauth/callback"


def test_resolve_oauth_redirect_uri_relative_from_proxy_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AION_OAUTH_REDIRECT_BASE_URL", raising=False)
    monkeypatch.delenv("AION_PUBLIC_API_URL", raising=False)
    monkeypatch.delenv("AION_FASTAPI_URL", raising=False)
    monkeypatch.delenv("AION_CHAT_URL", raising=False)
    monkeypatch.delenv("DOMAIN", raising=False)
    request = MagicMock()
    request.url.scheme = "https"
    request.headers = {
        "x-forwarded-proto": "https",
        "x-forwarded-host": "client.example.com",
        "x-forwarded-prefix": "/api",
    }
    out = mod._resolve_oauth_redirect_uri(
        "/api/v1/integrations/oauth/callback", request
    )
    assert out == "https://client.example.com/api/v1/integrations/oauth/callback"


def test_resolve_oauth_redirect_uri_ignores_backend_port_public_api_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AION_PUBLIC_API_URL=http://localhost:8001 is internal; OAuth needs Caddy /api."""
    monkeypatch.delenv("AION_OAUTH_REDIRECT_BASE_URL", raising=False)
    monkeypatch.setenv("AION_PUBLIC_API_URL", "http://localhost:8001")
    request = MagicMock()
    request.url.scheme = "http"
    request.headers = {
        "host": "thinkstation:8066",
        "x-forwarded-proto": "http",
        "x-forwarded-host": "thinkstation:8066",
        "x-forwarded-prefix": "/api",
    }
    out = mod._resolve_oauth_redirect_uri(
        "/api/v1/integrations/oauth/callback", request
    )
    assert out == "http://thinkstation:8066/api/v1/integrations/oauth/callback"


def test_resolve_oauth_redirect_uri_public_api_url_with_api_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AION_OAUTH_REDIRECT_BASE_URL", raising=False)
    monkeypatch.setenv("AION_PUBLIC_API_URL", "https://client.example.com/api")
    out = mod._resolve_oauth_redirect_uri("/api/v1/integrations/oauth/callback")
    assert out == "https://client.example.com/api/v1/integrations/oauth/callback"


def test_resolve_oauth_redirect_uri_caddy_port_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AION_OAUTH_REDIRECT_BASE_URL", raising=False)
    monkeypatch.delenv("AION_PUBLIC_API_URL", raising=False)
    monkeypatch.delenv("AION_CHAT_URL", raising=False)
    monkeypatch.setenv("DOMAIN", ":80")
    monkeypatch.setenv("CADDY_HTTP_PORT", "8066")
    out = mod._resolve_oauth_redirect_uri("/api/v1/integrations/oauth/callback")
    assert out == "http://localhost:8066/api/v1/integrations/oauth/callback"


def test_chat_base_url_derives_from_oauth_redirect_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AION_CHAT_URL", "http://localhost:8003")
    monkeypatch.setenv("AION_OAUTH_REDIRECT_BASE_URL", "https://agnt2.aion-asa.com/api")
    assert mod._chat_base_url() == "https://agnt2.aion-asa.com"


def test_chat_base_url_prefers_explicit_public_chat_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AION_CHAT_URL", "http://localhost:8003")
    monkeypatch.setenv("AION_PUBLIC_CHAT_URL", "https://chat.example.com")
    assert mod._chat_base_url() == "https://chat.example.com"


def test_chat_base_url_from_proxy_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AION_CHAT_URL", raising=False)
    monkeypatch.delenv("AION_OAUTH_REDIRECT_BASE_URL", raising=False)
    monkeypatch.delenv("AION_PUBLIC_API_URL", raising=False)
    request = MagicMock()
    request.url.scheme = "https"
    request.headers = {
        "x-forwarded-proto": "https",
        "x-forwarded-host": "agnt2.aion-asa.com",
    }
    assert mod._chat_base_url(request) == "https://agnt2.aion-asa.com"


@pytest.mark.asyncio
async def test_oauth_start_retries_dynamic_registration_when_endpoints_cached(
    oauth_db: str, oauth_request: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Endpoints in DB without client_id must not skip RFC 7591 registration."""
    await insert_mcp_server_config(
        "clickup",
        oauth_config={
            "authorization_server": "https://mcp.clickup.com",
            "authorization_endpoint": "https://mcp.clickup.com/oauth/authorize",
            "token_url": "https://mcp.clickup.com/oauth/token",
            "registration_endpoint": "https://mcp.clickup.com/oauth/register",
        },
    )

    auth = ChatAuthIdentity(via="chat_token", identifier="alice", user_row_id="1")

    class _Resp:
        status_code = 201

        @staticmethod
        def json():
            return {"client_id": "dyn-client-xyz"}

    with patch.object(mod, "_cleanup_expired_states"):
        with patch("httpx.AsyncClient") as client_cls:
            client = AsyncMock()
            client_cls.return_value.__aenter__.return_value = client
            client.post = AsyncMock(return_value=_Resp())
            result = await mod.oauth_start(
                oauth_request,
                server_slug="clickup",
                redirect_uri="http://localhost:8001/v1/integrations/oauth/callback",
                auth=auth,
            )

    client.post.assert_called_once()
    parsed = urlparse(result["authorization_url"])
    params = parse_qs(parsed.query)
    assert params["client_id"] == ["dyn-client-xyz"]
    mod._oauth_pending.pop(result["state"], None)


@pytest.mark.asyncio
async def test_oauth_start_rejects_missing_client_id_when_registration_disabled(
    oauth_db: str, oauth_request: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AION_MCP_OAUTH_DYNAMIC_REGISTRATION", "0")
    await insert_mcp_server_config(
        "clickup",
        oauth_config={
            "authorization_server": "https://mcp.clickup.com",
            "authorization_endpoint": "https://mcp.clickup.com/oauth/authorize",
            "token_url": "https://mcp.clickup.com/oauth/token",
        },
    )
    auth = ChatAuthIdentity(via="chat_token", identifier="alice", user_row_id="1")
    with patch.object(mod, "_cleanup_expired_states"):
        with pytest.raises(Exception) as exc:
            await mod.oauth_start(
                oauth_request,
                server_slug="clickup",
                redirect_uri="http://localhost:8001/v1/integrations/oauth/callback",
                auth=auth,
            )
    assert "client_id" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_oauth_start_builds_authorization_url(
    oauth_db: str, oauth_request: MagicMock
) -> None:
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
            oauth_request,
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
    oauth_db: str, oauth_request: MagicMock, monkeypatch: pytest.MonkeyPatch
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
            oauth_request, server_slug="remote-svc", redirect_uri=None, auth=auth
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
async def test_oauth_start_rejects_microsoft_without_client_id(
    oauth_db: str, oauth_request: MagicMock
) -> None:
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
            oauth_request,
            server_slug="microsoft_sharepoint",
            redirect_uri=None,
            auth=auth,
        )
    assert "client ID" in str(exc.value.detail)
