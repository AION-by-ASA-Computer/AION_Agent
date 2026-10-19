"""Login desktop via browser (PKCE + loopback).

Contratto: aion-cowork/docs/enterprise-api-contract.md, sezione "Login desktop
via browser". La pagina di login web, a login completato, chiama ``/handoff``
con il Bearer appena ottenuto; il client desktop scambia poi il codice monouso
su ``/exchange`` presentando il ``code_verifier`` (PKCE).

Il codice vive in ``sso_auth_states`` con ``kind="desktop_handoff"``: non e'
riscattabile da ``/auth/sso/exchange`` (che accetta solo ``kind="handoff"``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from src.api.auth_login import _bearer_chat_token, build_login_response
from src.api.auth_sso import _HANDOFF_TTL_SEC, _create_handoff_code, _tenant_id
from src.data.engine import get_async_session_maker
from src.data.models import SsoAuthState, User
from src.data.user_password import get_roles
from src.runtime.credential_store import decrypt_value

logger = logging.getLogger("aion.api.auth_desktop")
router = APIRouter(prefix="/auth/desktop", tags=["auth"])

KIND = "desktop_handoff"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_MAX_STATE_LEN = 256


def _err(code: str, status: int = 400) -> HTTPException:
    return HTTPException(status, detail={"code": code})


def _parse_url(url: str):
    try:
        parts = urlsplit(url)
        _ = parts.port  # valida la porta (ValueError se non numerica)
        return parts
    except ValueError:
        return None


def _is_loopback_redirect(url: str) -> bool:
    """http, host loopback, qualsiasi porta, path esatto /callback, nessun
    userinfo/query/fragment. Confronto per componenti, mai per sottostringa."""
    parts = _parse_url(url)
    if parts is None or parts.scheme != "http":
        return False
    if (parts.hostname or "").lower() not in _LOOPBACK_HOSTS:
        return False
    if "@" in parts.netloc or parts.username or parts.password:
        return False
    if parts.path != "/callback" or parts.query or parts.fragment:
        return False
    return "?" not in url and "#" not in url


def _custom_allowlist() -> list[str]:
    raw = os.getenv("AION_DESKTOP_REDIRECT_ALLOWLIST") or ""
    return [u.strip() for u in raw.split(",") if u.strip()]


def is_redirect_allowed(redirect: str) -> bool:
    if not redirect or redirect != redirect.strip():
        return False
    custom = _custom_allowlist()
    if custom:
        # Match esatto sull'intero URL (nessun prefisso/sottostringa).
        return redirect in custom
    return _is_loopback_redirect(redirect)


def _challenge_of(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class HandoffBody(BaseModel):
    challenge: str
    state: str
    redirect: str


class ExchangeBody(BaseModel):
    code: str
    code_verifier: str


@router.post("/handoff")
async def desktop_handoff(
    body: HandoffBody, authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """Emette un codice monouso (60 s) legato a challenge/state/redirect."""
    parsed = _bearer_chat_token(authorization)  # solo token chat, no API key

    if not _CHALLENGE_RE.match(body.challenge or ""):
        raise _err("invalid_challenge")
    if not body.state or len(body.state) > _MAX_STATE_LEN:
        raise _err("invalid_challenge")
    if not is_redirect_allowed(body.redirect):
        raise _err("redirect_not_allowed")

    async with get_async_session_maker()() as session:
        u = await session.get(User, parsed["user_row_id"])
        if not u:
            raise HTTPException(401, detail="Invalid or expired token")
        user_row_id = str(u.id)

    code = await _create_handoff_code(
        {
            "user_row_id": user_row_id,
            "challenge": body.challenge,
            "state": body.state,
            "redirect": body.redirect,
        },
        _tenant_id(),
        kind=KIND,
    )
    return {"code": code, "expires_in": _HANDOFF_TTL_SEC}


@router.post("/exchange")
async def desktop_exchange(body: ExchangeBody) -> Dict[str, Any]:
    """Scambia codice + code_verifier con un NUOVO token di sessione.

    Il codice e' consumato atomicamente PRIMA di verificare il verifier: un
    verifier errato brucia il codice (l'attaccante non puo' riprovare).
    """
    try:
        code_hash = hashlib.sha256(body.code.encode("ascii")).hexdigest()
    except UnicodeEncodeError:
        raise _err("invalid_code")
    now = datetime.now(timezone.utc)

    async with get_async_session_maker()() as session:
        state = (
            (
                await session.execute(
                    select(SsoAuthState).where(SsoAuthState.state_hash == code_hash)
                )
            )
            .scalars()
            .first()
        )
        if not state or state.kind != KIND:
            raise _err("invalid_code")
        if state.consumed_at:
            raise _err("code_already_used")
        expires_at = state.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            raise _err("code_expired")
        encrypted_payload = state.payload_json

        res = await session.execute(
            update(SsoAuthState)
            .where(
                SsoAuthState.state_hash == code_hash,
                SsoAuthState.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        await session.commit()
        if res.rowcount != 1:
            raise _err("code_already_used")

    try:
        payload = json.loads(decrypt_value(encrypted_payload))
        challenge = str(payload["challenge"])
        user_row_id = str(payload["user_row_id"])
    except Exception:
        raise HTTPException(500, detail={"code": "exchange_error"})

    if not hmac.compare_digest(
        _challenge_of(body.code_verifier).encode("ascii"), challenge.encode("ascii")
    ):
        raise _err("invalid_verifier")

    async with get_async_session_maker()() as session:
        u = await session.get(User, user_row_id)
        if not u:
            raise _err("invalid_code")
        row = {
            "id": u.id,
            "identifier": u.identifier,
            "display_name": u.display_name,
            "roles": get_roles(u),
            "must_change_password": bool(getattr(u, "must_change_password", False)),
        }

    sso_link_required = False
    sso_linked = False
    try:
        from src.auth.sso.login_mode import get_login_settings, user_needs_link

        settings = await get_login_settings(_tenant_id())
        if settings.get("sso_provider"):
            sso_link_required = await user_needs_link(_tenant_id(), user_row_id)
            sso_linked = not sso_link_required
    except Exception as e:  # stessa tolleranza di /auth/refresh
        logger.warning("desktop exchange SSO check failed: %s", e)
    row["must_change_password"] = row["must_change_password"] and not sso_linked
    return build_login_response(row, sso_link_required=sso_link_required)
