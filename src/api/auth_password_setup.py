"""Endpoint pubblici per impostare la password tramite link email.

Prefisso: /auth/password

- ``POST /setup/inspect``: verifica il token (senza consumarlo);
- ``POST /setup``: imposta la password scelta dall'utente;
- ``POST /forgot``: "Password dimenticata?" (risposta sempre neutra).

Il token arriva nel body (la pagina chat-ui lo legge dal fragment dell'URL),
mai in query string.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.public_urls import chat_base_url
from src.auth.password_setup import (
    SetupLinkError,
    consume_token,
    find_user_for_reset,
    inspect_token,
    issue_setup_links,
)
from src.runtime.redis_client import rate_limiter_check

logger = logging.getLogger("aion.api.auth_password_setup")
router = APIRouter(prefix="/auth/password", tags=["auth"])

_FORGOT_LIMIT_PER_IP = int(os.getenv("AION_PASSWORD_FORGOT_LIMIT_PER_IP", "10"))
_FORGOT_LIMIT_PER_ACCOUNT = int(
    os.getenv("AION_PASSWORD_FORGOT_LIMIT_PER_ACCOUNT", "3")
)
_FORGOT_WINDOW_SEC = 3600
_SETUP_LIMIT_PER_IP = 30
_SETUP_WINDOW_SEC = 600


def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if fwd:
        return fwd
    return request.client.host if request.client else "unknown"


def _raise(e: SetupLinkError) -> None:
    status = 422 if e.code == "password_policy" else 400
    detail: Dict[str, Any] = {"code": e.code}
    if e.violations:
        detail["violations"] = e.violations
    raise HTTPException(status, detail=detail)


async def _limit_setup(request: Request) -> None:
    allowed, *_ = await rate_limiter_check(
        f"pwsetup:ip:{_client_ip(request)}", _SETUP_LIMIT_PER_IP, _SETUP_WINDOW_SEC
    )
    if not allowed:
        raise HTTPException(429, detail={"code": "rate_limited"})


class TokenBody(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)


class SetupBody(TokenBody):
    new_password: str = Field(..., min_length=1, max_length=512)


class ForgotBody(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=256)


@router.post("/setup/inspect")
async def setup_inspect(body: TokenBody, request: Request) -> Dict[str, Any]:
    await _limit_setup(request)
    try:
        return await inspect_token(body.token)
    except SetupLinkError as e:
        _raise(e)


@router.post("/setup")
async def setup_password(body: SetupBody, request: Request) -> Dict[str, Any]:
    await _limit_setup(request)
    try:
        return await consume_token(body.token, body.new_password)
    except SetupLinkError as e:
        _raise(e)


async def password_reset_available(tenant_id: str) -> bool:
    """Il link "Password dimenticata?" ha senso solo con SMTP configurato e
    form password visibile."""
    from src.auth.sso.login_mode import password_login_visible
    from src.chat_auth import password_auth_enabled
    from src.notifications.smtp_settings import smtp_configured

    if not password_auth_enabled():
        return False
    if not await smtp_configured(tenant_id):
        return False
    return await password_login_visible(tenant_id)


async def _send_reset(tenant_id: str, identifier: str, base_url: str) -> None:
    from src.auth.sso.login_mode import get_login_settings

    try:
        user = await find_user_for_reset(tenant_id, identifier)
        if user is None or not (user.email or "").strip():
            return
        allowed, *_ = await rate_limiter_check(
            f"pwforgot:user:{user.id}", _FORGOT_LIMIT_PER_ACCOUNT, _FORGOT_WINDOW_SEC
        )
        if not allowed:
            return
        if user.password_hash:
            purpose = "reset"
        elif (await get_login_settings(tenant_id))["login_mode"] == "password":
            purpose = "invite"
        else:
            purpose = "migration"
        await issue_setup_links(
            tenant_id, [user.id], purpose, actor_user_id=None, base_url=base_url
        )
    except SetupLinkError:
        return
    except Exception as e:  # pragma: no cover - solo log
        logger.warning("forgot-password: invio fallito: %s", e)


@router.post("/forgot", status_code=202)
async def forgot_password(
    body: ForgotBody, request: Request, background: BackgroundTasks
) -> Dict[str, Any]:
    """Risposta identica che l'account esista o no (niente enumerazione):
    la ricerca e l'invio avvengono in background."""
    allowed, *_ = await rate_limiter_check(
        f"pwforgot:ip:{_client_ip(request)}", _FORGOT_LIMIT_PER_IP, _FORGOT_WINDOW_SEC
    )
    if not allowed:
        raise HTTPException(429, detail={"code": "rate_limited"})
    tenant = _tenant_id()
    if await password_reset_available(tenant):
        background.add_task(
            _send_reset, tenant, body.identifier.strip(), chat_base_url(request)
        )
    return {"status": "accepted"}
