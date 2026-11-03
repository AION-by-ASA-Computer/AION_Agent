"""Coda dei turni dell'agente avviati da Telegram.

AION non limita le chiamate parallele al modello (AION_MAP § 11): con un modello
locale due turni insieme rallentano entrambi. Qui un semaforo FIFO globale
(``AION_TELEGRAM_MAX_CONCURRENT_JOBS``) e un lock per conversazione: due messaggi
rapidi nella stessa chat vengono eseguiti uno dopo l'altro, mai in parallelo.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable, Dict, List, Optional

QueuedCallback = Callable[[int], Awaitable[None]]


class JobQueue:
    def __init__(self, max_concurrent: int = 1) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self._sem = asyncio.Semaphore(self.max_concurrent)
        self._waiting: List[object] = []
        self._chat_locks: Dict[str, asyncio.Lock] = {}
        # Turni (in corso o in attesa) per chat: a zero il lock viene rimosso.
        self._chat_refs: Dict[str, int] = {}

    @property
    def waiting(self) -> int:
        return len(self._waiting)

    def chat_busy(self, key: str) -> bool:
        lock = self._chat_locks.get(key)
        return lock is not None and lock.locked()

    @asynccontextmanager
    async def slot(
        self, chat_key: str, *, on_queued: Optional[QueuedCallback] = None
    ) -> AsyncIterator[None]:
        """Attende il turno della chat e poi un posto libero; ``on_queued(posizione)``
        viene chiamato una volta se bisogna aspettare."""
        lock = self._chat_locks.setdefault(chat_key, asyncio.Lock())
        self._chat_refs[chat_key] = self._chat_refs.get(chat_key, 0) + 1
        ticket = object()
        try:
            if lock.locked() or self._sem.locked():
                self._waiting.append(ticket)
                if on_queued is not None:
                    await on_queued(len(self._waiting))
            try:
                await lock.acquire()
                try:
                    await self._sem.acquire()
                except BaseException:
                    lock.release()
                    raise
            finally:
                if ticket in self._waiting:
                    self._waiting.remove(ticket)
            try:
                yield
            finally:
                self._sem.release()
                lock.release()
        finally:
            self._chat_refs[chat_key] -= 1
            if self._chat_refs[chat_key] == 0:
                self._chat_refs.pop(chat_key, None)
                self._chat_locks.pop(chat_key, None)
