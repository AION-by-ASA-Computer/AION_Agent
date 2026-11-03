"""Collegamento account Telegram ↔ utente AION (pairing con codice monouso).

Flusso: la Chat UI (Impostazioni → Telegram) chiede un link
``t.me/<manager>?start=pair_<code>``; l'utente lo apre e il bot riscatta il codice.
Il codice in chiaro esiste solo nel link: nel DB c'è lo SHA-256.
Un utente AION ha al massimo un account Telegram e viceversa.
"""

from __future__ import annotations

import enum
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from src.channels.telegram.models import TgLink, TgPairingCode, add_audit
from src.data.engine import get_async_session_maker

PAIR_PREFIX = "pair_"
# Telegram: parametro di /start lungo al massimo 64 caratteri [A-Za-z0-9_-].
_CODE_BYTES = 24
_TOUCH_EVERY = timedelta(minutes=1)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    # SQLite restituisce datetime naive anche con DateTime(timezone=True).
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class RedeemStatus(str, enum.Enum):
    LINKED = "linked"
    INVALID = "invalid"
    EXPIRED = "expired"
    USED = "used"
    TG_LINKED_TO_OTHER = "tg_linked_to_other"


@dataclass(frozen=True)
class LinkInfo:
    aion_user_id: str
    tg_user_id: int
    tg_username: Optional[str]
    tg_first_name: Optional[str]
    created_at: Optional[datetime]
    last_seen_at: Optional[datetime]

    @classmethod
    def from_row(cls, row: TgLink) -> "LinkInfo":
        return cls(
            aion_user_id=row.aion_user_id,
            tg_user_id=int(row.tg_user_id),
            tg_username=row.tg_username,
            tg_first_name=row.tg_first_name,
            created_at=_as_utc(row.created_at),
            last_seen_at=_as_utc(row.last_seen_at),
        )


@dataclass(frozen=True)
class PairingCode:
    code: str  # senza prefisso
    expires_at: datetime

    @property
    def start_param(self) -> str:
        return PAIR_PREFIX + self.code


