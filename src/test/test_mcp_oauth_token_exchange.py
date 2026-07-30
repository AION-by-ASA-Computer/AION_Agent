"""Tests for OAuth token exchange helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.runtime.oauth_token_exchange import (
    OAuthTokenExchangeError,
    exchange_authorization_code,
    exchange_refresh_token,
    token_expires_at,
)


def test_token_expires_at_parses_expires_in() -> None:
    exp = token_expires_at({"expires_in": 3600})
    assert exp is not None


@pytest.mark.asyncio
async def test_exchange_authorization_code_success() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "tok", "expires_in": 60}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        client_cls.return_value.__aenter__.return_value = client
        client.post = AsyncMock(return_value=mock_resp)
        data = await exchange_authorization_code(
            "https://auth.example.com/token",
            code="code",
            redirect_uri="http://localhost/cb",
            code_verifier="verifier",
            client_id="cid",
        )

    assert data["access_token"] == "tok"
    posted = client.post.await_args
    assert posted.args[0] == "https://auth.example.com/token"
    assert posted.kwargs["data"]["grant_type"] == "authorization_code"


@pytest.mark.asyncio
async def test_exchange_refresh_token_success() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "new", "expires_in": 60}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        client_cls.return_value.__aenter__.return_value = client
        client.post = AsyncMock(return_value=mock_resp)
        data = await exchange_refresh_token(
            "https://auth.example.com/token",
            refresh_token="refresh",
            client_id="cid",
        )

    assert data["access_token"] == "new"
    assert client.post.await_args.kwargs["data"]["grant_type"] == "refresh_token"


@pytest.mark.asyncio
async def test_exchange_token_http_error() -> None:
    import httpx

    response = MagicMock()
    response.status_code = 400
    response.text = "invalid_grant"

    with patch("httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        client_cls.return_value.__aenter__.return_value = client
        client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "bad", request=MagicMock(), response=response
            )
        )
        with pytest.raises(OAuthTokenExchangeError) as exc:
            await exchange_refresh_token(
                "https://auth.example.com/token", refresh_token="bad"
            )

    assert exc.value.status_code == 400
