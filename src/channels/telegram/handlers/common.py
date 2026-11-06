"""Comandi comuni: /start, /help, /whoami ed errore globale."""

from __future__ import annotations

import logging
from html import escape
from typing import Optional

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, ErrorEvent, Message

from src.channels.telegram.adapter import AionUserRef
from src.channels.telegram.chat import UNSUPPORTED_TEXT
from src.channels.telegram.config import TelegramSettings
from src.channels.telegram.middleware import NOT_LINKED_TEXT
from src.channels.telegram.redact import redact

logger = logging.getLogger("aion.telegram")

_CHAT_COMMANDS = [
    BotCommand(command="new", description="Nuova conversazione con AION"),
    BotCommand(command="profile", description="Scegli il profilo dell'agente"),
    BotCommand(command="project", description="Scegli il progetto"),
    BotCommand(command="stop", description="Interrompi la risposta in corso"),
]
_BOT_COMMANDS = [
    BotCommand(command="newbot", description="Crea un assistente personale"),
    BotCommand(command="mybots", description="I tuoi assistenti personali"),
]
_ACCOUNT_COMMANDS = [
    BotCommand(command="start", description="Avvia il bot"),
    BotCommand(command="help", description="Elenco dei comandi"),
    BotCommand(command="me", description="Mostra l'utente AION collegato"),
    BotCommand(command="unlink", description="Scollega questo account da AION"),
    BotCommand(command="whoami", description="Mostra il tuo Telegram user id"),
]

_CHAT_HELP = (
    "<b>Chat con AION</b>\n"
    "/new — nuova conversazione\n"
    "/profile — scegli il profilo dell'agente\n"
    "/project — scegli il progetto\n"
    "/stop — interrompi la risposta in corso\n\n"
)
_BOTS_HELP = (
    "<b>Assistenti personali</b>\n"
    "/newbot — crea un assistente con il suo profilo e progetto\n"
    "/mybots — i tuoi assistenti: apri, modifica, sospendi, elimina\n"
    "/cancel — annulla la creazione in corso\n\n"
)
_ACCOUNT_HELP = (
    "<b>Account</b>\n"
    "/start — avvia il bot\n"
    "/help — questo elenco\n"
    "/me — utente AION collegato\n"
    "/unlink — scollega questo account da AION\n"
    "/whoami — mostra il tuo Telegram user id"
)
# Il manager gestisce account e assistenti; si chatta con gli assistenti personali.
_MANAGER_ROLE = (
    "Qui gestisci il collegamento ad AION e i tuoi assistenti personali: "
    "per chattare con l'agente si usa un assistente."
)


def _chat_enabled(settings: Optional[TelegramSettings]) -> bool:
    return bool(settings and settings.manager_chat)


def manager_commands(settings: Optional[TelegramSettings]) -> list[BotCommand]:
    """Menu del bot manager (setMyCommands)."""
    chat = _CHAT_COMMANDS if _chat_enabled(settings) else []
    return [*chat, *_BOT_COMMANDS, *_ACCOUNT_COMMANDS]


def help_text(settings: Optional[TelegramSettings]) -> str:
    if _chat_enabled(settings):
        return (
            "Scrivimi una domanda: risponde l'agente AION.\n\n"
            + _CHAT_HELP
            + _BOTS_HELP
            + _ACCOUNT_HELP
        )
    return _MANAGER_ROLE + "\n\n" + _BOTS_HELP + _ACCOUNT_HELP


def linked_hint(settings: Optional[TelegramSettings]) -> str:
    """Cosa fare dopo il collegamento (nessun passo obbligatorio)."""
    if _chat_enabled(settings):
        return "Scrivimi una domanda per chattare con l'agente, /help per i comandi."
    return (
        "Quando vuoi, crea un assistente personale con /newbot; "
        "/mybots elenca quelli che hai. /help per tutti i comandi."
    )


async def cmd_start(
    message: Message,
    aion_user: Optional[AionUserRef] = None,
    settings: Optional[TelegramSettings] = None,
) -> None:
    name = escape(message.from_user.first_name) if message.from_user else ""
    greeting = f"Ciao {name}! " if name else "Ciao! "
    if aion_user is None:
        await message.answer(
            f"{greeting}Sono il bot di <b>AION</b>.\n\n{NOT_LINKED_TEXT}"
        )
        return
    await message.answer(
        f"{greeting}Sono il bot di <b>AION</b>.\n\n"
        f"Sei collegato come <b>{escape(aion_user.label)}</b>.\n"
        + linked_hint(settings)
    )


async def cmd_help(
    message: Message, settings: Optional[TelegramSettings] = None
) -> None:
    await message.answer(help_text(settings))


async def cmd_whoami(message: Message) -> None:
    user = message.from_user
    if user is None:
        await message.answer(
            "Non riesco a identificare il mittente di questo messaggio."
        )
        return
    lines = [f"Il tuo Telegram user id: <code>{user.id}</code>"]
    if user.username:
        lines.append(f"Username: @{escape(user.username)}")
    lines.append(f"Chat id: <code>{message.chat.id}</code>")
    await message.answer("\n".join(lines))


async def fallback_private(
    message: Message, settings: Optional[TelegramSettings] = None
) -> None:
    # Raggiunto solo da utenti collegati (il middleware blocca gli altri) e solo
    # per ciò che la chat non gestisce: comandi sconosciuti e messaggi non testuali.
    if message.text and message.text.startswith("/"):
        await message.answer("Comando sconosciuto. Usa /help per l'elenco.")
        return
    if not _chat_enabled(settings):
        await message.answer(
            "Sono il bot di gestione di AION: qui non rispondo ai messaggi. "
            "/mybots per i tuoi assistenti, /help per i comandi."
        )
        return
    await message.answer(UNSUPPORTED_TEXT)


async def on_error(event: ErrorEvent) -> bool:
    logger.error(
        "telegram: errore non gestito nell'update %s: %s: %s",
        event.update.update_id,
        type(event.exception).__name__,
        redact(event.exception),
    )
    message = event.update.message
    if message is not None:
        try:
            await message.answer(
                "⚠️ Si è verificato un errore interno. Riprova più tardi."
            )
        except Exception:  # noqa: BLE001 — anche l'invio può fallire (rete, chat bloccata)
            pass
    return True


def build_router() -> Router:
    """Router nuovo a ogni chiamata: un Router aiogram si collega a un solo
    Dispatcher, e ogni bot (manager e, in futuro, figli) ha il suo."""
    router = Router(name="telegram-common")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_whoami, Command("whoami"))
    # Ultimo: qualsiasi altro messaggio in chat privata.
    router.message.register(fallback_private, F.chat.type == ChatType.PRIVATE)
    router.errors.register(on_error)
    return router
