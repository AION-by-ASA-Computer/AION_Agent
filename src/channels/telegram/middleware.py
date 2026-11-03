"""Autorizzazione del bot manager: solo chat private, e chi non ha collegato
l'account Telegram ad AION può usare soltanto /start, /help, /whoami.

Il collegamento viene riletto a ogni messaggio (nessuna cache): uno scollegamento
dalla Chat UI ha effetto immediato.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.channels.telegram.redact import redact

logger = logging.getLogger("aion.telegram")

PUBLIC_COMMANDS = frozenset({"start", "help", "whoami"})

NOT_LINKED_TEXT = (
    "🔒 Questo account Telegram non è collegato ad AION.\n\n"
    "Apri la Chat UI → <b>Impostazioni → Telegram</b> e premi "
    "<b>Collega Telegram</b>."
)


def command_name(text: Optional[str]) -> Optional[str]:
    """``/start@bot pair_x`` → ``start``; None se non è un comando."""
    if not text or not text.startswith("/"):
        return None
    head = text[1:].split(maxsplit=1)[0] if len(text) > 1 else ""
    return head.split("@", 1)[0].lower() or None


class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery):
            chat = event.message.chat if event.message is not None else None
        else:
            return await handler(event, data)
        # Il bot manager lavora solo in chat privata (privacy mode attiva nei gruppi).
        if chat is None or chat.type != ChatType.PRIVATE or event.from_user is None:
            return None

        accounts = data["accounts"]
        user = event.from_user
        link = await accounts.get_link_for_tg(user.id)
        data["tg_link"] = link
        data["aion_user"] = None
        if link is not None:
            data["aion_user"] = await data["adapter"].resolve_user(link.aion_user_id)
            try:
                await accounts.touch(
                    link, tg_username=user.username, tg_first_name=user.first_name
                )
            except Exception as e:  # noqa: BLE001 — statistica, non deve bloccare
                logger.warning(
                    "telegram: aggiornamento last_seen fallito: %s", redact(e)
                )

        if data["aion_user"] is not None:
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            # Pulsanti di un messaggio vecchio dopo uno scollegamento.
            await event.answer("Account non collegato ad AION.", show_alert=True)
            return None
        if command_name(event.text) not in PUBLIC_COMMANDS:
            await event.answer(NOT_LINKED_TEXT)
            return None
        return await handler(event, data)
