"""Assistenti (bot figli): chat con l'agente nella configurazione del bot.

Un solo Dispatcher serve tutti i bot figli: ``bot.id`` identifica la riga di
``tg_bots``, riletta a ogni messaggio (un cambio di profilo, progetto o modalità da
/mybots vale subito, senza riavviare il polling).

- **Personale**: solo il proprietario, in chat privata, con l'account Telegram
  collegato allo stesso utente AION che ha creato il bot.
- **Condiviso**: qualunque utente AION che abbia collegato Telegram, ognuno con la
  *propria* identità (permessi, memoria, conversazioni). Nei gruppi risponde solo
  ai messaggi rivolti a lui (menzione, risposta a un suo messaggio, /ask) e solo
  il proprietario può aggiungerlo a un gruppo.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from html import escape
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType, MessageEntityType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    Message,
    MessageGenerationStopped,
    TelegramObject,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.channels.telegram import runtime
from src.channels.telegram.adapter import (
    AionAdapter,
    AionUserRef,
    ChatAccessError,
)
from src.channels.telegram.bots import MODE_LABELS, BotInfo, BotStatus, TelegramBots
from src.channels.telegram.chat import (
    MAX_FILE_BYTES,
    UNSUPPORTED_TEXT,
    VOICE_TEXT,
    ChatService,
    TurnConfig,
    files_ack_text,
    files_label,
    incoming_file,
)
from src.channels.telegram import groups
from src.channels.telegram.groups import GroupLog, group_prompt
from src.channels.telegram.handlers.chat import target_of
from src.channels.telegram.handlers.common import on_error
from src.channels.telegram.redact import redact

logger = logging.getLogger("aion.telegram")

PROJECT_CB = "tgc:j:"
_ACTIVITY_EVERY = timedelta(minutes=1)
_CB_MAX = 64
GROUP_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)
_IN_CHAT = (
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.RESTRICTED,
)


def _manager_ref() -> str:
    username = runtime.manager_username()
    return f"@{username}" if username else "il bot AION principale"


def _link_hint() -> str:
    return (
        "🔒 Per usare questo assistente collega il tuo account Telegram ad AION: "
        f"Chat UI → Impostazioni → Telegram, oppure scrivi a {_manager_ref()}."
    )


# ---------- messaggi rivolti al bot nei gruppi ----------
def addressed_question(
    message: Message, bot_id: int, username: Optional[str]
) -> Optional[str]:
    """Testo della domanda se il messaggio di gruppo è rivolto al bot, altrimenti None.

    Rivolto = menzione ``@username`` (o menzione testuale), risposta a un messaggio
    del bot, oppure un comando senza ``@`` o con il suo ``@username``.
    """
    text = message.text or message.caption or ""
    uname = (username or "").lower()
    if text.startswith("/"):
        head, _, rest = text[1:].partition(" ")
        _, _, mention = head.partition("@")
        if mention and mention.lower() != uname:
            return None  # comando per un altro bot
        return rest.strip() if head.split("@")[0].lower() == "ask" else text
    reply = message.reply_to_message
    if (
        reply is not None
        and reply.from_user is not None
        and reply.from_user.id == bot_id
    ):
        return text.strip()
    for entity in message.entities or message.caption_entities or []:
        if entity.type == MessageEntityType.MENTION and uname:
            value = text[entity.offset : entity.offset + entity.length]
            if value.lstrip("@").lower() == uname:
                return (
                    text[: entity.offset] + text[entity.offset + entity.length :]
                ).strip()
        if (
            entity.type == MessageEntityType.TEXT_MENTION
            and entity.user is not None
            and entity.user.id == bot_id
        ):
            return (
                text[: entity.offset] + text[entity.offset + entity.length :]
            ).strip()
    return None


class ChildAccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery):
            chat = event.message.chat if event.message is not None else None
        else:
            return await handler(event, data)
        if chat is None or event.from_user is None:
            return None
        in_group = chat.type in GROUP_TYPES
        if chat.type != ChatType.PRIVATE and not in_group:
            return None  # canali
        if in_group and not groups.GROUPS_ENABLED:
            # Groups are disabled (see ``groups.GROUPS_ENABLED``): never answer
            # there, leave the group the bot is still in.
            await _leave(data["bot"], chat.id, groups.GROUPS_DISABLED_TEXT)
            return None

        bot: Bot = data["bot"]
        bots: TelegramBots = data["bots"]
        info = await bots.get_by_tg_id(bot.id)
        if info is None or info.status == BotStatus.DELETED.value:
            return None

        question: Optional[str] = None
        if isinstance(event, Message):
            if in_group:
                question = addressed_question(event, bot.id, info.username)
                if question is None:
                    return None  # chiacchiere del gruppo non rivolte al bot
            else:
                question = event.text or event.caption or ""
        if in_group and not info.shared:
            # Bot personale finito in un gruppo (es. modalità cambiata dopo l'ingresso).
            await _leave(
                bot, chat.id, "🔒 Sono un assistente personale: esco dal gruppo."
            )
            return None

        if not info.shared and event.from_user.id != info.owner_tg_user_id:
            return await _deny(event, "🔒 Questo è un assistente AION personale.")
        if info.status != BotStatus.ACTIVE.value:
            return await _deny(
                event,
                "⏸️ Questo assistente è sospeso."
                + (
                    f" Riattivalo da {_manager_ref()} con /mybots."
                    if event.from_user.id == info.owner_tg_user_id
                    else ""
                ),
            )
        accounts = data["accounts"]
        link = await accounts.get_link_for_tg(event.from_user.id)
        if info.shared:
            if link is None:
                return await _deny(event, _link_hint())
        elif link is None or link.aion_user_id != info.owner_aion_user_id:
            return await _deny(
                event,
                "🔒 Il tuo account Telegram non è collegato all'utente AION che ha "
                "creato questo bot. Collegalo da Chat UI → Impostazioni → Telegram.",
            )
        aion_user = await data["adapter"].resolve_user(link.aion_user_id)
        if aion_user is None:
            return await _deny(event, "🔒 Utente AION non trovato.")
        try:
            await accounts.touch(
                link,
                tg_username=event.from_user.username,
                tg_first_name=event.from_user.first_name,
            )
        except Exception as e:  # noqa: BLE001 — statistica, non deve bloccare
            logger.warning("telegram: aggiornamento last_seen fallito: %s", redact(e))
        try:
            await bots.touch_activity(info.id, every=_ACTIVITY_EVERY)
        except Exception as e:  # noqa: BLE001 — statistica per l'Admin UI
            logger.warning("telegram: ultima attività non aggiornata: %s", redact(e))
        data["aion_user"] = aion_user
        data["child_bot"] = info
        data["in_group"] = in_group
        data["question"] = question
        data["is_owner"] = event.from_user.id == info.owner_tg_user_id
        return await handler(event, data)


async def _deny(event: TelegramObject, text: str) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer(text[:190], show_alert=True)
    elif isinstance(event, Message) and event.chat.type in GROUP_TYPES:
        await event.reply(text)
    else:
        await event.answer(text)
    return None


async def _leave(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception:  # noqa: BLE001 — può non avere i permessi di scrittura
        pass
    try:
        await bot.leave_chat(chat_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("telegram: uscita dal gruppo %s fallita: %s", chat_id, redact(e))


def _author(message: Message) -> str:
    user = message.from_user
    if user is None:
        return "Utente"
    name = " ".join(p for p in (user.first_name, user.last_name) if p)
    return name or (f"@{user.username}" if user.username else str(user.id))


async def _config(
    info: BotInfo,
    message: Message,
    question: str,
    group_log: GroupLog,
    in_group: bool,
    adapter: Optional[AionAdapter] = None,
) -> TurnConfig:
    metadata = {"telegram_bot": info.username or str(info.bot_tg_id)}
    if not in_group:
        return TurnConfig(
            profile_slug=info.profile_slug,
            project_slug=info.project_slug,
            metadata=metadata,
        )
    metadata["telegram_chat"] = message.chat.title or str(message.chat.id)
    author = _author(message)
    entries = await group_log.context_for(
        bot_id=info.bot_tg_id, chat_id=message.chat.id, tg_user_id=message.from_user.id
    )

    async def remember(answer: str) -> None:
        await group_log.add(
            bot_id=info.bot_tg_id,
            chat_id=message.chat.id,
            tg_user_id=message.from_user.id,
            author=author,
            question=question,
            answer=answer,
        )

    # Nei gruppi il progetto di un assistente condiviso usa i permessi del creatore:
    # le risposte le leggono tutti, e chi mette il bot nel gruppo ne risponde.
    project_user = None
    if info.shared and info.project_slug and adapter is not None:
        owner = await adapter.resolve_user(info.owner_aion_user_id)
        project_user = owner.identifier if owner is not None else None
    return TurnConfig(
        profile_slug=info.profile_slug,
        project_slug=info.project_slug,
        metadata=metadata,
        project_user=project_user,
        private_chat=False,
        reply_to=message.message_id,
        prompt_prefix=group_prompt(
            entries, chat_title=message.chat.title, author=author
        ),
        on_answer=remember,
    )


def _status_text(info: BotInfo, chat: ChatService) -> str:
    profile = (
        escape(chat.adapter.profile_name(info.profile_slug))
        if info.profile_slug
        else escape(chat.adapter.profile_name(chat.settings.default_profile))
    )
    project = escape(info.project_slug) if info.project_slug else "nessuno"
    return (
        f"Modalità: <b>{MODE_LABELS.get(info.mode, info.mode)}</b>\n"
        f"Profilo: <b>{profile}</b>\nProgetto: <b>{project}</b>"
    )


def _help_text(info: BotInfo, in_group: bool) -> str:
    if in_group:
        ask = f"/ask@{info.username}" if info.username else "/ask"
        return (
            f"Usa {escape(ask)} domanda o rispondi a un mio messaggio: rispondo qui, "
            "visibile a tutti. Le menzioni funzionano se sono amministratore del "
            "gruppo.\n\n"
            "Rispondo con i permessi di chi chiede: serve aver collegato il proprio "
            f"account Telegram ad AION ({escape(_manager_ref())}).\n\n"
            "/new — ricomincia la tua conversazione\n"
            "/stop — interrompi la tua risposta in corso"
        )
    return (
        "Scrivimi una domanda: risponde l'agente AION con il profilo di questo bot.\n\n"
        "<b>Comandi</b>\n"
        "/new — nuova conversazione\n"
        "/project — scegli il progetto (solo il creatore)\n"
        "/stop — interrompi la risposta in corso\n"
        "/status — modalità, profilo e progetto del bot\n"
        "/help — questo elenco"
    )


async def cmd_start(message: Message, child_bot: BotInfo, chat: ChatService) -> None:
    kind = "condiviso" if child_bot.shared else "personale"
    await message.answer(
        f"Ciao! Sono <b>{escape(child_bot.name or child_bot.mention)}</b>, "
        f"assistente AION {kind}.\n\n"
        f"{_status_text(child_bot, chat)}\n\nScrivimi una domanda, /help per i comandi."
    )


async def cmd_help(message: Message, child_bot: BotInfo, in_group: bool) -> None:
    await message.answer(_help_text(child_bot, in_group))


async def cmd_status(
    message: Message, bot: Bot, child_bot: BotInfo, chat: ChatService
) -> None:
    lines = [f"<b>{escape(child_bot.mention)}</b>", _status_text(child_bot, chat)]
    if chat.is_running(target_of(message, bot)):
        lines.append("⏳ Risposta in corso (/stop per interromperla).")
    lines.append(
        f"\nLe impostazioni le cambia il creatore da {_manager_ref()} → /mybots."
    )
    await message.answer("\n".join(lines))


async def cmd_new(
    message: Message,
    bot: Bot,
    child_bot: BotInfo,
    chat: ChatService,
    aion_user: AionUserRef,
    in_group: bool,
) -> None:
    target = target_of(message, bot)
    chat.pending.clear(target.key)
    await chat.new_conversation(target, aion_user)
    if in_group:
        await message.reply(
            "🆕 Ricomincio la tua conversazione con me in questo gruppo."
        )
        return
    await message.answer(f"🆕 Nuova conversazione.\n{_status_text(child_bot, chat)}")


async def cmd_stop(message: Message, bot: Bot, chat: ChatService) -> None:
    if await chat.stop(target_of(message, bot)):
        await message.reply("⏹️ Interrompo la risposta…")
    else:
        await message.reply("Nessuna risposta in corso.")


async def cmd_project(
    message: Message,
    child_bot: BotInfo,
    chat: ChatService,
    aion_user: AionUserRef,
    is_owner: bool,
) -> None:
    if not is_owner:
        await message.reply(
            "Solo il creatore dell'assistente può cambiarne il progetto."
        )
        return
    projects = await chat.adapter.list_projects(aion_user, child_bot.profile_slug)
    kb = InlineKeyboardBuilder()
    for p in projects:
        data = PROJECT_CB + p.slug
        if len(data.encode()) > _CB_MAX:
            continue
        mark = "✓ " if p.slug == child_bot.project_slug else ""
        kb.button(text=f"{mark}{p.display_name}", callback_data=data)
    kb.button(
        text=("✓ " if not child_bot.project_slug else "") + "Nessun progetto",
        callback_data=PROJECT_CB,
    )
    kb.adjust(1)
    current = escape(child_bot.project_slug) if child_bot.project_slug else "nessuno"
    await message.answer(
        f"Progetto attuale: <b>{current}</b>\nScegli il progetto:",
        reply_markup=kb.as_markup(),
    )


async def on_project_chosen(
    query: CallbackQuery,
    child_bot: BotInfo,
    chat: ChatService,
    aion_user: AionUserRef,
    bots: TelegramBots,
    is_owner: bool,
) -> None:
    if not is_owner:
        await query.answer(
            "Solo il creatore può cambiare il progetto.", show_alert=True
        )
        return
    project: Optional[str] = (query.data or "")[len(PROJECT_CB) :] or None
    if project:
        profile = await chat.adapter.resolve_profile(
            aion_user, child_bot.profile_slug or chat.settings.default_profile
        )
        try:
            await chat.adapter.check_project(aion_user, project, profile)
        except ChatAccessError as e:
            await query.answer(str(e)[:190], show_alert=True)
            return
    # Il progetto è una proprietà del bot: vale anche in /mybots.
    await bots.update(
        child_bot.id,
        project_slug=project,
        audit="bot_project_changed",
        actor_tg_user_id=query.from_user.id,
    )
    label = escape(project) if project else "nessuno"
    await query.answer()
    await query.message.edit_text(
        f"✅ Progetto impostato: <b>{label}</b>\nVale dal prossimo messaggio."
    )


async def _ask(
    message: Message,
    bot: Bot,
    child_bot: BotInfo,
    chat: ChatService,
    aion_user: AionUserRef,
    group_log: GroupLog,
    in_group: bool,
    question: str,
) -> None:
    if not question.strip():
        await message.reply(
            "Scrivi la domanda dopo la menzione, ad esempio: /ask che ore sono a Tokyo?"
        )
        return
    # La chiave include chi scrive: nel gruppo ognuno ha la propria conversazione.
    target = target_of(message, bot)
    files = chat.pending.take(target.key)
    await _submit(
        message, bot, child_bot, chat, aion_user, group_log, in_group, question, files
    )


async def _submit(
    message: Message,
    bot: Bot,
    child_bot: BotInfo,
    chat: ChatService,
    aion_user: AionUserRef,
    group_log: GroupLog,
    in_group: bool,
    question: str,
    files: list,
) -> None:
    log_text = f"[📎 {files_label(files)}] {question}" if files else question
    chat.submit(
        bot,
        target_of(message, bot),
        aion_user,
        question,
        config=await _config(
            child_bot, message, log_text, group_log, in_group, chat.adapter
        ),
        files=files,
    )


async def on_file(
    message: Message,
    bot: Bot,
    child_bot: BotInfo,
    chat: ChatService,
    aion_user: AionUserRef,
    group_log: GroupLog,
    in_group: bool,
    question: Optional[str],
) -> None:
    """Documento o foto: salvati nella conversazione e allegati alla domanda."""
    file = incoming_file(message, bot)
    if file is None:
        return
    if file.size is not None and file.size > MAX_FILE_BYTES:
        await message.reply(
            f"📎 «{escape(file.name)}» supera i 20 MB che Telegram consente ai bot."
        )
        return

    async def submit(text: str, files: list, msg: Message) -> None:
        await _submit(
            msg, bot, child_bot, chat, aion_user, group_log, in_group, text, files
        )

    async def ack(files: list) -> None:
        # Senza didascalia (es. documenti da Android): si aspetta la domanda.
        await message.reply(files_ack_text(files))

    await chat.pending.receive(
        target_of(message, bot).key,
        message,
        file,
        question or "",
        submit=submit,
        ack=ack,
    )


async def on_voice(message: Message) -> None:
    await message.reply(VOICE_TEXT)


async def on_text(
    message: Message,
    bot: Bot,
    child_bot: BotInfo,
    chat: ChatService,
    aion_user: AionUserRef,
    group_log: GroupLog,
    in_group: bool,
    question: Optional[str],
) -> None:
    await _ask(
        message, bot, child_bot, chat, aion_user, group_log, in_group, question or ""
    )


async def cmd_ask(
    message: Message,
    command: CommandObject,
    bot: Bot,
    child_bot: BotInfo,
    chat: ChatService,
    aion_user: AionUserRef,
    group_log: GroupLog,
    in_group: bool,
) -> None:
    await _ask(
        message,
        bot,
        child_bot,
        chat,
        aion_user,
        group_log,
        in_group,
        command.args or "",
    )


async def fallback(message: Message, in_group: bool) -> None:
    if in_group:
        return  # nei gruppi niente risposte di cortesia: solo domande
    if message.text and message.text.startswith("/"):
        await message.answer("Comando sconosciuto. Usa /help per l'elenco.")
        return
    await message.answer(UNSUPPORTED_TEXT)


async def on_generation_stopped(
    event: MessageGenerationStopped, bot: Bot, chat: ChatService
) -> None:
    """Pulsante di stop sull'anteprima della risposta (chat private)."""
    await chat.stop_draft(bot.id, event.chat.id, event.draft_id)


