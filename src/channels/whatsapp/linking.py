"""Collegamento tra un WhatsApp (BSUID) e un utente AION.

Il dipendente genera un codice dalla chat-ui (Impostazioni → WhatsApp) e lo
invia al numero aziendale come ``COLLEGA <codice>``. WhatsApp non crea mai
account: senza collegamento l'agente non risponde.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from sqlalchemy import delete, or_, select, update

from src.data.engine import get_async_session_maker
from src.data.ids import new_uuid7_str
from src.data.models import User, WhatsAppIdentity, WhatsAppLinkCode
from src.runtime.redis_client import cache_get, cache_set

logger = logging.getLogger("aion.whatsapp.linking")

LINK_COMMAND = "COLLEGA"
CODE_LENGTH = 8
CODE_TTL = timedelta(minutes=10)
# Niente caratteri ambigui (0/O, 1/I/L) per chi lo ricopia a mano.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MAX_FAILED_ATTEMPTS = 5
FAILED_WINDOW_S = 15 * 60

_LINK_RE = re.compile(rf"^\s*{LINK_COMMAND}\s+([A-Za-z0-9 -]{{4,32}})\s*$", re.I)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def normalize_code(code: str) -> str:
    return re.sub(r"[\s-]", "", code or "").upper()


def _hash_code(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


def parse_link_command(text: Optional[str]) -> Optional[str]:
    """``"collega 7kq4 m2xp"`` → ``"7KQ4M2XP"``; None se non è un comando."""
    m = _LINK_RE.match(text or "")
    return normalize_code(m.group(1)) if m else None


def phone_hint(phone: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", phone or "")
    return f"••• {digits[-3:]}" if len(digits) >= 3 else None


def wa_link(display_phone_number: Optional[str], code: str) -> Optional[str]:
    digits = re.sub(r"\D", "", display_phone_number or "")
    if not digits:
        return None
    return f"https://wa.me/{digits}?text={quote(f'{LINK_COMMAND} {code}')}"


@dataclass
class LinkCode:
    code: str
    expires_at: datetime
    wa_link: Optional[str]
    qr_svg: Optional[str]


async def create_link_code(
    tenant_id: str, user_id: str, display_phone_number: Optional[str]
) -> LinkCode:
    """Nuovo codice monouso (invalida i precedenti dello stesso utente)."""
    from src.auth.mfa.totp import qr_svg_data_uri

    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    expires = _now() + CODE_TTL
    async with get_async_session_maker()() as session:
        await session.execute(
            delete(WhatsAppLinkCode).where(
                WhatsAppLinkCode.tenant_id == tenant_id,
                WhatsAppLinkCode.user_id == user_id,
            )
        )
        session.add(
            WhatsAppLinkCode(
                id=new_uuid7_str(),
                tenant_id=tenant_id,
                user_id=user_id,
                code_hash=_hash_code(code),
                expires_at=expires,
            )
        )
        await session.commit()
    link = wa_link(display_phone_number, code)
    return LinkCode(
        code=code,
        expires_at=expires,
        wa_link=link,
        qr_svg=qr_svg_data_uri(link) if link else None,
    )


@dataclass
class LinkResult:
    ok: bool
    # linked | invalid | expired | rate_limited | already_linked_other
    reason: str
    user: Optional[User] = None


def _fail_key(tenant_id: str, sender_key: str) -> str:
    return f"wa_link_fail:{tenant_id}:{sender_key}"


async def _register_failure(tenant_id: str, sender_key: str) -> None:
    key = _fail_key(tenant_id, sender_key)
    n = int((await cache_get(key)) or "0") + 1
    await cache_set(key, str(n), ttl_sec=FAILED_WINDOW_S)


async def consume_code(
    tenant_id: str,
    *,
    code: str,
    bsuid: str,
    phone: Optional[str],
    profile_name: Optional[str],
) -> LinkResult:
    """Collega ``bsuid`` all'utente del codice. Max 5 tentativi errati / 15 min."""
    fails = int((await cache_get(_fail_key(tenant_id, bsuid))) or "0")
    if fails >= MAX_FAILED_ATTEMPTS:
        return LinkResult(False, "rate_limited")

    now = _now()
    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(WhatsAppLinkCode).where(
                        WhatsAppLinkCode.tenant_id == tenant_id,
                        WhatsAppLinkCode.code_hash == _hash_code(code),
                        WhatsAppLinkCode.used_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            await _register_failure(tenant_id, bsuid)
            return LinkResult(False, "invalid")
        if (_as_utc(row.expires_at) or now) <= now:
            await _register_failure(tenant_id, bsuid)
            return LinkResult(False, "expired")
        user = await session.get(User, row.user_id)
        if user is None:
            return LinkResult(False, "invalid")

        # Un WhatsApp per utente e un utente per WhatsApp: rimuove i
        # collegamenti precedenti di entrambi (ricollegamento = sostituzione).
        await session.execute(
            delete(WhatsAppIdentity).where(
                WhatsAppIdentity.tenant_id == tenant_id,
                or_(
                    WhatsAppIdentity.bsuid == bsuid,
                    WhatsAppIdentity.user_id == user.id,
                ),
            )
        )
        session.add(
            WhatsAppIdentity(
                id=new_uuid7_str(),
                tenant_id=tenant_id,
                bsuid=bsuid,
                phone_e164=phone,
                wa_profile_name=profile_name,
                user_id=user.id,
                linked_at=now,
            )
        )
        row.used_at = now
        await session.commit()
        await session.refresh(user)
    logger.info("WhatsApp linked to user %s", user.id)
    return LinkResult(True, "linked", user)


async def get_identity(
    tenant_id: str, bsuid: Optional[str], phone: Optional[str] = None
) -> Optional[WhatsAppIdentity]:
    """Identità per BSUID; in mancanza, per numero (e aggiorna il BSUID)."""
    async with get_async_session_maker()() as session:
        ident = None
        if bsuid:
            ident = (
                (
                    await session.execute(
                        select(WhatsAppIdentity).where(
                            WhatsAppIdentity.tenant_id == tenant_id,
                            WhatsAppIdentity.bsuid == bsuid,
                        )
                    )
                )
                .scalars()
                .first()
            )
        if ident is None and phone:
            ident = (
                (
                    await session.execute(
                        select(WhatsAppIdentity).where(
                            WhatsAppIdentity.tenant_id == tenant_id,
                            WhatsAppIdentity.phone_e164 == phone,
                        )
                    )
                )
                .scalars()
                .first()
            )
            # Collegato quando il payload aveva solo il numero: ora c'è il BSUID.
            if ident is not None and bsuid and ident.bsuid != bsuid:
                ident.bsuid = bsuid
                await session.commit()
                await session.refresh(ident)
        return ident


async def get_identity_for_user(
    tenant_id: str, user_id: str
) -> Optional[WhatsAppIdentity]:
    async with get_async_session_maker()() as session:
        return (
            (
                await session.execute(
                    select(WhatsAppIdentity).where(
                        WhatsAppIdentity.tenant_id == tenant_id,
                        WhatsAppIdentity.user_id == user_id,
                    )
                )
            )
            .scalars()
            .first()
        )


async def update_identity(identity_id: str, **fields: Any) -> None:
    async with get_async_session_maker()() as session:
        await session.execute(
            update(WhatsAppIdentity)
            .where(WhatsAppIdentity.id == identity_id)
            .values(**fields)
        )
        await session.commit()


async def unlink(
    tenant_id: str,
    *,
    user_id: Optional[str] = None,
    identity_id: Optional[str] = None,
) -> bool:
    if not user_id and not identity_id:
        return False
    stmt = delete(WhatsAppIdentity).where(WhatsAppIdentity.tenant_id == tenant_id)
    if user_id:
        stmt = stmt.where(WhatsAppIdentity.user_id == user_id)
    if identity_id:
        stmt = stmt.where(WhatsAppIdentity.id == identity_id)
    async with get_async_session_maker()() as session:
        res = await session.execute(stmt)
        await session.commit()
    return bool(res.rowcount)


async def apply_number_change(
    tenant_id: str,
    *,
    previous_bsuid: Optional[str],
    new_bsuid: Optional[str],
    new_phone: Optional[str],
    previous_phone: Optional[str] = None,
) -> bool:
    """Messaggi di sistema ``user_changed_number`` / ``user_changed_user_id``."""
    if not previous_bsuid and not previous_phone:
        return False
    match = (
        WhatsAppIdentity.bsuid == previous_bsuid
        if previous_bsuid
        else WhatsAppIdentity.phone_e164 == previous_phone
    )
    async with get_async_session_maker()() as session:
        ident = (
            (
                await session.execute(
                    select(WhatsAppIdentity).where(
                        WhatsAppIdentity.tenant_id == tenant_id, match
                    )
                )
            )
            .scalars()
            .first()
        )
        if ident is None:
            return False
        if new_bsuid and new_bsuid != ident.bsuid:
            await session.execute(
                delete(WhatsAppIdentity).where(
                    WhatsAppIdentity.tenant_id == tenant_id,
                    WhatsAppIdentity.bsuid == new_bsuid,
                )
            )
            ident.bsuid = new_bsuid
        if new_phone:
            ident.phone_e164 = new_phone
        await session.commit()
    return True


async def list_identities(tenant_id: str) -> List[Dict[str, Any]]:
    async with get_async_session_maker()() as session:
        rows = (
            await session.execute(
                select(WhatsAppIdentity, User)
                .join(User, User.id == WhatsAppIdentity.user_id)
                .where(WhatsAppIdentity.tenant_id == tenant_id)
                .order_by(WhatsAppIdentity.linked_at.desc())
            )
        ).all()

    def iso(dt: Optional[datetime]) -> Optional[str]:
        v = _as_utc(dt)
        return v.isoformat() if v else None

    return [
        {
            "id": ident.id,
            "user_id": user.id,
            "user_identifier": user.identifier,
            "user_display_name": user.display_name,
            "wa_profile_name": ident.wa_profile_name,
            "phone_hint": phone_hint(ident.phone_e164),
            "linked_at": iso(ident.linked_at),
            "last_inbound_at": iso(ident.last_inbound_at),
        }
        for ident, user in rows
    ]
