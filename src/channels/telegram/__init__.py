"""Canale Telegram per AION (bot manager + managed bots).

Vedi ``docs/telegram/AION_MAP.md``. Attivo solo con ``AION_TELEGRAM_ENABLED=1``:
con il flag spento non viene importato nulla di aiogram.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Optional

from src.channels.telegram.config import (
    TelegramSettings,
    get_telegram_settings,
)

if TYPE_CHECKING:
    from src.channels.telegram.gateway import TelegramGateway

logger = logging.getLogger("aion.telegram")

_ENV_PREFIX = "AION_TELEGRAM_"


def warn_misconfigured_env(settings: TelegramSettings) -> None:
    """Segnala nomi di variabili sconosciuti (es. ``AION_TELEGRAM_ENABLE``) e il
    token presente con flag spento: senza questo il canale resta muto. Solo nomi, mai valori."""
    known = {_ENV_PREFIX + name.upper() for name in TelegramSettings.model_fields}
    unknown = sorted(
        k
        for k in os.environ
        if k.upper().startswith(_ENV_PREFIX) and k.upper() not in known
    )
    if unknown:
        logger.warning(
            "telegram: variabili sconosciute ignorate: %s (valide: %s)",
            ", ".join(unknown),
            ", ".join(sorted(known)),
        )
    if not settings.enabled and settings.manager_token_value:
        logger.warning(
            "telegram: AION_TELEGRAM_MANAGER_TOKEN configurato ma AION_TELEGRAM_ENABLED "
            "non attivo: gateway spento"
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
    """Riapplica le variabili ``AION_TELEGRAM_*`` senza riavviare AION (impostazioni
    admin fuori da Docker): ferma il gateway attivo e lo riavvia con i nuovi valori."""
    from src.channels.telegram import runtime

    async with _restart_lock:
        current = runtime.get_gateway()
        if current is not None:
            await current.stop()
        get_telegram_settings.cache_clear()
        gateway = await start_gateway_if_enabled()
        logger.info(
            "telegram: impostazioni riapplicate (gateway %s)",
            "attivo" if gateway is not None else "spento",
        )
        return gateway


async def start_gateway_if_enabled() -> Optional["TelegramGateway"]:
    """Punto di aggancio per il lifespan di AION. None se disattivato o non avviabile."""
    settings = get_telegram_settings()
    warn_misconfigured_env(settings)
    if not settings.enabled:
        return None
    from src.channels.telegram.models import ensure_schema

    await ensure_schema()
    from src.channels.telegram.gateway import start_gateway

    return await start_gateway(settings)