class TelegramAccounts:
    def __init__(
        self,
        session_maker: Optional[Callable[[], Any]] = None,
        *,
        tenant_id: str = "default",
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._session_maker = session_maker
        self.tenant_id = tenant_id
        self._now = now

    def _session(self):
        maker = self._session_maker or get_async_session_maker()
        return maker()

    _audit = staticmethod(add_audit)

    # ---------- codici ----------
    async def create_pairing_code(
        self, aion_user_id: str, *, ttl_min: int
    ) -> PairingCode:
        """Nuovo codice; quelli non usati dello stesso utente vengono invalidati."""
        code = secrets.token_urlsafe(_CODE_BYTES)
        expires_at = self._now() + timedelta(minutes=max(1, int(ttl_min)))
        async with self._session() as session:
            await session.execute(
                delete(TgPairingCode).where(
                    TgPairingCode.aion_user_id == aion_user_id,
                    TgPairingCode.used_at.is_(None),
                )
            )
            session.add(
                TgPairingCode(
                    code_hash=hash_code(code),
                    aion_user_id=aion_user_id,
                    created_at=self._now(),
                    expires_at=expires_at,
                )
            )
            self._audit(session, "pairing_code_created", aion_user_id=aion_user_id)
            await session.commit()
        return PairingCode(code=code, expires_at=expires_at)

    async def redeem_pairing_code(
        self,
        code: str,
        *,
        tg_user_id: int,
        tg_username: Optional[str] = None,
        tg_first_name: Optional[str] = None,
    ) -> tuple[RedeemStatus, Optional[LinkInfo]]:
        now = self._now()
        code_hash = hash_code(code.strip())
        async with self._session() as session:
            row = await session.get(TgPairingCode, code_hash)
            if row is None:
                return RedeemStatus.INVALID, None
            if row.used_at is not None:
                return RedeemStatus.USED, None
            if _as_utc(row.expires_at) <= now:
                return RedeemStatus.EXPIRED, None
            aion_user_id = row.aion_user_id

            current = (
                await session.execute(
                    select(TgLink).where(TgLink.tg_user_id == tg_user_id)
                )
            ).scalar_one_or_none()
            if current is not None and current.aion_user_id != aion_user_id:
                # Il codice resta valido: l'utente può fare /unlink e riprovare.
                return RedeemStatus.TG_LINKED_TO_OTHER, None

            consumed = await session.execute(
                update(TgPairingCode)
                .where(
                    TgPairingCode.code_hash == code_hash,
                    TgPairingCode.used_at.is_(None),
                )
                .values(used_at=now, used_by_tg_user_id=tg_user_id)
            )
            if consumed.rowcount != 1:
                return RedeemStatus.USED, None

            if current is None:
                # Un nuovo account Telegram sostituisce quello eventualmente già collegato.
                await session.execute(
                    delete(TgLink).where(TgLink.aion_user_id == aion_user_id)
                )
                current = TgLink(
                    id=str(uuid.uuid4()),
                    tenant_id=self.tenant_id,
                    aion_user_id=aion_user_id,
                    tg_user_id=tg_user_id,
                    created_at=now,
                )
                session.add(current)
            current.tg_username = tg_username
            current.tg_first_name = tg_first_name
            current.last_seen_at = now
            self._audit(
                session, "linked", aion_user_id=aion_user_id, tg_user_id=tg_user_id
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return RedeemStatus.TG_LINKED_TO_OTHER, None
            return RedeemStatus.LINKED, LinkInfo.from_row(current)

    # ---------- collegamenti ----------
    async def get_link_for_user(self, aion_user_id: str) -> Optional[LinkInfo]:
        async with self._session() as session:
            row = (
                await session.execute(
                    select(TgLink).where(TgLink.aion_user_id == aion_user_id)
                )
            ).scalar_one_or_none()
        return LinkInfo.from_row(row) if row else None

    async def get_link_for_tg(self, tg_user_id: int) -> Optional[LinkInfo]:
        async with self._session() as session:
            row = (
                await session.execute(
                    select(TgLink).where(TgLink.tg_user_id == tg_user_id)
                )
            ).scalar_one_or_none()
        return LinkInfo.from_row(row) if row else None

    async def unlink(
        self,
        *,
        aion_user_id: Optional[str] = None,
        tg_user_id: Optional[int] = None,
        source: str,
    ) -> Optional[LinkInfo]:
        """Rimuove il collegamento (per utente AION o per account Telegram)."""
        if aion_user_id is None and tg_user_id is None:
            raise ValueError("aion_user_id or tg_user_id required")
        async with self._session() as session:
            q = select(TgLink)
            q = (
                q.where(TgLink.aion_user_id == aion_user_id)
                if aion_user_id is not None
                else q.where(TgLink.tg_user_id == tg_user_id)
            )
            row = (await session.execute(q)).scalar_one_or_none()
            if row is None:
                return None
            info = LinkInfo.from_row(row)
            await session.delete(row)
            self._audit(
                session,
                "unlinked",
                aion_user_id=info.aion_user_id,
                tg_user_id=info.tg_user_id,
                source=source,
            )
            await session.commit()
        return info

    async def touch(
        self,
        link: LinkInfo,
        *,
        tg_username: Optional[str],
        tg_first_name: Optional[str],
    ) -> None:
        """Aggiorna last_seen_at e nome Telegram, al massimo una volta al minuto."""
        now = self._now()
        changed = (link.tg_username, link.tg_first_name) != (tg_username, tg_first_name)
        if not changed and link.last_seen_at and now - link.last_seen_at < _TOUCH_EVERY:
            return
        async with self._session() as session:
            await session.execute(
                update(TgLink)
                .where(TgLink.tg_user_id == link.tg_user_id)
                .values(
                    last_seen_at=now,
                    tg_username=tg_username,
                    tg_first_name=tg_first_name,
                )
            )
            await session.commit()
