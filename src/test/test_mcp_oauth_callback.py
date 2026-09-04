"""Tests for OAuth callback token exchange."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.auth_login import ChatAuthIdentity
from src.api.v1 import mcp_integrations as mod
from src.api.v1.mcp_integrations import OAuthCallbackBody
from src.runtime import credential_store as cs
from src.runtime.oauth_token_exchange import OAuthTokenExchangeError
from src.test.mcp_oauth_test_helpers import insert_mcp_server_config


@pytest.mark.asyncio
async def test_oauth_callback_success(oauth_db: str) -> None:
    await insert_mcp_server_config(
        "clickup",
        oauth_config={
            "token_url": "https://auth.example.com/oauth/token",
            "client_id": "client-abc",
            "provider": "clickup",
        },
    )

    auth = ChatAuthIdentity(via="chat_token", identifier="alice", user_row_id="1")
    body = OAuthCallbackBody(
        server_slug="clickup",
        code="auth-code",
        state="state-1",
        code_verifier="verifier",
        redirect_uri="http://localhost:8001/v1/integrations/oauth/callback",
    )

    token_data = {
        "access_token": "access-123",
        "refresh_token": "refresh-456",
        "expires_in": 3600,
    }

    with (
        patch(
            "src.runtime.oauth_token_exchange.exchange_authorization_code",
            new=AsyncMock(return_value=token_data),
        ),
        patch(
            "src.runtime.mcp_credential_invalidate.invalidate_mcp_credentials_runtime",
            new=AsyncMock(),
        ),
    ):
        result = await mod.oauth_callback(body=body, auth=auth)

    assert result == {"ok": True, "server_slug": "clickup"}
    token = await cs.get_credential("alice", "clickup", "OAUTH_TOKEN")
    refresh = await cs.get_credential(
        "alice", "clickup", "OAUTH_REFRESH_TOKEN", auto_refresh_oauth=False
    )
    assert token == "access-123"
    assert refresh == "refresh-456"


@pytest.mark.asyncio
async def test_oauth_callback_provider_error(oauth_db: str) -> None:
    await insert_mcp_server_config(
        "clickup",
        oauth_config={"token_url": "https://auth.example.com/oauth/token"},
    )
    auth = ChatAuthIdentity(via="chat_token", identifier="alice", user_row_id="1")
    body = OAuthCallbackBody(server_slug="clickup", code="bad", state="s")

    with patch(
        "src.runtime.oauth_token_exchange.exchange_authorization_code",
        new=AsyncMock(
            side_effect=OAuthTokenExchangeError(
                "invalid_grant", status_code=400, body="invalid_grant"
            )
        ),
    ):
        with pytest.raises(Exception) as exc:
            await mod.oauth_callback(body=body, auth=auth)
    assert "invalid_grant" in str(exc.value)


@pytest.mark.asyncio
async def test_oauth_callback_redirect_invalid_state(oauth_db: str) -> None:
    from fastapi.responses import RedirectResponse
    from unittest.mock import MagicMock

    result = await mod.oauth_callback_redirect(
        code="c", state="missing-state", request=MagicMock()
    )
    assert isinstance(result, RedirectResponse)
    assert "oauth_status=error" in result.headers["location"]


@pytest.mark.asyncio
async def test_oauth_callback_redirect_success(oauth_db: str) -> None:
    await insert_mcp_server_config(
        "clickup",
        oauth_config={"token_url": "https://auth.example.com/oauth/token"},
    )

    state = "test-state"
    mod._oauth_pending[state] = {
        "server_slug": "clickup",
        "code_verifier": "verifier",
        "user_id": "alice",
        "redirect_uri": "http://localhost:8001/v1/integrations/oauth/callback",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    }

    token_data = {"access_token": "access-xyz", "expires_in": 3600}

    with (
        patch(
            "src.runtime.oauth_token_exchange.exchange_authorization_code",
            new=AsyncMock(return_value=token_data),
        ),
        patch(
            "src.runtime.mcp_credential_invalidate.invalidate_mcp_credentials_runtime",
            new=AsyncMock(),
        ),
    ):
        result = await mod.oauth_callback_redirect(
            code="auth-code", state=state, request=MagicMock()
        )

    assert "oauth_status=success" in result.headers["location"]
    token = await cs.get_credential("alice", "clickup", "OAUTH_TOKEN")
    assert token == "access-xyz"
