"""Bootstrap del canale Telegram: bot manager (long polling o webhook) nel loop di AION."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import BotCommandScopeDefault

from src.channels.telegram import runtime
from src.channels.telegram.accounts import TelegramAccounts
from src.channels.telegram.adapter import AionAdapter, default_tenant_id
from src.channels.telegram.bots import BotFactory, TelegramBots
from src.channels.telegram.chat import ChatService
from src.channels.telegram.config import TelegramSettings, get_telegram_settings
from src.channels.telegram.handlers import (
    account,
    bots as bots_handlers,
    chat as chat_handlers,
    child as child_handlers,
    common,
)
from src.channels.telegram.handlers.child import ChildAccessMiddleware
from src.channels.telegram.middleware import AccessMiddleware
from src.channels.telegram.groups import GroupLog
from src.channels.telegram.webhook import make_update_source
from src.channels.telegram.supervisor import BotSupervisor
from src.channels.telegram.redact import install_log_redaction, redact

logger = logging.getLogger("aion.telegram")

_BOOT_RETRY_START_SEC = 2.0
_BOOT_RETRY_MAX_SEC = 60.0


def build_dispatcher(
    *,
    accounts: Optional[TelegramAccounts] = None,
    adapter: Optional[AionAdapter] = None,
    chat: Optional[ChatService] = None,
    settings: Optional[TelegramSettings] = None,
    bot_factory: Optional[BotFactory] = None,
) -> Dispatcher:
    dp = Dispatcher(name="telegram-manager")
    settings = settings or get_telegram_settings()
    adapter = adapter or AionAdapter()
    accounts = accounts or TelegramAccounts(tenant_id=default_tenant_id())
    # Servizi disponibili agli handler come argomenti (workflow_data di aiogram).
    dp["settings"] = settings
    dp["accounts"] = accounts
    dp["adapter"] = adapter
    dp["chat"] = chat or ChatService(settings=settings, adapter=adapter)
    dp["bot_factory"] = bot_factory or BotFactory(
        bots=TelegramBots(tenant_id=default_tenant_id()),
        accounts=accounts,
        adapter=adapter,
        settings=settings,
    )
    access = AccessMiddleware()
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    # Ordine: /start pair_<code> prima del /start generico; il wizard /newbot
    # prima della chat (il nome del bot non va all'agente); il testo libero
    # (chat) prima del fallback di common.
    dp.include_router(account.build_router())
    dp.include_router(bots_handlers.build_router())
    if settings.manager_chat:
        dp.include_router(chat_handlers.build_router())
    else:
        # Il manager non chatta: il testo libero riceve un orientamento.
        dp.include_router(bots_handlers.build_guide_router())
    dp.include_router(common.build_router())
    return dp


def build_child_dispatcher(
    *,
    accounts: TelegramAccounts,
    adapter: AionAdapter,
    chat: ChatService,
    bots: TelegramBots,
    group_log: Optional[GroupLog] = None,
) -> Dispatcher:
    """Dispatcher unico per tutti i bot personali; condivide la coda dei turni."""
    dp = Dispatcher(name="telegram-children")
    dp["accounts"] = accounts
    dp["adapter"] = adapter
    dp["chat"] = chat
    dp["bots"] = bots
    dp["group_log"] = group_log or GroupLog()
    access = ChildAccessMiddleware()
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    dp.include_router(child_handlers.build_router())
    return dp


class TelegramGateway:
    """Avvia/ferma il bot manager. ``start`` non blocca: la rete viene usata solo
    nel task in background, così l'avvio di AION non dipende da api.telegram.org."""

    def __init__(self, settings: TelegramSettings) -> None:
        token = settings.manager_token_value
        if not token:
            raise ValueError("token del bot manager non configurato (Admin → Telegram)")
        self.settings = settings
        session = (
            AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else None
        )
        self.bot = Bot(
            token=token,
            session=session,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML, link_preview_is_disabled=True
            ),
        )
        self.dispatcher = build_dispatcher(settings=settings)
        factory: BotFactory = self.dispatcher["bot_factory"]
        self.supervisor = BotSupervisor(
            bots=factory.bots,
            dispatcher=build_child_dispatcher(
                accounts=self.dispatcher["accounts"],
                adapter=self.dispatcher["adapter"],
                chat=self.dispatcher["chat"],
                bots=factory.bots,
            ),
            settings=settings,
            notify=self.notify,
        )
        factory.supervisor = self.supervisor
        # Long poller or webhook receiver, per Admin → Telegram "delivery_mode";
        # both expose run()/stop(), so the rest of the gateway does not care.
        self.poller = make_update_source(
            self.bot, self.dispatcher, name="manager", token=token, settings=settings
        )
        self._task: Optional[asyncio.Task] = None
        self._reconcile_task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()
        # Noto dopo getMe: serve per i link t.me/<username>?start=pair_<code>.
        self.bot_username: Optional[str] = None

    async def notify(self, tg_user_id: int, text: str) -> bool:
        """Messaggio informativo all'utente; un errore (bot bloccato, rete) non è fatale."""
        try:
            await self.bot.send_message(tg_user_id, text)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("telegram: notifica non inviata: %s", redact(e))
            return False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="telegram-gateway")

    async def stop(self) -> None:
        self._stopping.set()
        if self._reconcile_task is not None:
            self._reconcile_task.cancel()
        # Prima i turni dell'agente (avvisano l'utente), poi il polling.
        await self.dispatcher["chat"].shutdown()
        await self.supervisor.stop_all()
        await self.poller.stop()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            except asyncio.CancelledError:
                pass
            except Exception as e:  # noqa: BLE001
                logger.warning("telegram: chiusura gateway: %s", redact(e))
        await self.bot.session.close()
        if runtime.get_gateway() is self:
            runtime.set_gateway(None)
        logger.info("telegram: gateway fermato")

    async def _run(self) -> None:
        if not await self._bootstrap():
            return
        try:
            await self.supervisor.start_all()
        except Exception as e:  # noqa: BLE001 — DB: il manager funziona comunque
            logger.error("telegram: avvio dei bot personali fallito: %s", redact(e))
        if self.settings.reconcile_interval_min > 0:
            self._reconcile_task = asyncio.create_task(
                self._reconcile_loop(), name="telegram-reconcile"
            )
        await self.poller.run()

    async def _reconcile_loop(self) -> None:
        """Ogni ``reconcile_interval_min`` (Admin → Telegram) controlla tutti gli assistenti."""
        interval = self.settings.reconcile_interval_min * 60
        factory: BotFactory = self.dispatcher["bot_factory"]
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await factory.reconcile(self.bot)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — si riprova al prossimo giro
                logger.warning("telegram: riconciliazione fallita: %s", redact(e))

    async def _bootstrap(self) -> bool:
        """getMe + setMyCommands con retry: False se il token è invalido o se si sta fermando."""
        delay = _BOOT_RETRY_START_SEC
        while not self._stopping.is_set():
            try:
                # Polling e webhook si escludono: in polling rimuove un eventuale
                # webhook senza scartare gli update in coda (drop_pending_updates=False);
                # in webhook mode lo registra il receiver in ``poller.run()``.
                if not self.settings.webhook_mode:
                    await self.bot.delete_webhook(drop_pending_updates=False)
                me = await self.bot.get_me()
                self.bot_username = me.username
                factory = self.dispatcher["bot_factory"]
                factory.manager_username = me.username
                factory.can_manage_bots = bool(me.can_manage_bots)
                logger.info(
                    "telegram: bot manager @%s (id=%s) can_manage_bots=%s",
                    me.username,
                    me.id,
                    bool(me.can_manage_bots),
                )
                if not me.can_manage_bots:
                    logger.warning(
                        "telegram: @%s non ha la gestione bot abilitata: attivare "
                        "'Bot Management Mode' nella Mini App di @BotFather (pulsante Open) "
                        "per creare i bot personali con /newbot",
                        me.username,
                    )
                await self.bot.set_my_commands(
                    common.manager_commands(self.settings),
                    scope=BotCommandScopeDefault(),
                )
                return True
            except TelegramUnauthorizedError:
                logger.error(
                    "telegram: token del bot manager rifiutato da Telegram (401): "
                    "gateway non avviato (correggerlo da Admin → Telegram)"
                )
                return False
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — rete/proxy: riprova
                logger.warning(
                    "telegram: avvio fallito (%s: %s), nuovo tentativo tra %.0fs",
                    type(e).__name__,
                    redact(e),
                    delay,
                )
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, _BOOT_RETRY_MAX_SEC)
        return False


async def start_gateway(settings: TelegramSettings) -> Optional[TelegramGateway]:
    install_log_redaction()
    try:
        gateway = TelegramGateway(settings)
    except Exception as e:  # noqa: BLE001 — token mancante o malformato
        logger.error("telegram: gateway non avviato: %s", redact(e))
        return None
    runtime.set_gateway(gateway)
    await gateway.start()
    logger.info(
        "telegram: gateway avviato (%s)",
        "webhook" if settings.webhook_mode else "long polling",
    )
    return gateway
