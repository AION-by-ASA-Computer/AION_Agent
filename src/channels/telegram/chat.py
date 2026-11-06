"""Chat con l'agente AION da Telegram: un turno per messaggio.

L'handler aiogram non aspetta il turno (può durare minuti): lo avvia in un task e
ritorna subito, così il poller conferma l'update e il bot resta reattivo a /stop.
Il prezzo è che un crash del processo durante il turno perde quella risposta;
allo shutdown ordinato i turni in corso vengono fermati e l'utente avvisato.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from html import escape
from typing import Awaitable, Callable, Dict, Optional, Sequence, Tuple

from aiogram import Bot

from src.channels.telegram.adapter import (
    AionAdapter,
    AionUserRef,
    ChannelPolicyError,
    ChatAccessError,
    Error,
    Final,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolResult,
)
from src.channels.session_turn import collect_new_outputs, snapshot_outputs
from src.channels.telegram import outputs
from src.channels.telegram.config import TelegramSettings
from src.channels.telegram.queue import JobQueue
from src.channels.telegram.redact import redact
from src.channels.telegram.sessions import ChatSession, TelegramSessions
from src.channels.telegram.streaming import (
    DraftSupport,
    ReplyRenderer,
    RichSupport,
    reasoning_block,
)

logger = logging.getLogger("aion.telegram")


@dataclass(frozen=True)
class ChatTarget:
    """Dove arriva il messaggio: bot, chat (ed eventuale topic) e mittente."""

    bot_id: int
    chat_id: int
    tg_user_id: int
    thread_id: Optional[int] = None

    @property
    def key(self) -> str:
        return f"{self.bot_id}:{self.chat_id}:{self.thread_id or 0}:{self.tg_user_id}"


@dataclass(frozen=True)
class TurnConfig:
    """Configurazione fissata dal bot (bot personali): prevale su quella della chat.

    ``profile_slug`` None = profilo di default del canale.
    """

    profile_slug: Optional[str]
    project_slug: Optional[str]
    metadata: Optional[dict] = None
    # Gruppi: niente anteprima animata (solo chat private) e risposta che cita la domanda.
    private_chat: bool = True
    reply_to: Optional[int] = None
    # Testo anteposto alla domanda solo per l'agente (es. contesto del gruppo).
    prompt_prefix: Optional[str] = None
    # Chiamata con la risposta finale riuscita (es. registro del gruppo).
    on_answer: Optional[Callable[[str], Awaitable[None]]] = None
    # Utente AION (identifier) i cui permessi valgono per il progetto: assistenti
    # condivisi nei gruppi, dove l'accesso lo concede il creatore.
    project_user: Optional[str] = None


# Telegram: i bot scaricano file fino a 20 MB (Bot API cloud).
MAX_FILE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class IncomingFile:
    """Allegato ricevuto su Telegram, scaricato solo quando parte il turno."""

    name: str
    size: Optional[int]
    load: Callable[[], Awaitable[bytes]]


VOICE_TEXT = (
    "🎤 Non posso ascoltare i messaggi vocali: scrivi la domanda.\n"
    "Con Telegram Premium puoi trascrivere il vocale e incollarne il testo."
)
UNSUPPORTED_TEXT = (
    "Posso leggere messaggi di testo, documenti e foto. "
    "Questo tipo di messaggio non è supportato."
)


def incoming_file(message, bot: Bot) -> Optional[IncomingFile]:
    """Documento o foto (la risoluzione più alta) del messaggio, se presente."""
    if message.document is not None:
        doc = message.document
        file_id, size = doc.file_id, doc.file_size
        name = doc.file_name or f"documento_{message.message_id}"
    elif message.photo:
        photo = message.photo[-1]
        file_id, size = photo.file_id, photo.file_size
        name = f"foto_{message.message_id}.jpg"
    else:
        return None

    async def load() -> bytes:
        return (await bot.download(file_id)).read()

    return IncomingFile(name=name, size=size, load=load)


# File ricevuti senza domanda: aspettano il messaggio successivo per questo tempo.
PENDING_FILES_TTL_SEC = 15 * 60
# Gli album arrivano come messaggi separati: si raccolgono per questo intervallo.
ALBUM_WAIT_SEC = 1.2

# (testo della domanda, file, messaggio che porta la domanda)
SubmitFiles = Callable[[str, list, object], Awaitable[None]]
AckFiles = Callable[[list], Awaitable[None]]


def files_label(files: Sequence[IncomingFile]) -> str:
    names = ", ".join(f.name for f in files[:3])
    return names + (f" e altri {len(files) - 3}" if len(files) > 3 else "")


def files_ack_text(files: Sequence[IncomingFile]) -> str:
    if len(files) == 1:
        head = f"📎 Ricevuto «{escape(files[0].name)}»."
        what = "il file"
    else:
        head = f"📎 Ricevuti {len(files)} file ({escape(files_label(files))})."
        what = "i file"
    return f"{head}\nOra scrivi cosa vuoi che faccia con {what}."


@dataclass
class _PendingBatch:
    files: list
    updated: float
    album: Optional[str] = None
    caption: str = ""
    caption_message: object = None
    timer: Optional[asyncio.Task] = None


class PendingFiles:
    """Allegati in attesa della domanda, per chat (e persona nei gruppi).

    Telegram su Android invia i documenti senza far scrivere una didascalia: il
    file viene confermato e allegato al messaggio di testo successivo. Gli album
    (più foto insieme) arrivano come messaggi separati con lo stesso
    ``media_group_id`` e la didascalia su uno solo: si raccolgono prima di decidere.
    In memoria: un riavvio di AION dimentica i file non ancora usati.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._items: Dict[str, _PendingBatch] = {}
        self._now = now

    def _get(self, key: str) -> Optional[_PendingBatch]:
        batch = self._items.get(key)
        if batch is not None and self._now() - batch.updated > PENDING_FILES_TTL_SEC:
            self._drop(key)
            return None
        return batch

    def _drop(self, key: str) -> Optional[_PendingBatch]:
        batch = self._items.pop(key, None)
        if batch is not None and batch.timer is not None:
            if batch.timer is not asyncio.current_task():
                batch.timer.cancel()
            batch.timer = None
        return batch

    def take(self, key: str) -> list:
        """File in attesa (svuota): da allegare alla domanda appena arrivata."""
        if self._get(key) is None:
            return []
        return self._drop(key).files

    def clear(self, key: str) -> None:
        self._drop(key)

    async def receive(
        self,
        key: str,
        message,
        file: IncomingFile,
        question: str,
        *,
        submit: SubmitFiles,
        ack: AckFiles,
    ) -> None:
        question = (question or "").strip()
        album = getattr(message, "media_group_id", None)
        batch = self._get(key)
        if album is None:
            if question:
                await submit(question, self.take(key) + [file], message)
                return
            if batch is None:
                batch = self._items[key] = _PendingBatch(files=[], updated=self._now())
            batch.files.append(file)
            batch.updated = self._now()
            await ack(list(batch.files))
            return
        if batch is None:
            batch = self._items[key] = _PendingBatch(files=[], updated=self._now())
        batch.album = album
        batch.files.append(file)
        batch.updated = self._now()
        if question and not batch.caption:
            batch.caption, batch.caption_message = question, message
        if batch.timer is not None:
            batch.timer.cancel()
        batch.timer = asyncio.create_task(self._flush_album(key, batch, submit, ack))

    async def _flush_album(
        self, key: str, batch: _PendingBatch, submit: SubmitFiles, ack: AckFiles
    ) -> None:
        await asyncio.sleep(ALBUM_WAIT_SEC)
        if self._items.get(key) is not batch:
            return
        batch.timer = None
        if batch.caption:
            files = self.take(key)
            await submit(batch.caption, files, batch.caption_message)
            return
        batch.album = None  # i file successivi si aggiungono a questo lotto
        await ack(list(batch.files))


