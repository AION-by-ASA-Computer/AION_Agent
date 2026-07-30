"""Shared OAuth token exchange (authorization_code + refresh_token grants)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("aion.oauth_token_exchange")


class OAuthTokenExchangeError(Exception):
    """Raised when the OAuth provider rejects or omits a token response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def token_expires_at(token_data: Dict[str, Any]) -> Optional[datetime]:
    expires_in = token_data.get("expires_in")
    if expires_in is None:
        return None
    try:
        return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    except (TypeError, ValueError):
        return None


async def exchange_token(
    token_url: str,
    payload: Dict[str, str],
    *,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    data = dict(payload)
    if client_id and "client_id" not in data:
        data["client_id"] = client_id
    if client_secret and "client_secret" not in data:
        data["client_secret"] = client_secret

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(token_url, data=data, headers=headers)
            resp.raise_for_status()
            token_data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "OAuth token exchange failed with status %d: %s",
            exc.response.status_code,
            exc.response.text,
        )
        raise OAuthTokenExchangeError(
            f"OAuth provider error: {exc.response.text}",
            status_code=exc.response.status_code,
            body=exc.response.text,
        ) from exc
    except Exception as exc:
        logger.exception("OAuth token exchange error")
        raise OAuthTokenExchangeError(
            f"Failed to connect to OAuth provider: {exc}"
        ) from exc

    if not token_data.get("access_token"):
        raise OAuthTokenExchangeError(
            f"No access_token returned by OAuth provider: {token_data}"
        )
    return token_data


async def exchange_authorization_code(
    token_url: str,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier
    return await exchange_token(
        token_url,
        payload,
        client_id=client_id,
        client_secret=client_secret,
    )


async def exchange_refresh_token(
    token_url: str,
    *,
    refresh_token: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    return await exchange_token(
        token_url,
        payload,
        client_id=client_id,
        client_secret=client_secret,
    )