# ---------- ingresso nei gruppi ----------
async def _reads_all_messages(bot: Bot, status: str) -> bool:
    """True se il bot riceve anche le menzioni: è amministratore del gruppo oppure
    ha la privacy mode disattivata in @BotFather (non modificabile via Bot API).

    Con la privacy mode attiva Telegram consegna solo i comandi per il bot
    (``/ask@nome_bot``) e le risposte ai suoi messaggi, non ``@nome_bot domanda``.
    """
    if status == ChatMemberStatus.ADMINISTRATOR:
        return True
    try:
        me = await bot.me()
    except Exception:  # noqa: BLE001
        return False
    return bool(me.can_read_all_group_messages)


def _usage_text(info: BotInfo, mentions: bool) -> str:
    mention = f"@{info.username}" if info.username else "il bot"
    ask = f"/ask@{info.username}" if info.username else "/ask"
    if mentions:
        return (
            f"Menzionami ({escape(mention)} domanda), rispondi a un mio messaggio "
            f"oppure usa {escape(ask)} domanda."
        )
    return (
        f"Fammi una domanda con {escape(ask)} domanda (dal menu /) oppure "
        "rispondendo a un mio messaggio.\n"
        f"Per usare anche la menzione {escape(mention)}, rendimi amministratore "
        "del gruppo: Telegram consegna le menzioni solo ai bot amministratori."
    )