def tool_label(name: str) -> str:
    """``mcp_server__tool_name`` → ``tool_name`` per la riga di stato."""
    return name.rsplit("__", 1)[-1] or name


class ToolActivity:
    """Tool chiamati nel turno, mostrati come nella Chat UI.

    Restano visibili anche quando durano pochi millisecondi: una riga di stato
    temporanea verrebbe cancellata prima del successivo aggiornamento dell'anteprima.
    """

    MAX_LINES = 12
    _ICON = {None: "⏳", True: "✓", False: "✗"}

    def __init__(self) -> None:
        self._calls: list[
            list
        ] = []  # [call_id, nome, esito: None=in corso / True / False]

    def __bool__(self) -> bool:
        return bool(self._calls)

    def start(self, event: ToolCall) -> None:
        self._calls.append([event.call_id, tool_label(event.name), None])

    def finish(self, event: ToolResult) -> None:
        label = tool_label(event.name)
        for call in reversed(self._calls):
            same = call[0] == event.call_id if event.call_id else call[1] == label
            if same and call[2] is None:
                call[2] = event.ok
                return

    def _lines(self) -> list[str]:
        lines = [f"{self._ICON[ok]} {escape(name)}" for _, name, ok in self._calls]
        hidden = len(lines) - self.MAX_LINES
        if hidden > 0:
            lines = [f"… altri {hidden}"] + lines[-self.MAX_LINES :]
        return lines

    def live_html(self) -> Optional[str]:
        """Righe per l'anteprima in streaming (il renderer le mette in corsivo)."""
        return "🔧 " + "\n".join(self._lines()) if self._calls else None

    def summary_html(self) -> Optional[str]:
        """Riquadro richiudibile in fondo alla risposta finale."""
        if not self._calls:
            return None
        body = "\n".join(self._lines())
        return (
            f"<blockquote expandable>🔧 Strumenti usati ({len(self._calls)})\n"
            f"{body}</blockquote>"
        )


