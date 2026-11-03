"""Tabelle del canale Telegram nel DB unificato di AION.

``DeclarativeBase`` separato: il canale non estende ``src/data/models.py`` e
``migrations/env.py`` (``include_object``) non tocca queste tabelle in autogenerate.

Due vie di creazione, stesso schema:
- installazioni esistenti: migrazioni ``a9b0c1d029_telegram_links`` e successive;
- DB nuovi: AION fa ``create_all`` del core e poi ``alembic stamp head`` (le
  migrazioni non girano), quindi ``ensure_schema`` crea le tabelle mancanti
  all'avvio del canale.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TelegramBase(DeclarativeBase):
    pass


# Riferimento a ``users`` (tabella del core) solo per le FK: non viene mai creata da qui.
_USERS_REF = Table(
    "users", TelegramBase.metadata, Column("id", String(64), primary_key=True)
)
_USER_FK = "users.id"


class TgLink(TelegramBase):
    """Account Telegram collegato a un utente AION (al massimo uno per lato)."""

    __tablename__ = "tg_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    aion_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(_USER_FK, ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    tg_username: Mapped[Optional[str]] = mapped_column(String(64))
    tg_first_name: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class TgPairingCode(TelegramBase):
    """Codice monouso di collegamento: nel DB solo lo SHA-256, mai il codice."""

    __tablename__ = "tg_pairing_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    aion_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(_USER_FK, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    used_by_tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)


class TgAudit(TelegramBase):
    __tablename__ = "tg_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    aion_user_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[Optional[str]] = mapped_column(Text)


class TgSession(TelegramBase):
    """Chat Telegram → conversazione AION corrente (cambia con /new).

    ``thread_id`` vale 0 fuori dai topic: con NULL l'UNIQUE di SQLite non varrebbe.
    """

    __tablename__ = "tg_sessions"
    __table_args__ = (
        UniqueConstraint(
            "bot_id", "chat_id", "thread_id", "tg_user_id", name="uq_tg_sessions_key"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    thread_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    aion_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey(_USER_FK, ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[Optional[str]] = mapped_column(String(64))
    profile_slug: Mapped[Optional[str]] = mapped_column(String(128))
    project_slug: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class TgBot(TelegramBase):
    """Bot personale creato dal manager (managed bot) e la sua configurazione.

    ``token_enc``: token cifrato con ``AION_CREDENTIAL_ENCRYPTION_KEY`` (mai in chiaro);
    NULL dopo l'eliminazione. ``status``: provisioning | active | suspended | error | deleted.
    """

    __tablename__ = "tg_bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_aion_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey(_USER_FK, ondelete="CASCADE"), nullable=False, index=True
    )
    owner_tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bot_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    name: Mapped[Optional[str]] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="managed")
    # personal: solo il proprietario; shared: tutti gli utenti AION collegati, anche nei gruppi.
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="personal", server_default="personal"
    )
    profile_slug: Mapped[Optional[str]] = mapped_column(String(128))
    project_slug: Mapped[Optional[str]] = mapped_column(String(128))
    token_enc: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Account Telegram a cui il bot è passato (sospeso finché un admin non conferma).
    pending_owner_tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    # Ultimo messaggio gestito (aggiornato al massimo una volta al minuto).
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class TgPendingCreation(TelegramBase):
    """Richiesta /newbot in attesa che l'utente confermi la creazione in Telegram.

    Una per account Telegram: ``ManagedBotCreated`` non riporta il ``request_id``,
    quindi il bot creato viene associato tramite il proprietario.
    """

    __tablename__ = "tg_pending_creations"

    owner_tg_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_aion_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey(_USER_FK, ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="personal", server_default="personal"
    )
    profile_slug: Mapped[Optional[str]] = mapped_column(String(128))
    project_slug: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class TgUserQuota(TelegramBase):
    """Quota di assistenti personalizzata per un utente AION (Admin → Telegram)."""

    __tablename__ = "tg_user_quotas"

    aion_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey(_USER_FK, ondelete="CASCADE"), primary_key=True
    )
    max_bots: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class TgGroupMessage(TelegramBase):
    """Domande rivolte a un assistente condiviso in un gruppo e sue risposte.

    È il contesto comune del gruppo: ogni domanda gira con l'identità AION di chi
    la fa (conversazione sua), e le domande degli altri arrivano all'agente da qui.
    """

    __tablename__ = "tg_group_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    author: Mapped[str] = mapped_column(String(128), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


Index(
    "ix_tg_group_messages_chat",
    TgGroupMessage.bot_id,
    TgGroupMessage.chat_id,
    TgGroupMessage.id,
)


def add_audit(
    session, action: str, *, aion_user_id=None, tg_user_id=None, **payload
) -> None:
    session.add(
        TgAudit(
            action=action,
            aion_user_id=aion_user_id,
            actor_tg_user_id=tg_user_id,
            payload_json=json.dumps(payload) if payload else None,
        )
    )


CHANNEL_TABLES = (
    TgLink.__table__,
    TgPairingCode.__table__,
    TgAudit.__table__,
    TgSession.__table__,
    TgBot.__table__,
    TgPendingCreation.__table__,
    TgGroupMessage.__table__,
    TgUserQuota.__table__,
)

# Colonne aggiunte dopo la creazione delle tabelle: (tabella, colonna, DDL).
_ADDED_COLUMNS = (
    ("tg_bots", "mode", "VARCHAR(16) NOT NULL DEFAULT 'personal'"),
    ("tg_pending_creations", "mode", "VARCHAR(16) NOT NULL DEFAULT 'personal'"),
    ("tg_bots", "pending_owner_tg_user_id", "BIGINT"),
    ("tg_bots", "last_activity_at", "TIMESTAMP"),
)


def _add_missing_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    for table, column, ddl in _ADDED_COLUMNS:
        if not insp.has_table(table):
            continue
        if column not in {c["name"] for c in insp.get_columns(table)}:
            sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def ensure_schema() -> None:
    """Crea le tabelle del canale se mancano (idempotente, ``checkfirst``)."""
    from src.data.engine import init_engine

    engine = init_engine()
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: TelegramBase.metadata.create_all(
                sync_conn, tables=list(CHANNEL_TABLES), checkfirst=True
            )
        )
        # Tabelle create da una versione precedente del canale.
        await conn.run_sync(_add_missing_columns)