async def on_added_to_chat(
    event: ChatMemberUpdated, bot: Bot, bots: TelegramBots
) -> None:
    """Solo i bot condivisi, e solo se li aggiunge il proprietario."""
    if event.chat.type not in GROUP_TYPES:
        return
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    joined = new_status in _IN_CHAT and old_status not in _IN_CHAT
    promoted = (
        new_status == ChatMemberStatus.ADMINISTRATOR
        and old_status in _IN_CHAT
        and old_status != ChatMemberStatus.ADMINISTRATOR
    )
    if not joined and not promoted:
        return
    if not groups.GROUPS_ENABLED:
        # Groups are disabled (see ``groups.GROUPS_ENABLED``): say so and leave.
        if joined:
            await _leave(bot, event.chat.id, groups.GROUPS_DISABLED_TEXT)
        return
    info = await bots.get_by_tg_id(bot.id)
    if info is None or info.status == BotStatus.DELETED.value:
        await _leave(bot, event.chat.id, "Questo assistente non è più attivo.")
        return
    if not info.shared:
        await _leave(
            bot,
            event.chat.id,
            "🔒 Sono un assistente personale: non posso stare nei gruppi.",
        )
        return
    if joined and event.from_user.id != info.owner_tg_user_id:
        await _leave(
            bot,
            event.chat.id,
            "🔒 Solo il creatore di questo assistente può aggiungerlo ai gruppi.",
        )
        return
    if promoted:
        mention = f"@{info.username}" if info.username else "il bot"
        text = (
            f"✅ Ora rispondo anche quando mi menzionate ({escape(mention)} domanda)."
        )
    else:
        mentions = await _reads_all_messages(bot, new_status)
        text = (
            f"Ciao! Sono <b>{escape(info.name or info.mention)}</b>, assistente AION.\n"
            f"{_usage_text(info, mentions)}\n\n"
            "Rispondo con i permessi di chi chiede: serve aver collegato il proprio "
            f"account Telegram ad AION ({escape(_manager_ref())})."
        )
    try:
        await bot.send_message(event.chat.id, text)
    except Exception as e:  # noqa: BLE001
        logger.warning("telegram: messaggio nel gruppo non inviato: %s", redact(e))


def build_router() -> Router:
    router = Router(name="telegram-child")
    router.my_chat_member.register(on_added_to_chat)
    router.stopped_message_generation.register(on_generation_stopped)
    # Prima dei comandi: una foto con didascalia "/ask@bot …" è un allegato.
    router.message.register(on_file, F.document | F.photo)
    router.message.register(on_voice, F.voice | F.video_note)
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_status, Command("status"))
    router.message.register(cmd_new, Command("new"))
    router.message.register(cmd_stop, Command("stop"))
    router.message.register(cmd_project, Command("project"))
    router.message.register(cmd_ask, Command("ask"))
    router.callback_query.register(on_project_chosen, F.data.startswith(PROJECT_CB))
    router.message.register(on_text, F.text, ~F.text.startswith("/"))
    router.message.register(fallback)
    router.errors.register(on_error)
    return router