class ChatService:
    def __init__(
        self,
        *,
        settings: TelegramSettings,
        adapter: Optional[AionAdapter] = None,
        sessions: Optional[TelegramSessions] = None,
        queue: Optional[JobQueue] = None,
    ) -> None:
        self.settings = settings
        self.adapter = adapter or AionAdapter()
        self.sessions = sessions or TelegramSessions()
        self.queue = queue or JobQueue(settings.max_concurrent_jobs)
        # sendMessageDraft: esito per bot (manager e bot personali possono differire).
        self._drafts: Dict[int, DraftSupport] = {}
        self._rich: Dict[int, RichSupport] = {}
        self._tasks: Dict[asyncio.Task, ChatTarget] = {}
        self._running: Dict[str, str] = {}  # chat key -> conversation_id in corso
        # (bot, chat, draft_id) -> chat key: il pulsante di stop riporta solo il draft.
        self._by_draft: Dict[Tuple[int, int, int], str] = {}
        # Allegati arrivati senza domanda, in attesa del messaggio successivo.
        self.pending = PendingFiles()

    def draft_support_for(self, bot_id: int) -> DraftSupport:
        support = self._drafts.get(bot_id)
        if support is None:
            support = self._drafts[bot_id] = DraftSupport()
        return support

    def rich_support_for(self, bot_id: int) -> Optional[RichSupport]:
        if not self.settings.rich_messages:
            return None
        support = self._rich.get(bot_id)
        if support is None:
            support = self._rich[bot_id] = RichSupport()
        return support

    # ---------- stato della chat ----------
    async def session_for(self, target: ChatTarget, user: AionUserRef) -> ChatSession:
        return await self.sessions.get_or_create(
            bot_id=target.bot_id,
            chat_id=target.chat_id,
            thread_id=target.thread_id,
            tg_user_id=target.tg_user_id,
            aion_user_id=user.row_id,
        )

    async def current_profile(self, state: ChatSession, user: AionUserRef) -> str:
        return await self.adapter.resolve_profile(
            user, state.profile_slug or self.settings.default_profile
        )

    async def new_conversation(
        self, target: ChatTarget, user: AionUserRef
    ) -> ChatSession:
        state = await self.session_for(target, user)
        return await self.sessions.update(state.id, conversation_id=None)

    def is_running(self, target: ChatTarget) -> bool:
        return target.key in self._running

    async def stop(self, target: ChatTarget) -> bool:
        cid = self._running.get(target.key)
        if cid is None:
            return False
        await self.adapter.cancel(cid)
        return True

    async def stop_draft(self, bot_id: int, chat_id: int, draft_id: int) -> bool:
        """Pulsante di stop sull'anteprima (update ``stopped_message_generation``)."""
        key = self._by_draft.get((bot_id, chat_id, draft_id))
        cid = self._running.get(key) if key else None
        if cid is None:
            return False
        await self.adapter.cancel(cid)
        return True

    # ---------- turno ----------
    def submit(
        self,
        bot: Bot,
        target: ChatTarget,
        user: AionUserRef,
        text: str,
        *,
        config: Optional[TurnConfig] = None,
        files: Sequence[IncomingFile] = (),
    ) -> asyncio.Task:
        task = asyncio.create_task(
            self._turn(bot, target, user, text, config, tuple(files)),
            name=f"telegram-turn-{target.key}",
        )
        self._tasks[task] = target
        task.add_done_callback(lambda t: self._tasks.pop(t, None))
        return task

    async def _turn(
        self,
        bot: Bot,
        target: ChatTarget,
        user: AionUserRef,
        text: str,
        config: Optional[TurnConfig] = None,
        files: Tuple[IncomingFile, ...] = (),
    ) -> None:
        async def on_queued(position: int) -> None:
            await bot.send_message(
                target.chat_id,
                f"⏳ In coda (posizione {position}): rispondo appena possibile.",
                message_thread_id=target.thread_id,
            )

        renderer: Optional[ReplyRenderer] = None
        try:
            async with self.queue.slot(target.key, on_queued=on_queued):
                state = await self.session_for(target, user)
                if config is None:
                    profile = await self.current_profile(state, user)
                    project = state.project_slug
                else:
                    try:
                        profile = await self.adapter.resolve_profile(
                            user, config.profile_slug or self.settings.default_profile
                        )
                    except ChannelPolicyError:
                        raise
                    except ChatAccessError as e:
                        raise ChatAccessError(
                            "Il tuo utente AION non ha accesso al profilo di questo "
                            "assistente: chiedi al suo creatore o a un amministratore."
                        ) from e
                    project = config.project_slug
                if project:
                    project_user = config.project_user if config else None
                    checker = (
                        replace(user, identifier=project_user) if project_user else user
                    )
                    await self.adapter.check_project(checker, project, profile)
                cid = await self._conversation_for(
                    state,
                    user,
                    profile,
                    project,
                    metadata=config.metadata if config else None,
                    first_text=text,
                )

                turn_attachments = await self._save_files(cid, files)
                # Output folders before the turn: what changes is what the agent
                # generated, sent back to the chat once the answer is delivered.
                outputs_before = await asyncio.to_thread(snapshot_outputs, cid)
                renderer = ReplyRenderer(
                    bot,
                    target.chat_id,
                    draft_support=self.draft_support_for(bot.id),
                    rich_support=self.rich_support_for(bot.id),
                    interval_sec=self.settings.stream_edit_interval_ms / 1000,
                    thread_id=target.thread_id,
                    private_chat=config.private_chat if config else True,
                    reply_to=config.reply_to if config else None,
                )
                prompt = (
                    f"{config.prompt_prefix}{text}"
                    if config and config.prompt_prefix
                    else text
                )
                self._running[target.key] = cid
                draft_key = (bot.id, target.chat_id, renderer.draft_id)
                self._by_draft[draft_key] = target.key
                try:
                    await renderer.start()
                    answer = await asyncio.wait_for(
                        self._stream(
                            renderer,
                            user,
                            cid,
                            prompt,
                            profile,
                            project,
                            turn_attachments,
                            config.project_user if config and project else None,
                        ),
                        timeout=self.settings.turn_timeout_sec,
                    )
                except asyncio.TimeoutError:
                    # wait_for ha chiuso lo stream; il flag ferma anche l'agente.
                    await self.adapter.cancel(cid)
                    raise
                finally:
                    self._running.pop(target.key, None)
                    self._by_draft.pop(draft_key, None)
                await self._send_outputs(bot, target, cid, outputs_before)
                if answer and config and config.on_answer:
                    try:
                        await config.on_answer(answer)
                    except Exception as e:  # noqa: BLE001 — la risposta è già stata inviata
                        logger.warning(
                            "telegram: registrazione della risposta fallita: %s",
                            redact(e),
                        )
        except ChatAccessError as e:
            await self._reply_error(bot, target, renderer, f"🚫 {escape(str(e))}")
        except asyncio.TimeoutError:
            await self._reply_error(
                bot, target, renderer, "⏱️ Risposta interrotta: tempo massimo superato."
            )
        except asyncio.CancelledError:
            # Shutdown di AION: avviso best effort, poi propaga la cancellazione.
            await asyncio.shield(
                self._reply_error(
                    bot,
                    target,
                    renderer,
                    "⚠️ AION si sta riavviando: risposta interrotta.",
                )
            )
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(
                "telegram: turno fallito chat=%s: %s", target.chat_id, redact(e)
            )
            await self._reply_error(
                bot, target, renderer, "⚠️ Si è verificato un errore. Riprova tra poco."
            )
        finally:
            if renderer is not None:
                await renderer.close()

    async def _send_outputs(
        self, bot: Bot, target: ChatTarget, cid: str, before: dict
    ) -> None:
        """Send the files generated during the turn, like WhatsApp does.

        Files beyond ``max_outbound_files`` (or rejected by Telegram) stay in
        the session and are announced with a link to the conversation.
        """
        after = await asyncio.to_thread(snapshot_outputs, cid)
        files = collect_new_outputs(before, after)
        if not files:
            return
        _sent, left_out = await outputs.send_outputs(
            bot,
            chat_id=target.chat_id,
            thread_id=target.thread_id,
            session_id=cid,
            files=files,
            max_files=self.settings.max_outbound_files,
        )
        if left_out:
            try:
                await bot.send_message(
                    target.chat_id,
                    outputs.more_files_html(left_out, cid),
                    message_thread_id=target.thread_id,
                )
            except Exception as e:  # noqa: BLE001 — the answer is already delivered
                logger.warning("telegram: avviso file non inviato: %s", redact(e))

    async def _save_files(self, cid: str, files: Tuple[IncomingFile, ...]) -> list:
        """Scarica gli allegati da Telegram e li salva nella conversazione.

        Returns the ``AttachmentRef``-shaped dicts, passed to the turn as
        ``turn_attachments`` (the files "new this turn").
        """
        refs = []
        for f in files:
            if f.size is not None and f.size > MAX_FILE_BYTES:
                raise ChatAccessError(
                    f"Il file «{f.name}» supera i 20 MB che Telegram consente ai bot."
                )
            data = await f.load()
            try:
                refs.append(await self.adapter.save_attachment(cid, f.name, data))
            except ValueError as e:  # limite AION_UPLOAD_MAX_BYTES
                raise ChatAccessError(f"File «{f.name}» non accettato: {e}") from e
        return refs

    async def _conversation_for(
        self,
        state: ChatSession,
        user: AionUserRef,
        profile: str,
        project: Optional[str],
        *,
        metadata: Optional[dict] = None,
        first_text: str = "",
    ) -> str:
        """Active AION conversation of the chat, or a new one titled from ``first_text``.

        ``tg_sessions`` maps the chat to its conversation (as WhatsApp's
        ``active_conversation_id``); /new clears it and the next message lands here.
        """
        if state.conversation_id and await self.adapter.sync_conversation(
            user, state.conversation_id, profile_slug=profile, project_slug=project
        ):
            return state.conversation_id
        cid = await self.adapter.create_conversation(
            user,
            profile_slug=profile,
            project_slug=project,
            extra_metadata=metadata,
            first_text=first_text,
        )
        await self.sessions.update(state.id, conversation_id=cid)
        return cid

    async def _stream(
        self,
        renderer: ReplyRenderer,
        user: AionUserRef,
        cid: str,
        text: str,
        profile: str,
        project: Optional[str],
        turn_attachments: Optional[list] = None,
        project_user: Optional[str] = None,
    ) -> Optional[str]:
        """Risposta finale completa, None se interrotta o in errore."""
        parts: list[str] = []
        reasoning: list[str] = []
        final: Optional[str] = None
        error: Optional[Error] = None
        tools = ToolActivity()
        show_tools = self.settings.show_tools
        kwargs: dict = (
            {"turn_attachments": turn_attachments} if turn_attachments else {}
        )
        if project_user:
            kwargs["project_user"] = project_user
        async for event in self.adapter.chat_stream(
            user, cid, text, profile_slug=profile, project_slug=project, **kwargs
        ):
            if isinstance(event, TextDelta):
                parts.append(event.text)
                renderer.update("".join(parts))
            elif isinstance(event, ReasoningDelta):
                if not reasoning and not parts and not tools:
                    # Come la Chat UI: si vede che il modello sta ragionando.
                    renderer.set_status("💭 Sto ragionando…")
                reasoning.append(event.text)
            elif isinstance(event, (ToolCall, ToolResult)):
                if isinstance(event, ToolCall):
                    tools.start(event)
                else:
                    tools.finish(event)
                if show_tools:
                    renderer.set_status(tools.live_html())
            elif isinstance(event, Final):
                final = event.text
            elif isinstance(event, Error):
                error = event
        answer = (final if final else "".join(parts)).strip()
        footers = [tools.summary_html()] if show_tools and tools else []
        # Same session in the chat-ui: link to continue there (as on WhatsApp).
        continue_link = outputs.continue_link_html(cid)
        if continue_link:
            footers.append(continue_link)
        thinking = (
            reasoning_block("".join(reasoning))
            if self.settings.show_reasoning
            else None
        )
        if error is not None and error.cancelled:
            footers.append("<i>⏹️ Risposta interrotta.</i>")
            await renderer.finish(
                answer, footer="\n".join(footers), rich_header=thinking
            )
            return None
        if error is not None and not answer:
            await renderer.fail(f"⚠️ {escape(error.message[:500])}")
            return None
        await renderer.finish(
            answer, footer="\n".join(footers) or None, rich_header=thinking
        )
        return answer or None

    async def _reply_error(
        self, bot: Bot, target: ChatTarget, renderer: Optional[ReplyRenderer], html: str
    ) -> None:
        try:
            if renderer is not None:
                await renderer.fail(html)
            else:
                await bot.send_message(
                    target.chat_id, html, message_thread_id=target.thread_id
                )
        except Exception as e:  # noqa: BLE001 — bot bloccato, rete giù
            logger.warning("telegram: messaggio di errore non inviato: %s", redact(e))

    # ---------- shutdown ----------
    async def shutdown(self, timeout: float = 5.0) -> None:
        for cid in list(self._running.values()):
            try:
                await self.adapter.cancel(cid)
            except Exception:  # noqa: BLE001
                pass
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)
