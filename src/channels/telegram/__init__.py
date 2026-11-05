"""Canale Telegram per AION (bot manager + managed bots).

Vedi ``docs/telegram/AION_MAP.md``. The configuration lives only in the DB
(``settings_store``, edited from Admin → Telegram): the channel is active when it
is enabled there; with it off nothing of aiogram is imported.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Optional

from src.channels.telegram.config import get_telegram_settings

if TYPE_CHECKING:
    from src.channels.telegram.gateway import TelegramGateway

logger = logging.getLogger("aion.telegram")

_ENV_PREFIX = "AION_TELEGRAM_"


def warn_ignored_env() -> None:
    """Warn when ``AION_TELEGRAM_*`` variables are still set in the environment.

    The channel no longer reads them (configuration is in the DB, Admin →
    Telegram): without this an old ``.env`` would silently look effective.
    Names only, never values.
    """
    ignored = sorted(k for k in os.environ if k.upper().startswith(_ENV_PREFIX))
    if ignored:
        logger.warning(
            "telegram: variabili d'ambiente ignorate: %s (la configurazione del "
            "canale si gestisce solo da Admin → Telegram)",
            ", ".join(ignored),
        )


async def _channel_tables_exist() -> bool:
    from sqlalchemy import inspect

    from src.data.engine import init_engine

    async with init_engine().connect() as conn:
        return await conn.run_sync(lambda c: inspect(c).has_table("tg_bots"))


async def lifecycle_factory():
    """``(BotFactory, bot manager)`` per le operazioni sul ciclo di vita.

    Con il gateway attivo è quello del gateway (polling e revoca dei token);
    altrimenti una factory solo-DB e ``None`` come manager (niente revoca).
    """
    from src.channels.telegram import runtime

    gateway = runtime.get_gateway()
    if gateway is not None:
        return gateway.dispatcher["bot_factory"], gateway.bot
    from src.channels.telegram.accounts import TelegramAccounts
    from src.channels.telegram.adapter import AionAdapter, default_tenant_id
    from src.channels.telegram.bots import BotFactory, TelegramBots

    tenant = default_tenant_id()
    factory = BotFactory(
        bots=TelegramBots(tenant_id=tenant),
        accounts=TelegramAccounts(tenant_id=tenant),
        adapter=AionAdapter(),
        settings=get_telegram_settings(),
    )
    return factory, None


async def on_user_deleted(aion_user_id: str) -> int:
    """Prima di eliminare un utente AION: revoca i token dei suoi assistenti, ne
    ferma l'ascolto e rimuove collegamento, sessioni e codici. Ritorna i bot revocati."""
    if not get_telegram_settings().enabled and not await _channel_tables_exist():
        return 0  # canale mai usato: nessuna tabella, niente aiogram
    factory, manager = await lifecycle_factory()
    revoked = await factory.purge_user(manager, aion_user_id)
    logger.info(
        "telegram: utente %s eliminato, %d assistenti revocati", aion_user_id, revoked
    )
    return revoked


_restart_lock = asyncio.Lock()


async def restart_gateway() -> Optional["TelegramGateway"]:
    """Apply the configuration saved from Admin → Telegram without restarting AION:
    stop the running gateway and start it again with the values reloaded from the
    DB (also after ``AION_CREDENTIAL_ENCRYPTION_KEY`` changes)."""
    from src.channels.telegram import runtime

    async with _restart_lock:
        current = runtime.get_gateway()
        if current is not None:
            await current.stop()
        gateway = await start_gateway_if_enabled()
        logger.info(
            "telegram: impostazioni riapplicate (gateway %s)",
            "attivo" if gateway is not None else "spento",
        )
        return gateway


async def start_gateway_if_enabled() -> Optional["TelegramGateway"]:
    """Punto di aggancio per il lifespan di AION. None se disattivato o non avviabile.

    Loads the configuration from the DB first, so ``get_telegram_settings()`` is
    current for the gateway and for the API even when the channel is off.
    """
    from src.channels.telegram.settings_store import reload_telegram_settings

    warn_ignored_env()
    settings = await reload_telegram_settings()
    if not settings.enabled:
        return None
    from src.channels.telegram.models import ensure_schema

    await ensure_schema()
    from src.channels.telegram.gateway import start_gateway

    return await start_gateway(settings)
