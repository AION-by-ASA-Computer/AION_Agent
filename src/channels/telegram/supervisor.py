"""BotSupervisor: un long polling (o un webhook) per ogni bot personale attivo.

In ``delivery_mode = "webhook"`` ogni bot registra il proprio webhook invece di
tenere aperto ``getUpdates`` (vedi ``webhook.py``); il resto non cambia.

Ascoltare costa poco: ogni bot tiene aperta una richiesta ``getUpdates`` in attesa
(nessuna CPU, nessuna chiamata al modello). Il lavoro vero parte solo quando arriva
un messaggio e passa dalla coda condivisa di ``ChatService``.

Avvio/stop dinamico senza riavviare AION: ``ensure`` allinea il polling allo stato
del bot (solo ``active`` viene ascoltato). Un solo consumer per token in questo
processo; una seconda istanza di AION sullo stesso token riceve 409 e va in backoff.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from html import escape
from typing import Awaitable, Callable, Dict, Optional

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramUnauthorizedError

from src.channels.telegram.bots import BotInfo, BotStatus, TelegramBots, child_bot
from src.channels.telegram.config import TelegramSettings
from src.channels.telegram.webhook import (
    UpdateSource,
    WebhookReceiver,
    make_update_source,
    remove_webhook,
)
from src.channels.telegram.redact import redact

logger = logging.getLogger("aion.telegram")

_BOOT_RETRY_START_SEC = 2.0
_BOOT_RETRY_MAX_SEC = 60.0

Notify = Callable[[int, str], Awaitable[object]]


@dataclass
class _Runtime:
    info: BotInfo
    bot: Bot
    poller: UpdateSource
    stopping: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None


class BotSupervisor:
    def __init__(
        self,
        *,
        bots: TelegramBots,
        dispatcher: Dispatcher,
        settings: TelegramSettings,
        notify: Optional[Notify] = None,
        make_bot: Callable[[str, TelegramSettings], Bot] = child_bot,
    ) -> None:
        self.bots = bots
        self.dispatcher = dispatcher
        self.settings = settings
        self.notify = notify
        self._make_bot = make_bot
        self._runtimes: Dict[int, _Runtime] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    # ---------- stato ----------
    def is_running(self, bot_tg_id: int) -> bool:
        return bot_tg_id in self._runtimes

    @property
    def running(self) -> int:
        return len(self._runtimes)

    # ---------- comandi ----------
    async def start_all(self) -> None:
        """Avvio di AION: ascolta tutti i bot attivi del DB."""
        bots = await self.bots.list_active()
        for info in bots:
            await self.ensure(info)
        logger.info("telegram: %d bot personali in ascolto", self.running)

    async def ensure(self, info: BotInfo) -> None:
        """Ascolta il bot se è attivo, altrimenti ne ferma il polling."""
        async with self._lock:
            if info.status == BotStatus.ACTIVE.value and info.has_token:
                if info.bot_tg_id not in self._runtimes:
                    await self._start(info)
            else:
                await self._stop(info.bot_tg_id)

    async def restart(self, info: BotInfo) -> None:
        """Nuovo token: il polling riparte con quello aggiornato."""
        async with self._lock:
            await self._stop(info.bot_tg_id)
            if info.status == BotStatus.ACTIVE.value and info.has_token:
                await self._start(info)

    async def stop(self, bot_tg_id: int) -> None:
        async with self._lock:
            await self._stop(bot_tg_id)

    async def stop_all(self) -> None:
        async with self._lock:
            self._closed = True
            await asyncio.gather(
                *(self._stop(bot_id) for bot_id in list(self._runtimes)),
                return_exceptions=True,
            )

    # ---------- interni ----------
    async def _start(self, info: BotInfo) -> None:
        if self._closed:
            return
        limit = max(0, int(self.settings.max_running_bots))
        if len(self._runtimes) >= limit:
            logger.warning(
                "telegram: limite di %d bot in ascolto raggiunto, %s non avviato "
                "(max_running_bots, Admin → Telegram)",
                limit,
                info.mention,
            )
            return
        try:
            token = await self.bots.token_for(info.id)
        except Exception as e:  # noqa: BLE001 — chiave di cifratura cambiata
            await self._mark_error(info, f"token non decifrabile: {redact(e)}")
            return
        if not token:
            return
        bot = self._make_bot(token, self.settings)
        poller = make_update_source(
            bot,
            self.dispatcher,
            name=f"bot-{info.username or info.bot_tg_id}",
            token=token,
            settings=self.settings,
        )
        rt = _Runtime(info=info, bot=bot, poller=poller)
        self._runtimes[info.bot_tg_id] = rt
        rt.task = asyncio.create_task(
            self._run(rt), name=f"telegram-bot-{info.bot_tg_id}"
        )

    async def _stop(self, bot_tg_id: int) -> None:
        rt = self._runtimes.pop(bot_tg_id, None)
        if rt is None:
            return
        rt.stopping.set()
        await rt.poller.stop()
        # Webhook mode: a bot stopped while AION keeps running (suspended, deleted,
        # token replaced) must not keep receiving updates we no longer serve. On
        # AION shutdown (``_closed``) the webhook stays: Telegram queues the updates.
        if isinstance(rt.poller, WebhookReceiver) and not self._closed:
            await remove_webhook(rt.bot)
        if rt.task is not None and rt.task is not asyncio.current_task():
            try:
                await asyncio.wait_for(rt.task, timeout=5.0)
            except asyncio.TimeoutError:
                rt.task.cancel()
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await rt.bot.session.close()
        logger.info("telegram: bot %s non più in ascolto", rt.info.mention)

    async def _run(self, rt: _Runtime) -> None:
        unauthorized = False
        try:
            if not await self._bootstrap(rt):
                unauthorized = not rt.stopping.is_set()
            else:
                logger.info("telegram: bot %s in ascolto", rt.info.mention)
                await rt.poller.run()
                unauthorized = rt.poller.unauthorized
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(
                "telegram: polling del bot %s terminato: %s", rt.info.mention, redact(e)
            )
        if unauthorized and self._runtimes.get(rt.info.bot_tg_id) is rt:
            self._runtimes.pop(rt.info.bot_tg_id, None)
            await rt.bot.session.close()
            await self._mark_error(rt.info, "token rifiutato da Telegram (401)")

    async def _bootstrap(self, rt: _Runtime) -> bool:
        """In polling rimuove un eventuale webhook (lo escluderebbe). False su 401 o stop.

        In webhook mode non c'è nulla da fare qui: il receiver registra il webhook
        in ``poller.run()`` (e segnala il 401 con ``unauthorized``).
        """
        if self.settings.webhook_mode:
            return True
        delay = _BOOT_RETRY_START_SEC
        while not rt.stopping.is_set():
            try:
                await rt.bot.delete_webhook(drop_pending_updates=False)
                return True
            except TelegramUnauthorizedError:
                return False
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — rete/proxy: riprova
                logger.warning(
                    "telegram: avvio del bot %s fallito (%s), nuovo tentativo tra %.0fs",
                    rt.info.mention,
                    redact(e),
                    delay,
                )
                try:
                    await asyncio.wait_for(rt.stopping.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, _BOOT_RETRY_MAX_SEC)
        return False

    async def _mark_error(self, info: BotInfo, reason: str) -> None:
        current = await self.bots.get(info.id)
        if current is None or current.status != BotStatus.ACTIVE.value:
            # Eliminato o sospeso nel frattempo (es. 401 dopo la revoca del token).
            return
        logger.error("telegram: bot %s in errore: %s", info.mention, reason)
        await self.bots.update(
            info.id, status=BotStatus.ERROR, last_error=reason, audit="bot_error"
        )
        if self.notify is not None:
            await self.notify(
                info.owner_tg_user_id,
                f"⚠️ Il bot {escape(info.mention)} si è fermato: {escape(reason)}.\n"
                "Controllalo da /mybots.",
            )
