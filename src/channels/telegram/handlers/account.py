"""Collegamento account: /start pair_<code>, /me, /unlink."""

from __future__ import annotations

import logging
from html import escape
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from src.channels.telegram.accounts import (
    PAIR_PREFIX,
    LinkInfo,
    RedeemStatus,
    TelegramAccounts,
)
from src.channels.telegram.adapter import AionAdapter, AionUserRef
from src.channels.telegram.bots import BotFactory
from src.channels.telegram.config import TelegramSettings
from src.channels.telegram.handlers.common import linked_hint
from src.channels.telegram.redact import redact

logger = logging.getLogger("aion.telegram")

SETTINGS_HINT = "Chat UI → <b>Impostazioni → Telegram</b>"

REDEEM_ERRORS = {
    RedeemStatus.INVALID: (
        f"❌ Link di collegamento non valido.\n\nGenerane uno nuovo da {SETTINGS_HINT}."
    ),
    RedeemStatus.EXPIRED: (
        f"⌛ Link di collegamento scaduto.\n\nGenerane uno nuovo da {SETTINGS_HINT}."
    ),
    RedeemStatus.USED: (
        "❌ Questo link è già stato usato.\n\n"
        f"Se serve, generane uno nuovo da {SETTINGS_HINT}."
    ),
    RedeemStatus.TG_LINKED_TO_OTHER: (
        "⚠️ Questo account Telegram è già collegato a un altro utente AION.\n\n"
        "Usa /unlink per scollegarlo, poi apri di nuovo il link."
    ),
}


def _format_date(link: LinkInfo) -> str:
    return link.created_at.strftime("%d/%m/%Y") if link.created_at else "—"


async def cmd_start_pair(
    message: Message,
    command: CommandObject,
    accounts: TelegramAccounts,
    adapter: AionAdapter,
    settings: Optional[TelegramSettings] = None,
    bot_factory: Optional[BotFactory] = None,
) -> None:
    user = message.from_user
    code = (command.args or "")[len(PAIR_PREFIX) :]
    status, link = await accounts.redeem_pairing_code(
        code,
        tg_user_id=user.id,
        tg_username=user.username,
        tg_first_name=user.first_name,
    )
    if status is not RedeemStatus.LINKED or link is None:
        await message.answer(REDEEM_ERRORS[status])
        return
    aion_user = await adapter.resolve_user(link.aion_user_id)
    who = escape(aion_user.label) if aion_user else "—"
    resumed = []
    if bot_factory is not None:
        try:
            resumed = await bot_factory.resume_after_link(link.aion_user_id, user.id)
        except Exception as e:  # noqa: BLE001 — il collegamento è già avvenuto
            logger.warning("telegram: riattivazione assistenti fallita: %s", redact(e))
    await message.answer(
        f"✅ Account collegato all'utente AION <b>{who}</b>.\n\n"
        + linked_hint(settings)
        + resumed_note(resumed)
    )


async def cmd_me(
    message: Message, tg_link: Optional[LinkInfo], aion_user: Optional[AionUserRef]
) -> None:
    if tg_link is None or aion_user is None:
        return
    lines = [
        f"👤 Collegato ad AION come <b>{escape(aion_user.label)}</b>",
        f"Utente: <code>{escape(aion_user.identifier)}</code>",
        f"Collegato dal: {_format_date(tg_link)}",
    ]
    await message.answer("\n".join(lines))


def suspended_note(bots: list) -> str:
    if not bots:
        return ""
    names = ", ".join(escape(b.mention) for b in bots)
    return (
        f"\n\n⏸️ Assistenti sospesi: {names}. Tornano attivi quando ricolleghi "
        "questo account Telegram."
    )


def resumed_note(bots: list) -> str:
    if not bots:
        return ""
    names = ", ".join(escape(b.mention) for b in bots)
    return f"\n\n▶️ Assistenti di nuovo attivi: {names}."


async def cmd_unlink(
    message: Message,
    accounts: TelegramAccounts,
    tg_link: Optional[LinkInfo],
    bot_factory: Optional[BotFactory] = None,
) -> None:
    if tg_link is None:
        return
    await accounts.unlink(tg_user_id=tg_link.tg_user_id, source="telegram")
    suspended = []
    if bot_factory is not None:
        try:
            suspended = await bot_factory.suspend_for_unlink(tg_link.aion_user_id)
        except Exception as e:  # noqa: BLE001 — lo scollegamento è già avvenuto
            logger.warning("telegram: sospensione assistenti fallita: %s", redact(e))
    await message.answer(
        "🔓 Account scollegato da AION.\n\n"
        f"Per ricollegarlo genera un nuovo link da {SETTINGS_HINT}."
        + suspended_note(suspended)
    )


def build_router() -> Router:
    router = Router(name="telegram-account")
    router.message.register(
        cmd_start_pair,
        CommandStart(deep_link=True, magic=F.args.startswith(PAIR_PREFIX)),
    )
    router.message.register(cmd_me, Command("me"))
    router.message.register(cmd_unlink, Command("unlink"))
    return router
