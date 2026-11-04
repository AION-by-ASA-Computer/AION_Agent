"""Bot personali (managed bot) creati dal bot manager con /newbot.

Flusso: il wizard salva una richiesta in ``tg_pending_creations`` e mostra il
pulsante ``request_managed_bot``; l'utente conferma nel client Telegram e il
manager riceve ``Message.managed_bot_created`` e ``Update.managed_bot`` (in
ordine non garantito, anche in parallelo). Entrambi passano da
``BotFactory.register``, idempotente: recupera il token con
``getManagedBotToken``, lo salva cifrato e configura il bot.

Il token è cifrato con la chiave delle credenziali di AION
(``AION_CREDENTIAL_ENCRYPTION_KEY``, AES-256-GCM): in chiaro esiste solo in memoria.
Il polling dei bot figli è di ``BotSupervisor`` (supervisor.py).
"""

from __future__ import annotations

import asyncio
import enum
import logging
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional
from urllib.parse import quote

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    ReplyKeyboardRemove,
    User,
)
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from src.channels.telegram import groups
from src.channels.telegram.accounts import TelegramAccounts
from src.channels.telegram.adapter import AionAdapter, ChatAccessError
from src.channels.telegram.config import TelegramSettings
from src.channels.telegram.models import (
    TgBot,
    TgLink,
    TgPairingCode,
    TgPendingCreation,
    TgSession,
    TgUserQuota,
    add_audit,
)
from src.channels.telegram.redact import redact
from src.data.engine import get_async_session_maker

if TYPE_CHECKING:
    from src.channels.telegram.supervisor import BotSupervisor

logger = logging.getLogger("aion.telegram")

PENDING_TTL = timedelta(minutes=30)
# last_error dei bot sospesi dallo scollegamento: li riconosce resume_after_link.
UNLINKED_REASON = "account Telegram scollegato"
# last_error dei bot passati a un altro account Telegram: li riassegna un admin.
OWNER_CHANGED_REASON = "proprietario cambiato su Telegram"
# Telegram: username 5-32 caratteri [a-zA-Z0-9_], inizia con una lettera, finisce con "bot".
_USERNAME_MAX = 32
NAME_MAX = 64

# Menu dei bot condivisi nei gruppi (registrato solo con ``groups.GROUPS_ENABLED``).
GROUP_COMMANDS = [
    BotCommand(command="ask", description="Fai una domanda all'assistente"),
    BotCommand(command="new", description="Ricomincia la tua conversazione"),
    BotCommand(command="stop", description="Interrompi la tua risposta in corso"),
    BotCommand(command="help", description="Come usare l'assistente"),
]

# Menu dei bot figli in chat privata.
CHILD_COMMANDS = [
    BotCommand(command="new", description="Nuova conversazione"),
    BotCommand(command="project", description="Scegli il progetto"),
    BotCommand(command="stop", description="Interrompi la risposta in corso"),
    BotCommand(command="status", description="Profilo e progetto del bot"),
    BotCommand(command="help", description="Elenco dei comandi"),
]


