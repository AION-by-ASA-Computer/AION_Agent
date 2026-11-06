"""Stato per chat Telegram: conversazione AION corrente, profilo e progetto scelti.

Chiave ``(bot_id, chat_id, thread_id, tg_user_id)`` come da piano. Se l'account
Telegram viene ricollegato a un altro utente AION, la riga riparte da zero: le
conversazioni dell'utente precedente non vengono mai riusate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.channels.telegram.models import TgSession
from src.data.engine import get_async_session_maker

_UNSET: Any = object()


@dataclass(frozen=True)
class ChatSession:
    id: int
    aion_user_id: str
    conversation_id: Optional[str]
    profile_slug: Optional[str]
    project_slug: Optional[str]


def _snapshot(row: TgSession) -> ChatSession:
    return ChatSession(
        id=row.id,
        aion_user_id=row.aion_user_id,
        conversation_id=row.conversation_id,
        profile_slug=row.profile_slug,
        project_slug=row.project_slug,
    )


class TelegramSessions:
    def __init__(self, session_maker: Optional[Callable[[], Any]] = None) -> None:
        self._session_maker = session_maker

    def _session(self):
        return (self._session_maker or get_async_session_maker())()

    async def get_or_create(
        self,
        *,
        bot_id: int,
        chat_id: int,
        tg_user_id: int,
        aion_user_id: str,
        thread_id: Optional[int] = None,
    ) -> ChatSession:
        key = dict(
            bot_id=bot_id,
            chat_id=chat_id,
            thread_id=thread_id or 0,
            tg_user_id=tg_user_id,
        )
        async with self._session() as session:
            row = (
                await session.execute(select(TgSession).filter_by(**key))
            ).scalar_one_or_none()
            if row is None:
                row = TgSession(
                    **key,
                    aion_user_id=aion_user_id,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(row)
            elif row.aion_user_id != aion_user_id:
                row.aion_user_id = aion_user_id
                row.conversation_id = None
                row.profile_slug = None
                row.project_slug = None
                row.updated_at = datetime.now(timezone.utc)
            else:
                return _snapshot(row)
            try:
                await session.commit()
            except IntegrityError:
                # Due messaggi simultanei della stessa chat: vince il primo insert.
                await session.rollback()
                row = (
                    await session.execute(select(TgSession).filter_by(**key))
                ).scalar_one()
            return _snapshot(row)

    async def update(
        self,
        session_id: int,
        *,
        conversation_id: Any = _UNSET,
        profile_slug: Any = _UNSET,
        project_slug: Any = _UNSET,
    ) -> ChatSession:
        async with self._session() as session:
            row = await session.get(TgSession, session_id)
            if row is None:
                raise LookupError(f"tg_session {session_id} not found")
            if conversation_id is not _UNSET:
                row.conversation_id = conversation_id
            if profile_slug is not _UNSET:
                row.profile_slug = profile_slug
            if project_slug is not _UNSET:
                row.project_slug = project_slug
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return _snapshot(row)
