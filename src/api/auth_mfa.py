"""Endpoint 2FA TOTP per il login con password (``/auth/2fa/*``).

Il token di sessione viene emesso solo qui, dopo codice valido, quando
``POST /auth/login`` risponde ``mfa_required``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.auth_login import build_login_response
from src.auth.mfa import totp
from src.data.engine import get_async_session_maker
from src.data.models import User

logger = logging.getLogger("aion.api.auth_mfa")

router = APIRouter(prefix="/auth/2fa", tags=["auth"])


class MfaTokenBody(BaseModel):
    mfa_token: str = Field(..., min_length=1)


class MfaCodeBody(MfaTokenBody):
    code: str = Field(..., min_length=1, max_length=16)


def _tenant() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


def _challenge(token: str, stage: str) -> Dict[str, Any]:
    parsed = totp.verify_mfa_token(token)
    if not parsed or parsed["stage"] != stage:
        raise HTTPException(401, detail={"code": "invalid_mfa_token"})
    return parsed


async def _check_code(user_row_id: str, code: str) -> None:
    try:
        ok = await totp.verify_code(user_row_id, code)
    except totp.MfaLocked as e:
        raise HTTPException(
            429,
            detail={"code": "mfa_locked", "retry_after": e.retry_after},
            headers={"Retry-After": str(e.retry_after)},
        ) from None
    if not ok:
        raise HTTPException(401, detail={"code": "invalid_code"})


async def _login_payload(user_row_id: str) -> Dict[str, Any]:
    from src.chat_auth import _user_to_auth_dict

    async with get_async_session_maker()() as session:
        user = await session.get(User, user_row_id)
    if not user:
        raise HTTPException(401, detail={"code": "invalid_mfa_token"})
    return build_login_response(_user_to_auth_dict(user))


async def _require_active() -> None:
    if not await totp.two_factor_effective(_tenant()):
        raise HTTPException(409, detail={"code": "two_factor_not_active"})


@router.post("/enroll/start")
async def enroll_start(body: MfaTokenBody) -> Dict[str, str]:
    await _require_active()
    parsed = _challenge(body.mfa_token, totp.STAGE_ENROLL)
    try:
        return await totp.start_enrollment(parsed["user_row_id"])
    except LookupError:
        raise HTTPException(401, detail={"code": "invalid_mfa_token"}) from None


@router.post("/enroll/confirm")
async def enroll_confirm(body: MfaCodeBody) -> Dict[str, Any]:
    await _require_active()
    parsed = _challenge(body.mfa_token, totp.STAGE_ENROLL)
    uid = parsed["user_row_id"]
    await _check_code(uid, body.code)
    await totp.confirm_enrollment(uid)
    return await _login_payload(uid)


@router.post("/verify")
async def verify(body: MfaCodeBody) -> Dict[str, Any]:
    await _require_active()
    parsed = _challenge(body.mfa_token, totp.STAGE_VERIFY)
    uid = parsed["user_row_id"]
    await _check_code(uid, body.code)
    return await _login_payload(uid)
