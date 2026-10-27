"""Impostazioni SMTP per tenant (tabella ``smtp_settings``).

La password SMTP e' cifrata con :mod:`src.runtime.credential_store` e non
lascia mai il backend: le API admin espongono solo ``password_present``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.data.engine import get_async_session_maker
from src.data.models import SmtpSettings
from src.runtime.credential_store import (
    CredentialDecryptionError,
    decrypt_value,
    encrypt_value,
)

logger = logging.getLogger("aion.notifications.smtp_settings")

SECURITY_MODES = ("starttls", "ssl", "none")
EMAIL_LANGUAGES = ("it", "en")

_CACHE: Dict[str, tuple] = {}
CACHE_TTL = 15.0  # secondi


@dataclass(frozen=True)
class SmtpConfig:
    """Configurazione risolta, pronta per il mailer (password in chiaro)."""

    host: str
    port: int
    security: str
    username: Optional[str]
    password: Optional[str]
    from_address: str
    from_name: Optional[str]
    reply_to: Optional[str]
    email_language: str


def invalidate_cache(tenant_id: str) -> None:
    _CACHE.pop(tenant_id, None)


def _row_is_complete(row: Optional[SmtpSettings]) -> bool:
    return bool(row and row.enabled and row.host and row.port and row.from_address)


async def _load_row(tenant_id: str) -> Optional[SmtpSettings]:
    async with get_async_session_maker()() as session:
        return await session.get(SmtpSettings, tenant_id)


async def get_smtp_config(tenant_id: str) -> Optional[SmtpConfig]:
    """Configurazione utilizzabile per l'invio, o None se assente/disattivata."""
    now = time.time()
    cached = _CACHE.get(tenant_id)
    if cached and now < cached[0]:
        return cached[1]

    row = await _load_row(tenant_id)
    cfg: Optional[SmtpConfig] = None
    if _row_is_complete(row):
        password: Optional[str] = None
        if row.password_encrypted:
            try:
                password = decrypt_value(row.password_encrypted)
            except CredentialDecryptionError:
                logger.error("SMTP password non decifrabile per tenant %s", tenant_id)
                password = None
        cfg = SmtpConfig(
            host=row.host or "",
            port=int(row.port or 0),
            security=row.security or "starttls",
            username=row.username or None,
            password=password,
            from_address=row.from_address or "",
            from_name=row.from_name or None,
            reply_to=row.reply_to or None,
            email_language=row.email_language or "it",
        )

    _CACHE[tenant_id] = (now + CACHE_TTL, cfg)
    return cfg


async def smtp_configured(tenant_id: str) -> bool:
    return (await get_smtp_config(tenant_id)) is not None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


async def get_smtp_settings_public(tenant_id: str) -> Dict[str, Any]:
    """Vista per l'admin: tutti i campi tranne la password."""
    row = await _load_row(tenant_id)
    if row is None:
        return {
            "configured": False,
            "enabled": True,
            "host": "",
            "port": 587,
            "security": "starttls",
            "username": "",
            "password_present": False,
            "from_address": "",
            "from_name": "",
            "reply_to": "",
            "email_language": "it",
            "last_test_at": None,
            "last_test_ok": None,
            "last_test_error": None,
            "updated_at": None,
        }
    return {
        "configured": _row_is_complete(row),
        "enabled": bool(row.enabled),
        "host": row.host or "",
        "port": int(row.port or 587),
        "security": row.security or "starttls",
        "username": row.username or "",
        "password_present": bool(row.password_encrypted),
        "from_address": row.from_address or "",
        "from_name": row.from_name or "",
        "reply_to": row.reply_to or "",
        "email_language": row.email_language or "it",
        "last_test_at": _iso(row.last_test_at),
        "last_test_ok": row.last_test_ok,
        "last_test_error": row.last_test_error,
        "updated_at": _iso(row.updated_at),
    }


async def upsert_smtp_settings(
    tenant_id: str,
    *,
    enabled: bool,
    host: str,
    port: int,
    security: str,
    username: Optional[str],
    password: Optional[str],
    clear_password: bool,
    from_address: str,
    from_name: Optional[str],
    reply_to: Optional[str],
    email_language: str,
    actor_user_id: Optional[str],
) -> None:
    """Crea o aggiorna la riga. ``password`` vuota = mantieni quella salvata;
    ``clear_password`` la rimuove (server senza autenticazione)."""
    async with get_async_session_maker()() as session:
        row = await session.get(SmtpSettings, tenant_id)
        if row is None:
            row = SmtpSettings(tenant_id=tenant_id)
            session.add(row)
        row.enabled = enabled
        row.host = host.strip()
        row.port = port
        row.security = security
        row.username = (username or "").strip() or None
        if clear_password:
            row.password_encrypted = None
        elif password:
            row.password_encrypted = encrypt_value(password)
        row.from_address = from_address.strip()
        row.from_name = (from_name or "").strip() or None
        row.reply_to = (reply_to or "").strip() or None
        row.email_language = email_language
        # La configurazione e' cambiata: l'esito dell'ultimo test non vale piu'.
        row.last_test_at = None
        row.last_test_ok = None
        row.last_test_error = None
        row.updated_by_user_id = actor_user_id
        await session.commit()
    invalidate_cache(tenant_id)


async def record_test_result(tenant_id: str, error_code: Optional[str]) -> None:
    async with get_async_session_maker()() as session:
        row = await session.get(SmtpSettings, tenant_id)
        if row is None:
            return
        row.last_test_at = datetime.now(timezone.utc)
        row.last_test_ok = error_code is None
        row.last_test_error = error_code
        await session.commit()
