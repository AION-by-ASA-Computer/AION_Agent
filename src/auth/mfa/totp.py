"""Servizio 2FA TOTP (RFC 6238) per il login con password.

- Secret cifrato a riposo con ``credential_store.encrypt_value``.
- Challenge tra password e codice: token HMAC stateless (chiave derivata,
  mai valido come chat token).
- Anti-replay (``totp_last_used_step``) e lockout dopo N errori.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pyotp
import segno
from sqlalchemy import update

from src.auth.sso.login_mode import get_login_settings
from src.chat_auth import chat_auth_secret
from src.data.engine import get_async_session_maker
from src.data.models import User
from src.runtime.credential_store import decrypt_value, encrypt_value

logger = logging.getLogger("aion.auth.mfa")

TOTP_INTERVAL = 30
TOTP_DIGITS = 6
MAX_FAILED_ATTEMPTS = 5
LOCK_SECONDS = 300
CHALLENGE_TTL_SEC = int(os.getenv("AION_2FA_CHALLENGE_TTL_SEC", "300"))

STAGE_ENROLL = "enroll"
STAGE_VERIFY = "verify"


def force_disabled() -> bool:
    return (os.getenv("AION_2FA_FORCE_DISABLE") or "").strip() == "1"


def issuer() -> str:
    return (os.getenv("AION_2FA_ISSUER") or "AION").strip() or "AION"


async def two_factor_effective(tenant_id: str) -> bool:
    """True se il 2FA va applicato al login con password."""
    if force_disabled():
        return False
    settings = await get_login_settings(tenant_id)
    return bool(settings.get("totp_required")) and settings.get("login_mode") == "password"


async def login_stage(tenant_id: str, user: Optional[User]) -> Optional[str]:
    """Passo 2FA richiesto dal login con password, ``None`` se nessuno.

    Con la politica attiva (solo login_mode=password) verifica o enrollment.
    In modalita' SSO chi aveva gia' configurato il TOTP e non ha ancora
    collegato l'account lo conserva: il codice resta obbligatorio.
    """
    if force_disabled() or user is None:
        return None
    if await two_factor_effective(tenant_id):
        return STAGE_VERIFY if is_enrolled(user) else STAGE_ENROLL
    settings = await get_login_settings(tenant_id)
    if settings.get("login_mode") != "password" and is_enrolled(user):
        return STAGE_VERIFY
    return None


# ---------------------------------------------------------------------------
# Secret / QR
# ---------------------------------------------------------------------------

def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, identifier: str) -> str:
    return pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL).provisioning_uri(
        name=identifier, issuer_name=issuer()
    )


def qr_svg_data_uri(uri: str) -> str:
    buf = io.BytesIO()
    segno.make(uri, error="m").save(buf, kind="svg", scale=6, border=2, dark="#000000", light="#ffffff")
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def user_secret(user: User) -> Optional[str]:
    if not user.totp_secret_encrypted:
        return None
    try:
        return decrypt_value(user.totp_secret_encrypted)
    except Exception:  # noqa: BLE001
        logger.error("Cannot decrypt TOTP secret for user %s", user.id)
        return None


def is_enrolled(user: User) -> bool:
    return user.totp_enabled_at is not None and bool(user.totp_secret_encrypted)


# ---------------------------------------------------------------------------
# Challenge token (password OK -> codice richiesto)
# ---------------------------------------------------------------------------

def _mfa_key() -> bytes:
    base = chat_auth_secret() or "aion-chat-auth-dev-insecure"
    return (base + "|mfa").encode("utf-8")


def issue_mfa_token(*, user_row_id: str, stage: str, client: str = "chat") -> str:
    exp = int(time.time()) + max(60, CHALLENGE_TTL_SEC)
    payload = f"mfa|{user_row_id}|{stage}|{client}|{exp}"
    sig = hmac.new(_mfa_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode("utf-8")).decode("ascii")


def verify_mfa_token(token: str) -> Optional[Dict[str, Any]]:
    if not token or not token.strip():
        return None
    try:
        raw = base64.urlsafe_b64decode(token.strip().encode("ascii")).decode("utf-8")
        body, sig = raw.rsplit("|", 1)
        expect = hmac.new(_mfa_key(), body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return None
        tag, user_row_id, stage, client, exp_s = body.split("|")
        if tag != "mfa" or int(exp_s) < int(time.time()):
            return None
        if stage not in (STAGE_ENROLL, STAGE_VERIFY):
            return None
        return {"user_row_id": user_row_id, "stage": stage, "client": client}
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Verifica codice
# ---------------------------------------------------------------------------

class MfaLocked(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("mfa_locked")
        self.retry_after = retry_after


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def verify_code(user_row_id: str, code: str) -> bool:
    """Verifica il codice, aggiornando lockout/anti-replay.

    Solleva ``MfaLocked`` se l'utente e' bloccato. Ritorna True/False.
    """
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    now = datetime.now(timezone.utc)
    async with get_async_session_maker()() as session:
        user = await session.get(User, user_row_id)
        if not user:
            return False
        if user.totp_locked_until and _aware(user.totp_locked_until) > now:
            raise MfaLocked(int((_aware(user.totp_locked_until) - now).total_seconds()) + 1)

        secret = user_secret(user)
        ok = False
        if secret and len(code) == TOTP_DIGITS:
            totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL)
            step_now = int(time.time()) // TOTP_INTERVAL
            last = user.totp_last_used_step
            for step in (step_now - 1, step_now, step_now + 1):
                if last is not None and step <= last:
                    continue
                expected = totp.at(step * TOTP_INTERVAL)
                if hmac.compare_digest(expected, code):
                    user.totp_last_used_step = step
                    ok = True
                    break

        if ok:
            user.totp_failed_count = 0
            user.totp_locked_until = None
        else:
            user.totp_failed_count = int(user.totp_failed_count or 0) + 1
            if user.totp_failed_count >= MAX_FAILED_ATTEMPTS:
                user.totp_locked_until = now + timedelta(seconds=LOCK_SECONDS)
                user.totp_failed_count = 0
        session.add(user)
        await session.commit()
        return ok


async def start_enrollment(user_row_id: str) -> Dict[str, str]:
    """Ritorna uri, qr e secret del secret *pending* dell'utente.

    Idempotente anche con chiamate concorrenti (es. React StrictMode in dev):
    il secret si scrive solo se assente (UPDATE condizionale) e poi si rilegge
    quello effettivamente salvato, cosi' QR mostrato e DB coincidono sempre.
    """
    async with get_async_session_maker()() as session:
        user = await session.get(User, user_row_id)
        if not user or is_enrolled(user):
            raise LookupError("user_not_found_or_enrolled")
        secret = user_secret(user)
        if not secret:
            await session.execute(
                update(User)
                .where(User.id == user_row_id, User.totp_secret_encrypted.is_(None))
                .values(
                    totp_secret_encrypted=encrypt_value(new_secret()),
                    totp_enabled_at=None,
                    totp_last_used_step=None,
                )
            )
            await session.commit()
            await session.refresh(user)
            secret = user_secret(user)
        if not secret:
            raise LookupError("secret_unavailable")
        uri = provisioning_uri(secret, user.identifier)
    return {"otpauth_uri": uri, "qr_svg": qr_svg_data_uri(uri), "secret": secret}


async def confirm_enrollment(user_row_id: str) -> None:
    async with get_async_session_maker()() as session:
        user = await session.get(User, user_row_id)
        if user:
            user.totp_enabled_at = datetime.now(timezone.utc)
            session.add(user)
            await session.commit()


async def reset_user_totp(user_row_id: str) -> bool:
    async with get_async_session_maker()() as session:
        user = await session.get(User, user_row_id)
        if not user:
            return False
        user.totp_secret_encrypted = None
        user.totp_enabled_at = None
        user.totp_last_used_step = None
        user.totp_failed_count = 0
        user.totp_locked_until = None
        session.add(user)
        await session.commit()
        return True


async def user_requires_enrollment(tenant_id: str, user_row_id: str) -> bool:
    """True se il 2FA e' effettivo e l'utente (con password) non l'ha configurato."""
    if not await two_factor_effective(tenant_id):
        return False
    async with get_async_session_maker()() as session:
        user = await session.get(User, user_row_id)
    return bool(user and user.password_hash and not is_enrolled(user))
