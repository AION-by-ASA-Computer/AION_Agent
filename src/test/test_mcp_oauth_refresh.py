"""Tests for OAuth token refresh in credential_store."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.runtime import credential_store as cs
from src.runtime.oauth_token_exchange import OAuthTokenExchangeError
from src.test.mcp_oauth_test_helpers import insert_mcp_server_config


def _expired() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=1)


@pytest.mark.asyncio
async def test_refresh_success_updates_access_token(oauth_db: str) -> None:
    await insert_mcp_server_config(
        "clickup",
        oauth_config={
            "token_url": "https://auth.example.com/oauth/token",
            "client_id": "client-abc",
        },
    )

    await cs.set_credential(
        "alice",
        "clickup",
        "OAUTH_TOKEN",
        "old-access",
        expires_at=_expired(),
    )
    await cs.set_credential(
        "alice",
        "clickup",
        "OAUTH_REFRESH_TOKEN",
        "refresh-valid",
    )

    token_data = {
        "access_token": "new-access",
        "expires_in": 3600,
        "refresh_token": "refresh-rotated",
    }

    with (
        patch(
            "src.runtime.oauth_token_exchange.exchange_refresh_token",
            new=AsyncMock(return_value=token_data),
        ),
        patch(
            "src.runtime.mcp_credential_invalidate.invalidate_mcp_credentials_runtime",
            new=AsyncMock(),
        ),
    ):
        token = await cs.get_credential("alice", "clickup", "OAUTH_TOKEN")

    assert token == "new-access"
    refresh = await cs.get_credential(
        "alice", "clickup", "OAUTH_REFRESH_TOKEN", auto_refresh_oauth=False
    )
    assert refresh == "refresh-rotated"


@pytest.mark.asyncio
async def test_refresh_keeps_refresh_token_when_provider_does_not_rotate(
    oauth_db: str,
) -> None:
    await insert_mcp_server_config(
        "clickup",
        oauth_config={"token_url": "https://auth.example.com/oauth/token"},
    )
    await cs.set_credential(
        "alice", "clickup", "OAUTH_TOKEN", "old", expires_at=_expired()
    )
    await cs.set_credential("alice", "clickup", "OAUTH_REFRESH_TOKEN", "refresh-stable")

    with (
        patch(
            "src.runtime.oauth_token_exchange.exchange_refresh_token",
            new=AsyncMock(
                return_value={"access_token": "new-access", "expires_in": 3600}
            ),
        ),
        patch(
            "src.runtime.mcp_credential_invalidate.invalidate_mcp_credentials_runtime",
            new=AsyncMock(),
        ),
    ):
        token = await cs.get_credential("alice", "clickup", "OAUTH_TOKEN")

    assert token == "new-access"
    refresh = await cs.get_credential(
        "alice", "clickup", "OAUTH_REFRESH_TOKEN", auto_refresh_oauth=False
    )
    assert refresh == "refresh-stable"


@pytest.mark.asyncio
async def test_refresh_failure_deletes_credentials(oauth_db: str) -> None:
    await insert_mcp_server_config(
        "clickup",
        oauth_config={"token_url": "https://auth.example.com/oauth/token"},
    )
    await cs.set_credential(
        "alice", "clickup", "OAUTH_TOKEN", "old", expires_at=_expired()
    )
    await cs.set_credential(
        "alice", "clickup", "OAUTH_REFRESH_TOKEN", "refresh-revoked"
    )

    with patch(
        "src.runtime.oauth_token_exchange.exchange_refresh_token",
        new=AsyncMock(
            side_effect=OAuthTokenExchangeError(
                "invalid_grant", status_code=400, body="invalid_grant"
            )
        ),
    ):
        token = await cs.get_credential("alice", "clickup", "OAUTH_TOKEN")

    assert token is None
    refresh = await cs.get_credential(
        "alice", "clickup", "OAUTH_REFRESH_TOKEN", auto_refresh_oauth=False
    )
    assert refresh is None


def test_ui_refresh_failure_keeps_refresh_token(oauth_db: str) -> None:
    async def run() -> None:
        await insert_mcp_server_config(
            "ms365",
            oauth_config={
                "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            },
        )
        await cs.set_credential(
            "admin", "ms365", "OAUTH_TOKEN", "old", expires_at=_expired()
        )
        await cs.set_credential("admin", "ms365", "OAUTH_REFRESH_TOKEN", "refresh-keep")

        with patch(
            "src.runtime.oauth_token_exchange.exchange_refresh_token",
            new=AsyncMock(
                side_effect=OAuthTokenExchangeError(
                    "temporarily unavailable", status_code=503, body="unavailable"
                )
            ),
        ):
            token = await cs.refresh_oauth_access_token(
                "admin", "ms365", delete_on_failure=False
            )

        assert token is None
        refresh = await cs.get_credential(
            "admin", "ms365", "OAUTH_REFRESH_TOKEN", auto_refresh_oauth=False
        )
        assert refresh == "refresh-keep"

    asyncio.run(run())


def test_refresh_oauth_hints_if_needed_renews_access(oauth_db: str) -> None:
    from src.runtime.mcp_integration_helpers import refresh_oauth_hints_if_needed

    async def run() -> None:
        await insert_mcp_server_config(
            "ms365",
            oauth_config={
                "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            },
        )
        await cs.set_credential(
            "admin", "ms365", "OAUTH_TOKEN", "old", expires_at=_expired()
        )
        await cs.set_credential(
            "admin", "ms365", "OAUTH_REFRESH_TOKEN", "refresh-valid"
        )

        hints = await cs.list_credentials_hints("admin", "ms365")
        token_data = {
            "access_token": "new-access",
            "expires_in": 3600,
            "refresh_token": "refresh-rotated",
        }
        with (
            patch(
                "src.runtime.oauth_token_exchange.exchange_refresh_token",
                new=AsyncMock(return_value=token_data),
            ),
            patch(
                "src.runtime.mcp_credential_invalidate.invalidate_mcp_credentials_runtime",
                new=AsyncMock(),
            ),
        ):
            updated = await refresh_oauth_hints_if_needed(
                "admin", "ms365", "default", hints
            )

        access = next(h for h in updated if h["key"] == "OAUTH_TOKEN")
        assert access["is_expired"] is False
        token = await cs.get_credential(
            "admin", "ms365", "OAUTH_TOKEN", auto_refresh_oauth=False
        )
        assert token == "new-access"

    asyncio.run(run())


@pytest.mark.asyncio
async def test_expired_without_refresh_token_returns_none(oauth_db: str) -> None:
    await cs.set_credential(
        "alice", "clickup", "OAUTH_TOKEN", "old", expires_at=_expired()
    )
    token = await cs.get_credential("alice", "clickup", "OAUTH_TOKEN")
    assert token is None
