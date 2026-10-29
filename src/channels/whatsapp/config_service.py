"""Configurazione del canale WhatsApp per tenant (una riga ``whatsapp_channels``).

Stesso schema di ``src/auth/sso/config_service.py``:

- i segreti (access token, app secret, verify token) sono cifrati con
  ``credential_store``; un segreto vuoto in ``upsert_channel`` mantiene quello
  salvato;
- se cambiano le credenziali, ``validated_at`` si azzera e il canale si spegne:
  va rivalidato dal pannello admin prima di riattivarlo;
- cache in memoria di 30s, svuotata a ogni scrittura;
- kill switch ``AION_WHATSAPP_FORCE_DISABLE=1``: il canale resta configurato
  ma i webhook vengono ignorati e nessun messaggio viene inviato.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select

from src.data.engine import get_async_session_maker
from src.data.ids import new_uuid7_str
from src.data.models import WhatsAppChannel
from src.runtime.credential_store import (
    CredentialDecryptionError,
    decrypt_value,
    encrypt_value,
)

logger = logging.getLogger("aion.whatsapp.config")

DEFAULT_GRAPH_VERSION = "v26.0"
WEBHOOK_PATH = "/v1/channels/whatsapp/webhook"
CACHE_TTL = 30.0


def default_tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


def force_disabled() -> bool:
    return (os.getenv("AION_WHATSAPP_FORCE_DISABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def graph_version() -> str:
    return (os.getenv("AION_WHATSAPP_GRAPH_VERSION") or DEFAULT_GRAPH_VERSION).strip()


def webhook_url() -> str:
    """URL pubblico da registrare su Meta (``AION_PUBLIC_API_URL`` + path)."""
    from src.api.public_urls import _public_api_base_url

    base = _public_api_base_url()
    return f"{base}{WEBHOOK_PATH}" if base else ""


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    v = _as_utc(dt)
    return v.isoformat() if v else None


def _decrypt(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return decrypt_value(value)
    except CredentialDecryptionError:
        logger.error("Cannot decrypt WhatsApp channel secret (key mismatch?)")
        return None


def _hint(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return f"••••{value[-4:]}" if len(value) >= 4 else "••••"


@dataclass(frozen=True)
class ChannelConfig:
    tenant_id: str
    enabled: bool
    waba_id: Optional[str]
    phone_number_id: Optional[str]
    display_phone_number: Optional[str]
    verified_name: Optional[str]
    access_token: Optional[str]
    app_secret: Optional[str]
    verify_token: Optional[str]
    default_profile_slug: Optional[str]
    validated_at: Optional[datetime]
    webhook_verified_at: Optional[datetime]
    last_webhook_at: Optional[datetime]
    last_error: Optional[str]

    @property
    def configured(self) -> bool:
        return bool(
            self.waba_id
            and self.phone_number_id
            and self.access_token
            and self.app_secret
        )

    @property
    def active(self) -> bool:
        """Il canale risponde ai messaggi: attivo, validato e senza kill switch."""
        return (
            self.enabled
            and self.validated_at is not None
            and self.configured
            and not force_disabled()
        )


def _row_to_config(row: WhatsAppChannel) -> ChannelConfig:
    return ChannelConfig(
        tenant_id=row.tenant_id,
        enabled=bool(row.enabled),
        waba_id=row.waba_id,
        phone_number_id=row.phone_number_id,
        display_phone_number=row.display_phone_number,
        verified_name=row.verified_name,
        access_token=_decrypt(row.access_token_encrypted),
        app_secret=_decrypt(row.app_secret_encrypted),
        verify_token=_decrypt(row.verify_token_encrypted),
        default_profile_slug=row.default_profile_slug,
        validated_at=_as_utc(row.validated_at),
        webhook_verified_at=_as_utc(row.webhook_verified_at),
        last_webhook_at=_as_utc(row.last_webhook_at),
        last_error=row.last_error,
    )


_CACHE: Dict[str, Tuple[float, Optional[ChannelConfig]]] = {}


def invalidate_cache() -> None:
    _CACHE.clear()


async def _load_row(session, tenant_id: str) -> Optional[WhatsAppChannel]:
    return (
        (
            await session.execute(
                select(WhatsAppChannel).where(WhatsAppChannel.tenant_id == tenant_id)
            )
        )
        .scalars()
        .first()
    )


async def get_channel(tenant_id: Optional[str] = None) -> Optional[ChannelConfig]:
    """Configurazione del tenant (segreti in chiaro), con cache di 30s."""
    tenant_id = tenant_id or default_tenant_id()
    now = time.time()
    cached = _CACHE.get(tenant_id)
    if cached and now < cached[0]:
        return cached[1]
    async with get_async_session_maker()() as session:
        row = await _load_row(session, tenant_id)
    cfg = _row_to_config(row) if row else None
    _CACHE[tenant_id] = (now + CACHE_TTL, cfg)
    return cfg


async def get_channel_by_phone_number_id(
    phone_number_id: str,
) -> Optional[ChannelConfig]:
    """Canale a cui appartiene un webhook (``metadata.phone_number_id``)."""
    if not phone_number_id:
        return None
    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(WhatsAppChannel).where(
                        WhatsAppChannel.phone_number_id == phone_number_id
                    )
                )
            )
            .scalars()
            .first()
        )
    return _row_to_config(row) if row else None


async def find_tenant_by_verify_token(token: str) -> Optional[str]:
    """Tenant il cui verify token coincide (handshake GET del webhook)."""
    if not token:
        return None
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(WhatsAppChannel).where(
                        WhatsAppChannel.verify_token_encrypted.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
    for row in rows:
        stored = _decrypt(row.verify_token_encrypted)
        if stored and secrets.compare_digest(stored, token):
            return row.tenant_id
    return None


async def upsert_channel(
    tenant_id: str,
    *,
    waba_id: str,
    phone_number_id: str,
    access_token: Optional[str] = None,
    app_secret: Optional[str] = None,
    default_profile_slug: Optional[str] = None,
) -> None:
    """Crea o aggiorna la configurazione. Segreti vuoti = mantieni gli attuali."""
    invalidate_cache()
    waba_id = (waba_id or "").strip()
    phone_number_id = (phone_number_id or "").strip()
    access_token = (access_token or "").strip() or None
    app_secret = (app_secret or "").strip() or None
    profile = (default_profile_slug or "").strip() or None

    async with get_async_session_maker()() as session:
        row = await _load_row(session, tenant_id)
        if row is None:
            row = WhatsAppChannel(
                id=new_uuid7_str(),
                tenant_id=tenant_id,
                enabled=False,
                verify_token_encrypted=encrypt_value(secrets.token_urlsafe(24)),
            )
            session.add(row)
            needs_revalidation = True
        else:
            needs_revalidation = (
                row.waba_id != waba_id
                or row.phone_number_id != phone_number_id
                or access_token is not None
                or app_secret is not None
            )

        if row.phone_number_id != phone_number_id:
            row.display_phone_number = None
            row.verified_name = None
        row.waba_id = waba_id
        row.phone_number_id = phone_number_id
        if access_token is not None:
            row.access_token_encrypted = encrypt_value(access_token)
        if app_secret is not None:
            row.app_secret_encrypted = encrypt_value(app_secret)
        row.default_profile_slug = profile
        row.updated_at = datetime.now(timezone.utc)
        if needs_revalidation:
            row.validated_at = None
            row.validated_by_user_id = None
            row.enabled = False
        await session.commit()


async def regenerate_verify_token(tenant_id: str) -> str:
    """Nuovo verify token: va reinserito su Meta (webhook da riverificare)."""
    invalidate_cache()
    token = secrets.token_urlsafe(24)
    async with get_async_session_maker()() as session:
        row = await _load_row(session, tenant_id)
        if row is None:
            row = WhatsAppChannel(
                id=new_uuid7_str(), tenant_id=tenant_id, enabled=False
            )
            session.add(row)
        row.verify_token_encrypted = encrypt_value(token)
        row.webhook_verified_at = None
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
    return token


async def _update(tenant_id: str, **fields: Any) -> bool:
    invalidate_cache()
    async with get_async_session_maker()() as session:
        row = await _load_row(session, tenant_id)
        if row is None:
            return False
        for key, value in fields.items():
            setattr(row, key, value)
        await session.commit()
    return True


async def mark_validated(
    tenant_id: str,
    user_id: Optional[str],
    *,
    display_phone_number: Optional[str],
    verified_name: Optional[str],
) -> None:
    await _update(
        tenant_id,
        validated_at=datetime.now(timezone.utc),
        validated_by_user_id=user_id,
        display_phone_number=display_phone_number,
        verified_name=verified_name,
        last_error=None,
    )


async def update_phone_info(
    tenant_id: str,
    *,
    display_phone_number: Optional[str],
    verified_name: Optional[str],
) -> None:
    await _update(
        tenant_id,
        display_phone_number=display_phone_number,
        verified_name=verified_name,
    )


async def mark_webhook_verified(tenant_id: str) -> None:
    await _update(tenant_id, webhook_verified_at=datetime.now(timezone.utc))


async def touch_webhook(tenant_id: str) -> None:
    await _update(tenant_id, last_webhook_at=datetime.now(timezone.utc))


async def set_last_error(tenant_id: str, error: Optional[str]) -> None:
    await _update(tenant_id, last_error=(error or None) and error[:2000])


class ChannelStateError(ValueError):
    """Attivazione rifiutata; ``code`` è il codice restituito al client."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def set_enabled(tenant_id: str, enabled: bool) -> None:
    invalidate_cache()
    async with get_async_session_maker()() as session:
        row = await _load_row(session, tenant_id)
        if row is None:
            raise ChannelStateError("not_configured")
        if enabled:
            if force_disabled():
                raise ChannelStateError("force_disabled")
            if row.validated_at is None:
                raise ChannelStateError("not_validated")
        row.enabled = enabled
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def admin_view(tenant_id: str) -> Dict[str, Any]:
    """Configurazione per l'admin-ui: segreti mascherati, verify token in chiaro.

    Il verify token serve solo all'handshake del webhook e va copiato su Meta,
    quindi l'admin lo vede sempre.
    """
    cfg = await get_channel(tenant_id)
    base: Dict[str, Any] = {
        "configured": False,
        "enabled": False,
        "force_disabled": force_disabled(),
        "waba_id": None,
        "phone_number_id": None,
        "display_phone_number": None,
        "verified_name": None,
        "access_token_hint": None,
        "app_secret_hint": None,
        "verify_token": None,
        "default_profile_slug": None,
        "webhook_url": webhook_url(),
        "graph_api_version": graph_version(),
        "validated_at": None,
        "webhook_verified_at": None,
        "last_webhook_at": None,
        "last_error": None,
    }
    if cfg is None:
        return base
    base.update(
        {
            "configured": cfg.configured,
            "enabled": cfg.enabled,
            "waba_id": cfg.waba_id,
            "phone_number_id": cfg.phone_number_id,
            "display_phone_number": cfg.display_phone_number,
            "verified_name": cfg.verified_name,
            "access_token_hint": _hint(cfg.access_token),
            "app_secret_hint": _hint(cfg.app_secret),
            "verify_token": cfg.verify_token,
            "default_profile_slug": cfg.default_profile_slug,
            "validated_at": _iso(cfg.validated_at),
            "webhook_verified_at": _iso(cfg.webhook_verified_at),
            "last_webhook_at": _iso(cfg.last_webhook_at),
            "last_error": cfg.last_error,
        }
    )
    return base
