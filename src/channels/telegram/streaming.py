"""Risposta dell'agente su Telegram mentre viene generata.

Due modalità di anteprima, scelte da sole:
- **draft** (chat private, Bot API ``sendMessageDraft`` / ``sendRichMessageDraft``):
  anteprima animata ed effimera (~30 s, va rinnovata) con il pulsante di stop
  nativo (``can_stop``), poi il messaggio finale;
- **edit**: un messaggio inviato e poi modificato ogni ``interval``; usata nei
  gruppi e se Telegram rifiuta i draft.

Formato: **rich** (``sendRichMessage``, Markdown in stile GitHub: tabelle vere,
codice con linguaggio, titoli, sezioni richiudibili) quando il bot lo supporta,
altrimenti l'HTML di Telegram (``formatting.markdown_to_html``). Un rifiuto del
formato rich lo disattiva per quel bot; un testo che Telegram non riesce a leggere
ricade sull'HTML solo per quel messaggio.

Gli aggiornamenti sono raggruppati da un task che scrive al massimo una volta per
intervallo (limite Telegram ~1 messaggio/s per chat).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from html import escape
from typing import Optional

from aiogram import Bot
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import InputRichMessage, ReplyParameters

from src.channels.telegram.formatting import (
    markdown_to_html,
    preview_markdown,
    split_markdown,
    strip_html,
)
from src.channels.telegram.redact import redact

logger = logging.getLogger("aion.telegram")

# Un draft scompare dopo ~30 s senza aggiornamenti: lo si rinnova prima.
_DRAFT_KEEPALIVE_SEC = 10.0
# "sta scrivendo…" dura ~5 s.
_TYPING_EVERY_SEC = 4.5
# Limite Telegram dei messaggi rich (32768 caratteri), con margine per il footer.
RICH_LIMIT = 30000


class DraftSupport:
    """Esito condiviso per bot: dopo il primo rifiuto non si riprova."""

    def __init__(self) -> None:
        self.enabled: Optional[bool] = None


# Stesso meccanismo per i messaggi rich.
RichSupport = DraftSupport


async def _call(coro_factory, *, retries: int = 2):
    """Chiamata Bot API con attesa su 429 (RetryAfter)."""
    for attempt in range(retries + 1):
        try:
            return await coro_factory()
        except TelegramRetryAfter as e:
            if attempt == retries:
                raise
            await asyncio.sleep(min(float(e.retry_after), 30.0))


def _is_not_modified(e: Exception) -> bool:
    return "message is not modified" in str(e).lower()


def _is_parse_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "can't parse" in msg or "unsupported start tag" in msg


def _rich_status(status_html: str) -> str:
    """Riga di stato (HTML) come blocco citato in Markdown per le anteprime rich."""
    lines = [line for line in strip_html(status_html).splitlines() if line.strip()]
    return "\n".join(f"> {line}" for line in lines)


def reasoning_block(reasoning: str, *, limit: int = 3000) -> Optional[str]:
    """Ragionamento del modello come sezione richiudibile (HTML ammesso nel rich)."""
    text = (reasoning or "").strip()
    if not text:
        return None
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return (
        "<details><summary>💭 Ragionamento</summary>"
        f"<blockquote>{escape(text)}</blockquote></details>"
    )


class ReplyRenderer:
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        *,
        draft_support: DraftSupport,
        rich_support: Optional[RichSupport] = None,
        interval_sec: float = 1.0,
        thread_id: Optional[int] = None,
        private_chat: bool = True,
        reply_to: Optional[int] = None,
    ) -> None:
        self.bot = bot
        # Nei gruppi la risposta cita la domanda (solo il primo messaggio inviato).
        self._reply_to = reply_to
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.interval = max(0.3, float(interval_sec))
        self._draft_support = draft_support
        self._use_draft = private_chat and draft_support.enabled is not False
        # None = formato rich disattivato da configurazione.
        self._rich_support = rich_support
        self.draft_id = random.randint(1, 2**31 - 1)
        self._text = ""
        self._status: Optional[str] = None
        self._dirty = False
        self._shown = ""
        self._last_send = 0.0
        self._last_typing = 0.0
        self._message_id: Optional[int] = None
        # L'anteprima nella modalità edit è un messaggio rich: in HTML non si modifica.
        self._message_is_rich = False
        self._task: Optional[asyncio.Task] = None
        self._closed = False

    @property
    def _rich(self) -> bool:
        return (
            self._rich_support is not None and self._rich_support.enabled is not False
        )

    def _disable_rich(self, e: Exception) -> None:
        if self._rich_support is None:
            return
        if self._rich_support.enabled is None:
            logger.info(
                "telegram: messaggi rich non disponibili (%s): uso l'HTML", redact(e)
            )
        self._rich_support.enabled = False

    # ---------- ciclo di vita ----------
    async def start(self) -> None:
        await self._show_waiting()
        self._task = asyncio.create_task(
            self._loop(), name=f"telegram-render-{self.chat_id}"
        )

    def update(self, text: str) -> None:
        self._text = text
        self._dirty = True

    def set_status(self, status: Optional[str]) -> None:
        if status != self._status:
            self._status = status
            self._dirty = True

    async def finish(
        self,
        text: str,
        *,
        footer: Optional[str] = None,
        rich_header: Optional[str] = None,
    ) -> None:
        """Testo finale (Markdown); ``footer`` è HTML. ``rich_header`` (HTML) compare
        solo nel formato rich, prima della risposta (es. ragionamento richiudibile,
        come nella Chat UI)."""
        await self._stop_loop()
        if self._rich and await self._finish_rich(text, footer, rich_header):
            return
        chunks = [markdown_to_html(c) for c in split_markdown(text)] or [""]
        if footer:
            sep = "\n\n" if chunks[-1] else ""
            chunks[-1] = f"{chunks[-1]}{sep}{footer}"
        if not chunks[0]:
            chunks[0] = "<i>(nessuna risposta)</i>"
        await self._drop_rich_preview()
        first = True
        for html in chunks:
            if first and self._message_id is not None:
                await self._edit(html)
            else:
                await self._send(html)
            first = False

    async def fail(self, html: str) -> None:
        await self._stop_loop()
        partial = self._text.strip()
        body = (
            f"{markdown_to_html(preview_markdown(partial))}\n\n{html}"
            if partial
            else html
        )
        await self._drop_rich_preview()
        if self._message_id is not None:
            await self._edit(body)
        else:
            await self._send(body)

    async def _drop_rich_preview(self) -> None:
        """Ripiego HTML dopo un'anteprima rich: si invia un messaggio nuovo e si
        toglie l'anteprima (un messaggio rich non diventa testo con una modifica)."""
        if self._message_id is None or not self._message_is_rich:
            return
        old, self._message_id, self._message_is_rich = self._message_id, None, False
        try:
            await self.bot.delete_message(self.chat_id, old)
        except TelegramAPIError:
            pass

    async def close(self) -> None:
        await self._stop_loop()

    # ---------- interni ----------
    async def _stop_loop(self) -> None:
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self.interval)
            try:
                now = time.monotonic()
                if self._dirty:
                    self._dirty = False
                    await self._render()
                elif self._use_draft and now - self._last_send > _DRAFT_KEEPALIVE_SEC:
                    await self._render(force=True)
                if not self._text and now - self._last_typing > _TYPING_EVERY_SEC:
                    await self._typing()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — l'anteprima non deve fermare il turno
                logger.warning("telegram: anteprima non aggiornata: %s", redact(e))

    def _preview_html(self) -> str:
        body = (
            markdown_to_html(preview_markdown(self._text)) if self._text.strip() else ""
        )
        if self._status:
            status = f"<i>{self._status}</i>"
            body = f"{body}\n\n{status}" if body else status
        return body

    def _preview_markdown(self) -> str:
        body = preview_markdown(self._text) if self._text.strip() else ""
        if self._status:
            status = _rich_status(self._status)
            body = f"{body}\n\n{status}" if body else status
        return body

    async def _show_waiting(self) -> None:
        if self._use_draft:
            # Testo vuoto = segnaposto "Sto pensando…" nativo di Telegram.
            if await self._draft(""):
                return
        await self._typing()

    async def _render(self, force: bool = False) -> None:
        html = self._preview_html()
        if not html or (html == self._shown and not force):
            return
        if self._use_draft:
            if self._rich and await self._draft_rich(self._preview_markdown()):
                self._shown = html
                return
            if await self._draft(html):
                self._shown = html
                return
        if self._rich and await self._show_rich(self._preview_markdown()):
            self._shown = html
            return
        await self._drop_rich_preview()
        if self._message_id is None:
            await self._send(html, keep_id=True)
        else:
            await self._edit(html)
        self._shown = html

    # ---------- draft ----------
    async def _draft(self, html: str) -> bool:
        try:
            await _call(
                lambda: self.bot.send_message_draft(
                    chat_id=self.chat_id,
                    draft_id=self.draft_id,
                    text=html,
                    message_thread_id=self.thread_id,
                    parse_mode=ParseMode.HTML,
                    can_stop=True,
                )
            )
            self._draft_support.enabled = True
            self._last_send = time.monotonic()
            return True
        except TelegramBadRequest as e:
            if _is_parse_error(e):
                return False  # questo testo non è HTML valido: lo gestirà l'edit/plain
            self._disable_draft(e)
            return False
        except TelegramAPIError as e:
            self._disable_draft(e)
            return False

    async def _draft_rich(self, markdown: str) -> bool:
        try:
            await _call(
                lambda: self.bot.send_rich_message_draft(
                    chat_id=self.chat_id,
                    draft_id=self.draft_id,
                    rich_message=InputRichMessage(markdown=markdown),
                    message_thread_id=self.thread_id,
                    can_stop=True,
                )
            )
            self._rich_support.enabled = True
            self._last_send = time.monotonic()
            return True
        except TelegramBadRequest as e:
            if not _is_parse_error(e):
                self._disable_rich(e)
            return False
        except TelegramAPIError as e:
            self._disable_rich(e)
            return False

    def _disable_draft(self, e: Exception) -> None:
        if self._draft_support.enabled is None:
            logger.info(
                "telegram: sendMessageDraft non disponibile (%s): streaming con modifica del messaggio",
                redact(e),
            )
        self._draft_support.enabled = False
        self._use_draft = False

    async def _typing(self) -> None:
        self._last_typing = time.monotonic()
        try:
            await self.bot.send_chat_action(
                self.chat_id, ChatAction.TYPING, message_thread_id=self.thread_id
            )
        except TelegramAPIError:
            pass

    # ---------- rich ----------
    async def _show_rich(self, markdown: str) -> bool:
        """Anteprima rich nella modalità edit (invio o modifica del messaggio)."""
        if not markdown.strip() or len(markdown) > RICH_LIMIT:
            return False
        return await self._put_rich(markdown, keep_id=True)

    async def _finish_rich(
        self, text: str, footer: Optional[str], header: Optional[str]
    ) -> bool:
        parts = [header] if header else []
        parts.append(text.strip() or "_(nessuna risposta)_")
        if footer:
            parts.append(footer)
        markdown = "\n\n".join(parts)
        if len(markdown) > RICH_LIMIT:
            return False  # troppo lungo: l'HTML lo divide in più messaggi
        return await self._put_rich(markdown, keep_id=False)

    async def _put_rich(self, markdown: str, *, keep_id: bool) -> bool:
        rich = InputRichMessage(markdown=markdown)
        try:
            if self._message_id is not None:
                await _call(
                    lambda: self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self._message_id,
                        rich_message=rich,
                    )
                )
            else:
                reply = self._reply_parameters()
                msg = await _call(
                    lambda: self.bot.send_rich_message(
                        chat_id=self.chat_id,
                        rich_message=rich,
                        message_thread_id=self.thread_id,
                        reply_parameters=reply,
                    )
                )
                self._reply_to = None
                if keep_id:
                    self._message_id = msg.message_id
                    self._message_is_rich = True
        except TelegramBadRequest as e:
            if _is_not_modified(e):
                return True
            if not _is_parse_error(e):
                self._disable_rich(e)
            return False
        except TelegramAPIError as e:
            self._disable_rich(e)
            return False
        self._rich_support.enabled = True
        self._last_send = time.monotonic()
        return True

    # ---------- HTML ----------
    def _reply_parameters(self) -> Optional[ReplyParameters]:
        if not self._reply_to:
            return None
        return ReplyParameters(
            message_id=self._reply_to, allow_sending_without_reply=True
        )

    async def _send(self, html: str, *, keep_id: bool = False) -> None:
        reply = self._reply_parameters()

        async def send(text: str, mode: Optional[str]):
            return await _call(
                lambda: self.bot.send_message(
                    self.chat_id,
                    text,
                    parse_mode=mode,
                    message_thread_id=self.thread_id,
                    reply_parameters=reply,
                )
            )

        try:
            msg = await send(html, ParseMode.HTML)
        except TelegramBadRequest as e:
            if not _is_parse_error(e):
                raise
            msg = await send(strip_html(html), None)
        self._last_send = time.monotonic()
        self._reply_to = None
        if keep_id:
            self._message_id = msg.message_id

    async def _edit(self, html: str) -> None:
        async def edit(text: str, mode: Optional[str]):
            return await _call(
                lambda: self.bot.edit_message_text(
                    text=text,
                    chat_id=self.chat_id,
                    message_id=self._message_id,
                    parse_mode=mode,
                )
            )

        try:
            await edit(html, ParseMode.HTML)
        except TelegramBadRequest as e:
            if _is_not_modified(e):
                return
            if not _is_parse_error(e):
                raise
            try:
                await edit(strip_html(html), None)
            except TelegramBadRequest as e2:
                if not _is_not_modified(e2):
                    raise
        self._last_send = time.monotonic()
