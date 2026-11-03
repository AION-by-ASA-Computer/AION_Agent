"""Contesto comune degli assistenti condivisi nei gruppi.

Ogni domanda in un gruppo gira con l'identità AION di chi la fa (conversazione
sua). Perché l'assistente sappia cosa si è detto nel gruppo, le domande rivolte
all'assistente e le sue risposte finiscono in ``tg_group_messages``; a ogni nuova
domanda l'agente riceve, prima della domanda, quelle fatte dagli *altri*
partecipanti dopo l'ultima domanda di chi scrive (le proprie sono già nella sua
conversazione).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from sqlalchemy import delete, select

from src.channels.telegram.models import TgGroupMessage
from src.data.engine import get_async_session_maker

KEEP_PER_CHAT = 50
CONTEXT_ENTRIES = 8
_QUESTION_CHARS = 600
_ANSWER_CHARS = 800
_STORED_ANSWER_CHARS = 4000


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class GroupLog:
    def __init__(self, session_maker: Optional[Callable[[], Any]] = None) -> None:
        self._session_maker = session_maker

    def _session(self):
        maker = self._session_maker or get_async_session_maker()
        return maker()

    async def add(
        self,
        *,
        bot_id: int,
        chat_id: int,
        tg_user_id: int,
        author: str,
        question: str,
        answer: str,
    ) -> None:
        async with self._session() as session:
            session.add(
                TgGroupMessage(
                    bot_id=bot_id,
                    chat_id=chat_id,
                    tg_user_id=tg_user_id,
                    author=author[:128],
                    question=question,
                    answer=answer[:_STORED_ANSWER_CHARS],
                )
            )
            await session.flush()
            # Tiene solo le ultime KEEP_PER_CHAT voci del gruppo.
            ids = (
                (
                    await session.execute(
                        select(TgGroupMessage.id)
                        .where(
                            TgGroupMessage.bot_id == bot_id,
                            TgGroupMessage.chat_id == chat_id,
                        )
                        .order_by(TgGroupMessage.id.desc())
                        .offset(KEEP_PER_CHAT)
                    )
                )
                .scalars()
                .all()
            )
            if ids:
                await session.execute(
                    delete(TgGroupMessage).where(TgGroupMessage.id.in_(ids))
                )
            await session.commit()

    async def context_for(
        self, *, bot_id: int, chat_id: int, tg_user_id: int
    ) -> list[TgGroupMessage]:
        """Domande degli altri dopo l'ultima di ``tg_user_id`` (al massimo
        CONTEXT_ENTRIES, dalla più vecchia alla più recente)."""
        async with self._session() as session:
            last_own = (
                await session.execute(
                    select(TgGroupMessage.id)
                    .where(
                        TgGroupMessage.bot_id == bot_id,
                        TgGroupMessage.chat_id == chat_id,
                        TgGroupMessage.tg_user_id == tg_user_id,
                    )
                    .order_by(TgGroupMessage.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            rows = (
                (
                    await session.execute(
                        select(TgGroupMessage)
                        .where(
                            TgGroupMessage.bot_id == bot_id,
                            TgGroupMessage.chat_id == chat_id,
                            TgGroupMessage.tg_user_id != tg_user_id,
                            TgGroupMessage.id > (last_own or 0),
                        )
                        .order_by(TgGroupMessage.id.desc())
                        .limit(CONTEXT_ENTRIES)
                    )
                )
                .scalars()
                .all()
            )
        return list(reversed(rows))


def group_prompt(
    entries: list[TgGroupMessage], *, chat_title: Optional[str], author: str
) -> str:
    """Prefisso della domanda per l'agente: dove siamo, cosa si è detto, chi chiede."""
    where = f"chat di gruppo «{chat_title}»" if chat_title else "chat di gruppo"
    lines = [f"[Messaggio da una {where} su Telegram. La risposta è visibile a tutti.]"]
    if entries:
        lines.append(
            "[Domande fatte all'assistente da altri partecipanti dopo il tuo "
            "ultimo messaggio:]"
        )
        for e in entries:
            lines.append(f"{e.author}: {_clip(e.question, _QUESTION_CHARS)}")
            lines.append(f"Assistente: {_clip(e.answer, _ANSWER_CHARS)}")
    lines.append(f"[Domanda di {author}:]")
    return "\n".join(lines) + "\n"
