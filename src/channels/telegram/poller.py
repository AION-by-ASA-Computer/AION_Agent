"""Long polling di un singolo bot con conferma dell'offset solo a update gestiti.

Perché non ``Dispatcher.start_polling`` di aiogram: aiogram avanza l'offset appena
legge un update, quindi allo stop gli update ancora in lavorazione risultano già
confermati (persi) e l'ultimo batch gestito non viene mai confermato (duplicati al
riavvio). Qui l'offset inviato a Telegram non supera mai il più vecchio update
ancora in corso, e allo shutdown un ``getUpdates`` finale conferma esattamente
quelli completati. Lo stesso poller servirà al BotSupervisor (un poller per token).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramConflictError, TelegramUnauthorizedError
from aiogram.types import Update

from src.channels.telegram.redact import redact

logger = logging.getLogger("aion.telegram")

_BACKOFF_START_SEC = 1.0
_BACKOFF_MAX_SEC = 30.0
# Con update in corso Telegram risponde subito (ci sono update non confermati):
# tra due poll "a vuoto" si aspetta il primo handler che termina, al massimo questo.
_INFLIGHT_RECHECK_SEC = 1.0


class UpdatePoller:
    def __init__(
        self,
        bot: Bot,
        dispatcher: Dispatcher,
        *,
        name: str,
        polling_timeout: int = 50,
        shutdown_grace_sec: float = 10.0,
        allowed_updates: Optional[List[str]] = None,
    ) -> None:
        self.bot = bot
        self.dispatcher = dispatcher
        self.name = name
        self.polling_timeout = max(0, int(polling_timeout))
        self.shutdown_grace_sec = max(0.0, float(shutdown_grace_sec))
        self.allowed_updates = allowed_updates
        self.unauthorized = False
        self._inflight: Dict[int, asyncio.Task] = {}
        self._seen_max: Optional[int] = None
        self._last_sent_offset: Optional[int] = None
        self._stopping = asyncio.Event()

    # ---------- offset ----------
    def next_offset(self) -> Optional[int]:
        """Il più vecchio update in corso, altrimenti il successivo all'ultimo visto."""
        if self._inflight:
            return min(self._inflight)
        if self._seen_max is None:
            return None
        return self._seen_max + 1

    # ---------- loop ----------
    async def run(self) -> None:
        backoff = _BACKOFF_START_SEC
        while not self._stopping.is_set():
            try:
                updates = await self._get_updates_interruptible()
            except TelegramUnauthorizedError:
                self.unauthorized = True
                logger.error(
                    "telegram[%s]: token non valido (401), polling fermato", self.name
                )
                break
            except TelegramConflictError as e:
                logger.warning(
                    "telegram[%s]: conflitto 409 (altra istanza in polling sullo stesso token?): %s",
                    self.name,
                    redact(e),
                )
                await self._sleep_or_stop(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX_SEC)
                continue
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — rete/5xx: riprova con backoff
                logger.warning(
                    "telegram[%s]: getUpdates fallito (%s: %s), nuovo tentativo tra %.0fs",
                    self.name,
                    type(e).__name__,
                    redact(e),
                    backoff,
                )
                await self._sleep_or_stop(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX_SEC)
                continue

            if updates is None:  # stop richiesto durante il long poll
                break
            backoff = _BACKOFF_START_SEC
            started = self._dispatch(updates)
            if self._inflight and not started:
                await self._wait_inflight_progress()

    async def stop(self) -> None:
        """Ferma il polling, attende gli handler (grace) e conferma l'offset."""
        self._stopping.set()
        if self._inflight:
            done, pending = await asyncio.wait(
                list(self._inflight.values()), timeout=self.shutdown_grace_sec or None
            )
            if pending:
                logger.warning(
                    "telegram[%s]: %d update ancora in corso allo shutdown: "
                    "non confermati, verranno riconsegnati al riavvio",
                    self.name,
                    len(pending),
                )
        offset = self.next_offset()
        for task in list(self._inflight.values()):
            task.cancel()
        if self.unauthorized or offset is None:
            return
        if self._last_sent_offset is not None and offset <= self._last_sent_offset:
            return
        try:
            # timeout=0: conferma gli update < offset senza attendere; quelli
            # restituiti (>= offset) restano non confermati per il prossimo avvio.
            await self.bot.get_updates(offset=offset, limit=1, timeout=0)
            self._last_sent_offset = offset
            logger.info("telegram[%s]: offset confermato allo shutdown", self.name)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "telegram[%s]: conferma offset allo shutdown fallita: %s",
                self.name,
                redact(e),
            )

    # ---------- interni ----------
    async def _get_updates_interruptible(self) -> Optional[List[Update]]:
        offset = self.next_offset()
        timeout = 0 if self._inflight else self.polling_timeout
        poll = asyncio.create_task(
            self.bot.get_updates(
                offset=offset,
                timeout=timeout,
                allowed_updates=self.allowed_updates,
                request_timeout=timeout + 10,
            )
        )
        stop = asyncio.create_task(self._stopping.wait())
        try:
            await asyncio.wait({poll, stop}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop.cancel()
        if not poll.done():
            # Lo stop interrompe il long poll: la richiesta portava già `offset`,
            # quindi sul server non è stato confermato nulla oltre l'invariante.
            poll.cancel()
            try:
                await poll
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            return None
        self._last_sent_offset = offset
        return poll.result()

    def _dispatch(self, updates: List[Update]) -> int:
        started = 0
        for update in updates:
            uid = update.update_id
            if self._seen_max is not None and uid <= self._seen_max:
                continue  # già in corso o già gestito
            self._seen_max = uid
            self._inflight[uid] = asyncio.create_task(
                self._handle(update), name=f"telegram-{self.name}-update-{uid}"
            )
            started += 1
        return started

    async def _handle(self, update: Update) -> None:
        try:
            await self.dispatcher.feed_update(self.bot, update)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — un update rotto non deve fermare il bot
            logger.error(
                "telegram[%s]: errore gestendo update %s: %s",
                self.name,
                update.update_id,
                redact(e),
            )
        finally:
            self._inflight.pop(update.update_id, None)

    async def _wait_inflight_progress(self) -> None:
        stop = asyncio.create_task(self._stopping.wait())
        try:
            await asyncio.wait(
                [*self._inflight.values(), stop],
                timeout=_INFLIGHT_RECHECK_SEC,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            stop.cancel()

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