class BotStatus(str, enum.Enum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ERROR = "error"
    DELETED = "deleted"


class BotMode(str, enum.Enum):
    PERSONAL = "personal"  # solo il proprietario, solo in privato
    SHARED = "shared"  # tutti gli utenti AION collegati (e i gruppi, se attivi)


MODE_LABELS = {
    BotMode.PERSONAL.value: "🔒 personale",
    BotMode.SHARED.value: "👥 condiviso",
}

STATUS_LABELS = {
    BotStatus.PROVISIONING.value: "⏳ in configurazione",
    BotStatus.ACTIVE.value: "🟢 attivo",
    BotStatus.SUSPENDED.value: "⏸️ sospeso",
    BotStatus.ERROR.value: "⚠️ errore",
    BotStatus.DELETED.value: "🗑️ eliminato",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def suggest_username(name: str) -> str:
    """``"Assistente RAG"`` → ``assistente_rag_bot`` (l'utente può cambiarlo in Telegram)."""
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    if not base or not base[0].isalpha():
        base = f"aion_{base}".strip("_")
    if base.endswith("bot"):
        base = base[:-3].rstrip("_")
    base = base[: _USERNAME_MAX - len("_bot")].rstrip("_") or "aion"
    return f"{base}_bot"


# ---------- cifratura del token ----------
def token_encryption_error() -> Optional[str]:
    """None se i token possono essere cifrati, altrimenti il motivo."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    except ImportError:
        return "pacchetto `cryptography` non installato"
    from src.runtime.credential_store import decrypt_value, encrypt_value

    try:
        if decrypt_value(encrypt_value("probe")) != "probe":
            return "cifratura non reversibile"
    except Exception as e:  # noqa: BLE001 — chiave assente o non valida in produzione
        return str(e)
    return None


def seal_token(token: str) -> str:
    from src.runtime.credential_store import encrypt_value

    return encrypt_value(token)


def open_token(token_enc: str) -> str:
    from src.runtime.credential_store import decrypt_value

    return decrypt_value(token_enc)


@dataclass(frozen=True)
class BotInfo:
    id: int
    owner_aion_user_id: str
    owner_tg_user_id: int
    bot_tg_id: int
    username: Optional[str]
    name: Optional[str]
    profile_slug: Optional[str]
    project_slug: Optional[str]
    status: str
    last_error: Optional[str]
    has_token: bool
    created_at: Optional[datetime]
    mode: str = BotMode.PERSONAL.value
    pending_owner_tg_user_id: Optional[int] = None
    last_activity_at: Optional[datetime] = None

    @property
    def shared(self) -> bool:
        return self.mode == BotMode.SHARED.value

    @classmethod
    def from_row(cls, row: TgBot) -> "BotInfo":
        return cls(
            id=row.id,
            owner_aion_user_id=row.owner_aion_user_id,
            owner_tg_user_id=int(row.owner_tg_user_id),
            bot_tg_id=int(row.bot_tg_id),
            username=row.username,
            name=row.name,
            profile_slug=row.profile_slug,
            project_slug=row.project_slug,
            status=row.status,
            last_error=row.last_error,
            has_token=bool(row.token_enc),
            created_at=_as_utc(row.created_at),
            mode=row.mode or BotMode.PERSONAL.value,
            pending_owner_tg_user_id=(
                int(row.pending_owner_tg_user_id)
                if row.pending_owner_tg_user_id is not None
                else None
            ),
            last_activity_at=_as_utc(row.last_activity_at),
        )

    @property
    def mention(self) -> str:
        return (
            f"@{self.username}" if self.username else (self.name or str(self.bot_tg_id))
        )


@dataclass(frozen=True)
class PendingCreation:
    owner_tg_user_id: int
    owner_aion_user_id: str
    request_id: int
    name: str
    profile_slug: Optional[str]
    project_slug: Optional[str]
    expires_at: datetime
    mode: str = BotMode.PERSONAL.value


_UNSET: Any = object()


class TelegramBots:
    """Accesso a ``tg_bots`` / ``tg_pending_creations`` (solo DB, nessuna rete)."""

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

    # ---------- richieste in attesa ----------
    async def save_pending(
        self,
        *,
        owner_tg_user_id: int,
        owner_aion_user_id: str,
        name: str,
        profile_slug: Optional[str],
        project_slug: Optional[str],
        mode: str = BotMode.PERSONAL.value,
    ) -> PendingCreation:
        """Nuova richiesta /newbot; sostituisce quella precedente dello stesso account."""
        mode = BotMode(mode).value
        pending = PendingCreation(
            owner_tg_user_id=owner_tg_user_id,
            owner_aion_user_id=owner_aion_user_id,
            request_id=secrets.randbelow(2**31 - 1) + 1,
            name=name,
            profile_slug=profile_slug,
            project_slug=project_slug,
            expires_at=self._now() + PENDING_TTL,
            mode=mode,
        )
        async with self._session() as session:
            await session.execute(
                delete(TgPendingCreation).where(
                    TgPendingCreation.owner_tg_user_id == owner_tg_user_id
                )
            )
            session.add(
                TgPendingCreation(
                    owner_tg_user_id=owner_tg_user_id,
                    owner_aion_user_id=owner_aion_user_id,
                    request_id=pending.request_id,
                    name=name,
                    profile_slug=profile_slug,
                    project_slug=project_slug,
                    mode=mode,
                    created_at=self._now(),
                    expires_at=pending.expires_at,
                )
            )
            add_audit(
                session,
                "bot_creation_requested",
                aion_user_id=owner_aion_user_id,
                tg_user_id=owner_tg_user_id,
                name=name,
            )
            await session.commit()
        return pending

    async def pop_pending(self, owner_tg_user_id: int) -> Optional[PendingCreation]:
        """Consuma la richiesta dell'account (None se assente o scaduta)."""
        async with self._session() as session:
            row = await session.get(TgPendingCreation, owner_tg_user_id)
            if row is None:
                return None
            pending = PendingCreation(
                owner_tg_user_id=int(row.owner_tg_user_id),
                owner_aion_user_id=row.owner_aion_user_id,
                request_id=row.request_id,
                name=row.name,
                profile_slug=row.profile_slug,
                project_slug=row.project_slug,
                expires_at=_as_utc(row.expires_at),
                mode=row.mode or BotMode.PERSONAL.value,
            )
            await session.delete(row)
            await session.commit()
        return pending if pending.expires_at > self._now() else None

    async def discard_pending(self, owner_tg_user_id: int) -> None:
        async with self._session() as session:
            await session.execute(
                delete(TgPendingCreation).where(
                    TgPendingCreation.owner_tg_user_id == owner_tg_user_id
                )
            )
            await session.commit()

    # ---------- bot ----------
    async def count_for_owner(self, owner_aion_user_id: str) -> int:
        """Bot che occupano la quota (tutti tranne gli eliminati)."""
        async with self._session() as session:
            return int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(TgBot)
                        .where(
                            TgBot.owner_aion_user_id == owner_aion_user_id,
                            TgBot.status != BotStatus.DELETED.value,
                        )
                    )
                ).scalar_one()
            )

    async def list_for_owner(self, owner_aion_user_id: str) -> list[BotInfo]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    select(TgBot)
                    .where(
                        TgBot.owner_aion_user_id == owner_aion_user_id,
                        TgBot.status != BotStatus.DELETED.value,
                    )
                    .order_by(TgBot.id)
                )
            ).scalars()
            return [BotInfo.from_row(r) for r in rows]

    async def get(self, bot_id: int) -> Optional[BotInfo]:
        async with self._session() as session:
            row = await session.get(TgBot, bot_id)
            return BotInfo.from_row(row) if row else None

    async def get_by_tg_id(self, bot_tg_id: int) -> Optional[BotInfo]:
        async with self._session() as session:
            row = (
                await session.execute(select(TgBot).where(TgBot.bot_tg_id == bot_tg_id))
            ).scalar_one_or_none()
            return BotInfo.from_row(row) if row else None

    async def create(
        self,
        *,
        owner_aion_user_id: str,
        owner_tg_user_id: int,
        bot_tg_id: int,
        username: Optional[str],
        name: Optional[str],
        profile_slug: Optional[str],
        project_slug: Optional[str],
        token: str,
        status: BotStatus = BotStatus.PROVISIONING,
        last_error: Optional[str] = None,
        mode: str = BotMode.PERSONAL.value,
    ) -> Optional[BotInfo]:
        """Nuovo bot; None se ``bot_tg_id`` è già registrato.

        Un bot eliminato con lo stesso id (ricreato o restituito da Telegram) viene
        riutilizzato: la riga resta unica per ``bot_tg_id``.
        """
        now = self._now()
        async with self._session() as session:
            row = (
                await session.execute(select(TgBot).where(TgBot.bot_tg_id == bot_tg_id))
            ).scalar_one_or_none()
            if row is not None and row.status != BotStatus.DELETED.value:
                return None
            if row is None:
                row = TgBot(
                    bot_tg_id=bot_tg_id, tenant_id=self.tenant_id, created_at=now
                )
                session.add(row)
            row.owner_aion_user_id = owner_aion_user_id
            row.owner_tg_user_id = owner_tg_user_id
            row.username = username
            row.name = name
            row.kind = "managed"
            row.mode = BotMode(mode).value
            row.profile_slug = profile_slug
            row.project_slug = project_slug
            row.token_enc = seal_token(token)
            row.status = status.value
            row.last_error = last_error
            row.updated_at = now
            add_audit(
                session,
                "bot_created",
                aion_user_id=owner_aion_user_id,
                tg_user_id=owner_tg_user_id,
                bot_tg_id=bot_tg_id,
                username=username,
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return None
            return BotInfo.from_row(row)

    async def update(
        self,
        bot_id: int,
        *,
        status: Any = _UNSET,
        last_error: Any = _UNSET,
        profile_slug: Any = _UNSET,
        project_slug: Any = _UNSET,
        token: Any = _UNSET,
        username: Any = _UNSET,
        name: Any = _UNSET,
        mode: Any = _UNSET,
        owner_tg_user_id: Any = _UNSET,
        owner_aion_user_id: Any = _UNSET,
        pending_owner_tg_user_id: Any = _UNSET,
        audit: Optional[str] = None,
        actor_tg_user_id: Optional[int] = None,
    ) -> Optional[BotInfo]:
        values: Dict[str, Any] = {}
        if name is not _UNSET:
            values["name"] = name
        if mode is not _UNSET:
            values["mode"] = BotMode(mode).value
        if status is not _UNSET:
            values["status"] = BotStatus(status).value
        if last_error is not _UNSET:
            values["last_error"] = last_error
        if profile_slug is not _UNSET:
            values["profile_slug"] = profile_slug
        if project_slug is not _UNSET:
            values["project_slug"] = project_slug
        if token is not _UNSET:
            values["token_enc"] = seal_token(token) if token else None
        if username is not _UNSET:
            values["username"] = username
        if owner_tg_user_id is not _UNSET:
            values["owner_tg_user_id"] = owner_tg_user_id
        if owner_aion_user_id is not _UNSET:
            values["owner_aion_user_id"] = owner_aion_user_id
        if pending_owner_tg_user_id is not _UNSET:
            values["pending_owner_tg_user_id"] = pending_owner_tg_user_id
        async with self._session() as session:
            row = await session.get(TgBot, bot_id)
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = self._now()
            if audit:
                add_audit(
                    session,
                    audit,
                    aion_user_id=row.owner_aion_user_id,
                    tg_user_id=actor_tg_user_id,
                    bot_tg_id=int(row.bot_tg_id),
                    **({"status": values["status"]} if "status" in values else {}),
                )
            await session.commit()
            return BotInfo.from_row(row)

    async def list_active(self) -> list[BotInfo]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    select(TgBot)
                    .where(
                        TgBot.tenant_id == self.tenant_id,
                        TgBot.status == BotStatus.ACTIVE.value,
                    )
                    .order_by(TgBot.id)
                )
            ).scalars()
            return [BotInfo.from_row(r) for r in rows]

    async def list_all(self) -> list[BotInfo]:
        """Tutti i bot del tenant tranne gli eliminati (riconciliazione)."""
        async with self._session() as session:
            rows = (
                await session.execute(
                    select(TgBot)
                    .where(
                        TgBot.tenant_id == self.tenant_id,
                        TgBot.status != BotStatus.DELETED.value,
                    )
                    .order_by(TgBot.id)
                )
            ).scalars()
            return [BotInfo.from_row(r) for r in rows]

    async def token_for(self, bot_id: int) -> Optional[str]:
        async with self._session() as session:
            row = await session.get(TgBot, bot_id)
            token_enc = row.token_enc if row else None
        return open_token(token_enc) if token_enc else None

    # ---------- amministrazione ----------
    async def list_admin(self, *, include_deleted: bool = False) -> list[BotInfo]:
        async with self._session() as session:
            q = select(TgBot).where(TgBot.tenant_id == self.tenant_id)
            if not include_deleted:
                q = q.where(TgBot.status != BotStatus.DELETED.value)
            rows = (await session.execute(q.order_by(TgBot.id))).scalars()
            return [BotInfo.from_row(r) for r in rows]

    async def touch_activity(self, bot_id: int, *, every: timedelta) -> None:
        """``last_activity_at`` = adesso, al massimo una volta ogni ``every``."""
        now = self._now()
        async with self._session() as session:
            row = await session.get(TgBot, bot_id)
            if row is None:
                return
            last = _as_utc(row.last_activity_at)
            if last is not None and now - last < every:
                return
            row.last_activity_at = now
            await session.commit()

    async def quota_for(self, aion_user_id: str) -> Optional[int]:
        """Quota personalizzata dell'utente, None = quella di default."""
        async with self._session() as session:
            row = await session.get(TgUserQuota, aion_user_id)
            return int(row.max_bots) if row else None

    async def list_quotas(self) -> Dict[str, int]:
        async with self._session() as session:
            rows = (await session.execute(select(TgUserQuota))).scalars()
            return {r.aion_user_id: int(r.max_bots) for r in rows}

    async def set_quota(
        self, aion_user_id: str, max_bots: Optional[int], *, actor: Optional[str] = None
    ) -> None:
        """Quota personalizzata (``None`` torna a quella di default)."""
        async with self._session() as session:
            row = await session.get(TgUserQuota, aion_user_id)
            if max_bots is None:
                if row is not None:
                    await session.delete(row)
            elif row is None:
                session.add(
                    TgUserQuota(
                        aion_user_id=aion_user_id,
                        max_bots=int(max_bots),
                        updated_at=self._now(),
                    )
                )
            else:
                row.max_bots = int(max_bots)
                row.updated_at = self._now()
            add_audit(
                session,
                "quota_changed",
                aion_user_id=aion_user_id,
                max_bots=max_bots,
                actor=actor,
            )
            await session.commit()

    async def purge_user_rows(self, aion_user_id: str) -> None:
        """Dati del canale di un utente AION eliminato (oltre ai bot, già revocati).

        Le FK ``ON DELETE CASCADE`` non valgono su tutti i DB SQLite di AION:
        pulizia esplicita, come fa ``DELETE /admin/users`` per le altre tabelle.
        """
        async with self._session() as session:
            for model, column in (
                (TgLink, TgLink.aion_user_id),
                (TgPairingCode, TgPairingCode.aion_user_id),
                (TgSession, TgSession.aion_user_id),
                (TgPendingCreation, TgPendingCreation.owner_aion_user_id),
                (TgUserQuota, TgUserQuota.aion_user_id),
            ):
                await session.execute(delete(model).where(column == aion_user_id))
            add_audit(session, "user_purged", aion_user_id=aion_user_id)
            await session.commit()


def child_bot(token: str, settings: TelegramSettings) -> Bot:
    session = AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else None
    return Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML, link_preview_is_disabled=True
        ),
    )


class QuotaExceeded(Exception):
    pass


class BotFactory:
    """Creazione e gestione dei bot personali via Bot API del manager."""

    def __init__(
        self,
        *,
        bots: TelegramBots,
        accounts: TelegramAccounts,
        adapter: AionAdapter,
        settings: TelegramSettings,
        child_bot: Callable[[str, TelegramSettings], Bot] = child_bot,
    ) -> None:
        self.bots = bots
        self.accounts = accounts
        self.adapter = adapter
        self.settings = settings
        self._child_bot = child_bot
        self._locks: Dict[int, asyncio.Lock] = {}
        # Valorizzati dal gateway dopo getMe.
        self.can_manage_bots: Optional[bool] = None
        self.manager_username: Optional[str] = None
        # BotSupervisor (polling dei bot figli); None nei test senza gateway.
        self.supervisor: Optional["BotSupervisor"] = None

    async def sync_runtime(
        self, info: Optional[BotInfo], *, restart: bool = False
    ) -> None:
        """Allinea il polling del bot al suo stato (attivo → in ascolto)."""
        if self.supervisor is None or info is None:
            return
        try:
            if restart:
                await self.supervisor.restart(info)
            else:
                await self.supervisor.ensure(info)
        except Exception as e:  # noqa: BLE001 — il polling non deve bloccare la gestione
            logger.warning(
                "telegram: avvio/stop del bot %s fallito: %s", info.mention, redact(e)
            )

    # ---------- precondizioni di /newbot ----------
    def unavailable_reason(self) -> Optional[str]:
        """Messaggio per l'utente se /newbot non può funzionare; None se è tutto pronto."""
        if self.can_manage_bots is False:
            return (
                "La creazione di bot non è abilitata su questo bot manager.\n"
                "L'amministratore deve attivare <b>Bot Management Mode</b> nella "
                "Mini App di @BotFather."
            )
        error = token_encryption_error()
        if error:
            logger.error(
                "telegram: /newbot non disponibile, cifratura token: %s", error
            )
            return (
                "La creazione di bot non è disponibile: manca la chiave di cifratura "
                "delle credenziali di AION. Contatta l'amministratore."
            )
        return None

    async def quota_limit(self, owner_aion_user_id: str) -> int:
        custom = await self.bots.quota_for(owner_aion_user_id)
        return max(
            0, int(custom if custom is not None else self.settings.max_bots_per_user)
        )

    async def check_quota(self, owner_aion_user_id: str) -> None:
        limit = await self.quota_limit(owner_aion_user_id)
        if await self.bots.count_for_owner(owner_aion_user_id) >= limit:
            raise QuotaExceeded(
                f"Hai già raggiunto il numero massimo di bot ({limit}). "
                "Eliminane uno da /mybots per crearne un altro."
            )

    def creation_link(self, username: str, name: str) -> Optional[str]:
        """Link alternativo al pulsante: ``t.me/newbot/<manager>/<username>?name=...``."""
        if not self.manager_username:
            return None
        return (
            f"https://t.me/newbot/{self.manager_username}/{username}?name={quote(name)}"
        )

    # ---------- creazione ----------
    def _lock(self, bot_tg_id: int) -> asyncio.Lock:
        lock = self._locks.get(bot_tg_id)
        if lock is None:
            lock = self._locks[bot_tg_id] = asyncio.Lock()
        return lock

    async def register(
        self, manager: Bot, *, owner: User, bot_user: User, refresh_token: bool
    ) -> tuple[Optional[BotInfo], bool]:
        """Registra il bot creato o aggiornato da Telegram. Ritorna (bot, creato_ora)."""
        async with self._lock(bot_user.id):
            existing = await self.bots.get_by_tg_id(bot_user.id)
            if existing is not None and existing.status == BotStatus.DELETED.value:
                # Eliminato da AION: anche la revoca del token fatta da ``delete``
                # genera un update managed_bot, che non deve riattivarlo.
                logger.info(
                    "telegram: update per il bot eliminato %s ignorato",
                    existing.mention,
                )
                return existing, False
            if existing is not None:
                updated = await self._on_update(
                    manager, existing, owner, bot_user, refresh_token
                )
                return updated, False
            return await self._create(manager, owner, bot_user)

    async def _on_update(
        self,
        manager: Bot,
        info: BotInfo,
        owner: User,
        bot_user: User,
        refresh_token: bool,
    ) -> BotInfo:
        if owner.id != info.owner_tg_user_id:
            # Proprietà trasferita su Telegram: fermo finché un admin non conferma.
            updated = await self.bots.update(
                info.id,
                status=BotStatus.SUSPENDED,
                last_error=OWNER_CHANGED_REASON,
                pending_owner_tg_user_id=owner.id,
                audit="bot_owner_changed",
                actor_tg_user_id=owner.id,
            )
            await self.sync_runtime(updated)
            await self._notify(
                manager,
                info.owner_tg_user_id,
                f"⚠️ Il bot {escape(info.mention)} è passato a un altro account "
                "Telegram: l'ho sospeso in AION.",
            )
            return updated or info
        if not refresh_token:
            return info
        # managed_bot arriva anche quando il token viene rigenerato da @BotFather.
        token = await manager.get_managed_bot_token(user_id=bot_user.id)
        try:
            unchanged = await self.bots.token_for(info.id) == token
        except Exception:  # noqa: BLE001 — token salvato non decifrabile
            unchanged = False
        if unchanged:
            return info
        updated = await self.bots.update(
            info.id,
            token=token,
            username=bot_user.username or info.username,
            audit="bot_token_synced",
            actor_tg_user_id=owner.id,
        )
        await self.sync_runtime(updated, restart=True)
        return updated or info

    async def _create(
        self, manager: Bot, owner: User, bot_user: User
    ) -> tuple[Optional[BotInfo], bool]:
        link = await self.accounts.get_link_for_tg(owner.id)
        if link is None:
            logger.warning(
                "telegram: bot %s creato da un account non collegato (%s): ignorato",
                bot_user.id,
                owner.id,
            )
            return None, False
        user = await self.adapter.resolve_user(link.aion_user_id)
        if user is None:
            return None, False
        pending = await self.bots.pop_pending(owner.id)
        if pending is not None and pending.owner_aion_user_id != user.row_id:
            pending = None

        status, last_error = BotStatus.PROVISIONING, None
        if pending is None:
            # Creato fuori dal wizard (link t.me/newbot o richiesta scaduta).
            try:
                await self.check_quota(user.row_id)
            except QuotaExceeded:
                status, last_error = BotStatus.SUSPENDED, "quota superata"
        try:
            profile = await self.adapter.resolve_profile(
                user,
                (pending.profile_slug if pending else None)
                or self.settings.default_profile,
            )
        except ChatAccessError:
            profile = None

        token = await manager.get_managed_bot_token(user_id=bot_user.id)
        info = await self.bots.create(
            owner_aion_user_id=user.row_id,
            owner_tg_user_id=owner.id,
            bot_tg_id=bot_user.id,
            username=bot_user.username,
            name=bot_user.first_name or (pending.name if pending else None),
            profile_slug=profile,
            project_slug=pending.project_slug if pending else None,
            token=token,
            status=status,
            last_error=last_error,
            mode=pending.mode if pending else BotMode.PERSONAL.value,
        )
        if info is None:  # registrato nel frattempo (altro update dello stesso bot)
            return await self.bots.get_by_tg_id(bot_user.id), False
        if status is BotStatus.PROVISIONING:
            info = await self.provision(manager, info, token)
            await self.sync_runtime(info)
        await self._notify(
            manager, owner.id, self.created_text(info), remove_keyboard=True
        )
        return info, True

    def created_text(self, info: BotInfo) -> str:
        if info.status == BotStatus.ACTIVE.value:
            head = f"✅ {escape(info.mention)} è pronto."
        elif info.last_error == "quota superata":
            head = (
                f"⏸️ {escape(info.mention)} è stato creato ma resta sospeso: "
                "hai raggiunto il numero massimo di bot."
            )
        else:
            head = (
                f"⚠️ {escape(info.mention)} è stato creato ma la configurazione non è "
                "riuscita. Riprova da /mybots."
            )
        profile = (
            escape(self.adapter.profile_name(info.profile_slug))
            if info.profile_slug
            else "—"
        )
        project = escape(info.project_slug) if info.project_slug else "nessuno"
        mode = MODE_LABELS.get(info.mode, info.mode)
        if not info.shared:
            usage = "Aprilo e scrivigli una domanda: risponde solo a te."
        elif groups.GROUPS_ENABLED:
            usage = (
                "Chiunque abbia collegato il proprio account ad AION può scrivergli, "
                "con i propri permessi. Solo tu puoi aggiungerlo ai gruppi: lì "
                "risponde a /ask e a chi risponde a un suo messaggio; per le "
                "menzioni @ rendilo amministratore del gruppo."
            )
        else:
            # Groups disabled: a shared bot is reachable only in private chats.
            usage = (
                "Chiunque abbia collegato il proprio account ad AION può scrivergli "
                "in chat privata, con i propri permessi."
            )
        return (
            f"{head}\n\nModalità: <b>{mode}</b>\nProfilo: <b>{profile}</b>\n"
            f"Progetto: <b>{project}</b>\n\n{usage}\nGestiscilo da /mybots."
        )

    async def provision(self, manager: Bot, info: BotInfo, token: str) -> BotInfo:
        """Comandi, descrizioni e accesso riservato al proprietario; poi ``active``."""
        profile = (
            self.adapter.profile_name(info.profile_slug)
            if info.profile_slug
            else "AION"
        )
        child = self._child_bot(token, self.settings)
        try:
            await child.set_my_commands(CHILD_COMMANDS)
            await child.set_my_short_description(f"Assistente AION — {profile}")
            await self._apply_mode(manager, child, info)
        except Exception as e:  # noqa: BLE001 — rete, token revocato, limiti API
            logger.warning(
                "telegram: configurazione del bot %s fallita: %s",
                info.bot_tg_id,
                redact(e),
            )
            return (
                await self.bots.update(
                    info.id,
                    status=BotStatus.ERROR,
                    last_error=redact(f"{type(e).__name__}: {e}")[:500],
                    audit="bot_provision_failed",
                )
                or info
            )
        finally:
            await child.session.close()
        return (
            await self.bots.update(
                info.id,
                status=BotStatus.ACTIVE,
                last_error=None,
                audit="bot_provisioned",
            )
            or info
        )

    async def _apply_mode(self, manager: Bot, child: Bot, info: BotInfo) -> None:
        """Descrizione, comandi nei gruppi e accesso Telegram secondo la modalità."""
        profile = (
            self.adapter.profile_name(info.profile_slug)
            if info.profile_slug
            else "AION"
        )
        if info.shared:
            group_hint = (
                " Nei gruppi menzionalo o rispondi a un suo messaggio."
                if groups.GROUPS_ENABLED
                else ""
            )
            await child.set_my_description(
                f"Assistente AION condiviso (profilo {profile}). Per usarlo collega "
                f"il tuo account Telegram ad AION.{group_hint}"
            )
            # With groups disabled the group menu is removed, so bots provisioned
            # while groups were on stop advertising /ask there.
            if groups.GROUPS_ENABLED:
                await child.set_my_commands(
                    GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats()
                )
            else:
                await child.delete_my_commands(scope=BotCommandScopeAllGroupChats())
        else:
            await child.set_my_description(
                f"Assistente personale AION (profilo {profile}). "
                "Accessibile solo al proprietario."
            )
            await child.delete_my_commands(scope=BotCommandScopeAllGroupChats())
        # Condiviso: Telegram non filtra, il controllo è di AION (utente collegato).
        await manager.set_managed_bot_access_settings(
            user_id=info.bot_tg_id, is_access_restricted=not info.shared
        )

    async def set_mode(
        self,
        manager: Bot,
        info: BotInfo,
        mode: str,
        *,
        actor_tg_user_id: Optional[int] = None,
    ) -> BotInfo:
        """Cambia modalità: aggiorna il DB e le impostazioni del bot su Telegram."""
        mode = BotMode(mode).value
        if mode == info.mode:
            return info
        token = await self.bots.token_for(info.id)
        updated = await self.bots.update(
            info.id,
            mode=mode,
            audit="bot_mode_changed",
            actor_tg_user_id=actor_tg_user_id,
        )
        if updated is None or not token:
            return updated or info
        child = self._child_bot(token, self.settings)
        try:
            await self._apply_mode(manager, child, updated)
        finally:
            await child.session.close()
        return updated

    async def retry_provision(self, manager: Bot, info: BotInfo) -> BotInfo:
        token = await self.bots.token_for(info.id)
        if not token:
            token = await manager.get_managed_bot_token(user_id=info.bot_tg_id)
            await self.bots.update(info.id, token=token)
        info = await self.provision(manager, info, token)
        await self.sync_runtime(info)
        return info

    # ---------- ciclo di vita legato all'account ----------
    async def suspend_for_unlink(self, aion_user_id: str) -> list[BotInfo]:
        """Account Telegram scollegato: gli assistenti attivi smettono di ascoltare.

        Tornano attivi da soli se lo stesso utente ricollega lo stesso account
        (``resume_after_link``); sospesi per altri motivi restano come sono.
        """
        suspended = []
        for info in await self.bots.list_for_owner(aion_user_id):
            if info.status != BotStatus.ACTIVE.value:
                continue
            async with self._lock(info.bot_tg_id):
                updated = await self.bots.update(
                    info.id,
                    status=BotStatus.SUSPENDED,
                    last_error=UNLINKED_REASON,
                    audit="bot_suspended_unlink",
                )
                await self.sync_runtime(updated)
            if updated is not None:
                suspended.append(updated)
        return suspended

    async def resume_after_link(
        self, aion_user_id: str, tg_user_id: int
    ) -> list[BotInfo]:
        """Ricollegamento: riattiva gli assistenti sospesi dallo scollegamento.

        Solo quelli dello stesso account Telegram: per Telegram il proprietario
        resta l'account che li ha creati.
        """
        resumed = []
        for info in await self.bots.list_for_owner(aion_user_id):
            if (
                info.status != BotStatus.SUSPENDED.value
                or info.last_error != UNLINKED_REASON
                or info.owner_tg_user_id != tg_user_id
            ):
                continue
            async with self._lock(info.bot_tg_id):
                updated = await self.bots.update(
                    info.id,
                    status=BotStatus.ACTIVE,
                    last_error=None,
                    audit="bot_resumed_link",
                    actor_tg_user_id=tg_user_id,
                )
                await self.sync_runtime(updated)
            if updated is not None:
                resumed.append(updated)
        return resumed

    async def purge_user(self, manager: Optional[Bot], aion_user_id: str) -> int:
        """Utente AION eliminato: revoca i token dei suoi assistenti e ne rimuove i dati."""
        bots = await self.bots.list_for_owner(aion_user_id)
        for info in bots:
            await self.delete(manager, info, actor_tg_user_id=None)
        await self.bots.purge_user_rows(aion_user_id)
        return len(bots)

    # ---------- token ----------
    async def rotate_token(
        self, manager: Bot, info: BotInfo, *, actor_tg_user_id: Optional[int]
    ) -> BotInfo:
        """Nuovo token (``replaceManagedBotToken``): il vecchio smette di funzionare.

        Tutto sotto il lock del bot: l'update managed_bot generato dalla rotazione
        attende, trova il token già aggiornato e non riavvia il polling una seconda volta.
        """
        async with self._lock(info.bot_tg_id):
            token = await manager.replace_managed_bot_token(user_id=info.bot_tg_id)
            updated = await self.bots.update(
                info.id,
                token=token,
                audit="bot_token_rotated",
                actor_tg_user_id=actor_tg_user_id,
            )
            await self.sync_runtime(updated, restart=True)
        return updated or info

    # ---------- riconciliazione ----------
    async def reconcile(self, manager: Bot) -> dict:
        """Controllo periodico di tutti i bot: nome/username, ripresa dagli errori,
        bot cancellati da @BotFather. Gli errori di rete non cambiano nulla."""
        from aiogram.exceptions import TelegramUnauthorizedError

        summary = {"checked": 0, "updated": 0, "recovered": 0, "gone": 0}
        for info in await self.bots.list_all():
            if not info.has_token:
                continue
            summary["checked"] += 1
            try:
                token = await self.bots.token_for(info.id)
            except Exception:  # noqa: BLE001 — chiave di cifratura cambiata
                continue
            child = self._child_bot(token, self.settings)
            try:
                me = await child.get_me()
            except TelegramUnauthorizedError:
                me = None
            except Exception as e:  # noqa: BLE001 — rete: si riprova al prossimo giro
                logger.info(
                    "telegram: riconciliazione di %s rimandata: %s",
                    info.mention,
                    redact(e),
                )
                continue
            finally:
                await child.session.close()
            if me is None:
                result = await self._reconcile_unauthorized(manager, info)
            else:
                result = await self._reconcile_alive(manager, info, me)
            if result:
                summary[result] += 1
        if summary["updated"] or summary["recovered"] or summary["gone"]:
            logger.info("telegram: riconciliazione bot %s", summary)
        return summary

    async def _reconcile_alive(
        self, manager: Bot, info: BotInfo, me: User
    ) -> Optional[str]:
        changes = {}
        if me.username and me.username != info.username:
            changes["username"] = me.username
        if me.first_name and me.first_name != info.name:
            changes["name"] = me.first_name
        recover = info.status == BotStatus.ERROR.value
        if not changes and not recover:
            return None
        async with self._lock(info.bot_tg_id):
            current = await self.bots.get(info.id)
            if current is None or current.status == BotStatus.DELETED.value:
                return None
            fields = dict(changes)
            if recover and current.status == BotStatus.ERROR.value:
                fields.update(status=BotStatus.ACTIVE, last_error=None)
            updated = await self.bots.update(info.id, audit="bot_reconciled", **fields)
            if "status" in fields:
                await self.sync_runtime(updated)
        if "status" in fields and updated is not None:
            await self._notify(
                manager,
                info.owner_tg_user_id,
                f"✅ {escape(updated.mention)} funziona di nuovo ed è tornato attivo.",
            )
            return "recovered"
        return "updated"

    async def _reconcile_unauthorized(
        self, manager: Bot, info: BotInfo
    ) -> Optional[str]:
        """Token rifiutato: o è cambiato senza che arrivasse l'update, o il bot
        non esiste più (cancellato da @BotFather o non più gestito dal manager)."""
        try:
            token = await manager.get_managed_bot_token(user_id=info.bot_tg_id)
        except Exception as e:  # noqa: BLE001 — bot sparito per Telegram
            async with self._lock(info.bot_tg_id):
                current = await self.bots.get(info.id)
                if current is None or current.status == BotStatus.DELETED.value:
                    return None
                await self.bots.update(
                    info.id,
                    status=BotStatus.DELETED,
                    token=None,
                    last_error=redact(f"{type(e).__name__}: {e}")[:500],
                    audit="bot_gone",
                )
                if self.supervisor is not None:
                    await self.supervisor.stop(info.bot_tg_id)
            await self._notify(
                manager,
                info.owner_tg_user_id,
                f"🗑️ {escape(info.mention)} non esiste più su Telegram: "
                "l'ho rimosso da /mybots.",
            )
            return "gone"
        async with self._lock(info.bot_tg_id):
            current = await self.bots.get(info.id)
            if current is None or current.status == BotStatus.DELETED.value:
                return None
            fields: dict = {"token": token}
            if current.status == BotStatus.ERROR.value:
                fields.update(status=BotStatus.ACTIVE, last_error=None)
            updated = await self.bots.update(
                info.id, audit="bot_token_synced", **fields
            )
            await self.sync_runtime(updated, restart=True)
        return "recovered" if "status" in fields else "updated"

    async def delete(
        self, manager: Optional[Bot], info: BotInfo, *, actor_tg_user_id: Optional[int]
    ) -> None:
        """Revoca il token (``replaceManagedBotToken``, il nuovo viene scartato) e
        marca il bot come eliminato. Il bot resta su Telegram finché l'utente non
        lo cancella da @BotFather: la Bot API non permette di eliminarlo.

        Ordine: prima lo stato ``deleted`` (sotto lo stesso lock di ``register``),
        poi stop del polling, infine la revoca. La revoca fa arrivare un update
        managed_bot "token cambiato" che, trovando il bot già eliminato, viene ignorato.
        """
        async with self._lock(info.bot_tg_id):
            await self.bots.update(
                info.id,
                status=BotStatus.DELETED,
                token=None,
                last_error=None,
                audit="bot_deleted",
                actor_tg_user_id=actor_tg_user_id,
            )
            if self.supervisor is not None:
                await self.supervisor.stop(info.bot_tg_id)
        if manager is None:
            # Gateway spento: il token resta valido su Telegram finché non lo si revoca.
            logger.warning(
                "telegram: bot %s eliminato senza revoca del token (gateway spento)",
                info.mention,
            )
            return
        try:
            await manager.replace_managed_bot_token(user_id=info.bot_tg_id)
        except Exception as e:  # noqa: BLE001 — il bot può essere già stato cancellato
            logger.warning(
                "telegram: revoca token del bot %s fallita: %s",
                info.bot_tg_id,
                redact(e),
            )

    # ---------- amministrazione (Admin UI) ----------
    async def admin_set_status(
        self, manager: Optional[Bot], info: BotInfo, *, active: bool, actor: str
    ) -> BotInfo:
        """Sospende o riattiva un bot dall'Admin UI e avvisa il proprietario."""
        async with self._lock(info.bot_tg_id):
            updated = await self.bots.update(
                info.id,
                status=BotStatus.ACTIVE if active else BotStatus.SUSPENDED,
                last_error=None if active else "sospeso dall'amministratore",
                audit="bot_resumed_admin" if active else "bot_suspended_admin",
            )
            await self.sync_runtime(updated)
        if manager is not None and updated is not None:
            verb = "riattivato" if active else "sospeso"
            await self._notify(
                manager,
                info.owner_tg_user_id,
                f"ℹ️ L'amministratore ha {verb} il tuo assistente {escape(info.mention)}.",
            )
        return updated or info

    async def reassign_owner(self, manager: Optional[Bot], info: BotInfo) -> BotInfo:
        """Conferma il passaggio di proprietà avvenuto su Telegram.

        Il nuovo proprietario deve aver collegato il suo account Telegram ad AION:
        il bot passa al suo utente AION e torna attivo.
        """
        new_tg = info.pending_owner_tg_user_id
        if new_tg is None:
            raise ValueError("no_pending_owner")
        link = await self.accounts.get_link_for_tg(new_tg)
        if link is None:
            raise ValueError("new_owner_not_linked")
        async with self._lock(info.bot_tg_id):
            updated = await self.bots.update(
                info.id,
                owner_tg_user_id=new_tg,
                owner_aion_user_id=link.aion_user_id,
                pending_owner_tg_user_id=None,
                status=BotStatus.ACTIVE,
                last_error=None,
                audit="bot_owner_reassigned",
                actor_tg_user_id=new_tg,
            )
            await self.sync_runtime(updated)
        if manager is not None and updated is not None:
            await self._notify(
                manager,
                new_tg,
                f"✅ L'assistente {escape(info.mention)} ora è tuo in AION. "
                "Gestiscilo da /mybots.",
            )
        return updated or info

    async def _notify(
        self, manager: Bot, chat_id: int, text: str, *, remove_keyboard: bool = False
    ) -> None:
        try:
            await manager.send_message(
                chat_id,
                text,
                reply_markup=ReplyKeyboardRemove() if remove_keyboard else None,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("telegram: notifica bot non inviata: %s", redact(e))
