"""Chat con l'agente: testo → turno AION; /new, /profile, /project, /stop.

Raggiunto solo da utenti collegati (``AccessMiddleware``): ``aion_user`` è sempre valorizzato.
"""

from __future__ import annotations

from html import escape
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    MessageGenerationStopped,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.channels.telegram.adapter import AionAdapter, AionUserRef, ChatAccessError
from src.channels.telegram.chat import (
    MAX_FILE_BYTES,
    VOICE_TEXT,
    ChatService,
    ChatTarget,
    files_ack_text,
    incoming_file,
)

PROFILE_CB = "tgp:"
PROJECT_CB = "tgj:"
# Telegram: callback_data al massimo 64 byte.
_CB_MAX = 64


def target_of(message: Message, bot: Bot) -> ChatTarget:
    return ChatTarget(
        bot_id=bot.id,
        chat_id=message.chat.id,
        tg_user_id=message.from_user.id,
        thread_id=message.message_thread_id if message.is_topic_message else None,
    )


def _callback_target(query: CallbackQuery, bot: Bot) -> Optional[ChatTarget]:
    msg = query.message
    if not isinstance(msg, Message):
        return None
    return ChatTarget(
        bot_id=bot.id,
        chat_id=msg.chat.id,
        tg_user_id=query.from_user.id,
        thread_id=msg.message_thread_id if msg.is_topic_message else None,
    )


async def on_text(
    message: Message, bot: Bot, chat: ChatService, aion_user: AionUserRef
) -> None:
    target = target_of(message, bot)
    chat.submit(
        bot,
        target,
        aion_user,
        message.text or "",
        files=chat.pending.take(target.key),
    )


async def on_file(
    message: Message, bot: Bot, chat: ChatService, aion_user: AionUserRef
) -> None:
    file = incoming_file(message, bot)
    if file is None:
        return
    if file.size is not None and file.size > MAX_FILE_BYTES:
        await message.answer(
            f"📎 «{escape(file.name)}» supera i 20 MB che Telegram consente ai bot."
        )
        return
    target = target_of(message, bot)

    async def submit(text: str, files: list, msg: Message) -> None:
        chat.submit(bot, target_of(msg, bot), aion_user, text, files=files)

    async def ack(files: list) -> None:
        await message.answer(files_ack_text(files))

    await chat.pending.receive(
        target.key, message, file, message.caption or "", submit=submit, ack=ack
    )


async def on_voice(message: Message) -> None:
    await message.answer(VOICE_TEXT)


async def on_generation_stopped(
    event: MessageGenerationStopped, bot: Bot, chat: ChatService
) -> None:
    await chat.stop_draft(bot.id, event.chat.id, event.draft_id)


async def cmd_new(
    message: Message, bot: Bot, chat: ChatService, aion_user: AionUserRef
) -> None:
    target = target_of(message, bot)
    chat.pending.clear(target.key)
    state = await chat.new_conversation(target, aion_user)
    profile = await chat.current_profile(state, aion_user)
    lines = [
        "🆕 Nuova conversazione.",
        f"Profilo: <b>{escape(chat.adapter.profile_name(profile))}</b>",
    ]
    if state.project_slug:
        lines.append(f"Progetto: <b>{escape(state.project_slug)}</b>")
    await message.answer("\n".join(lines))


async def cmd_stop(message: Message, bot: Bot, chat: ChatService) -> None:
    if await chat.stop(target_of(message, bot)):
        await message.answer("⏹️ Interrompo la risposta…")
    else:
        await message.answer("Nessuna risposta in corso.")


# ---------- /profile ----------
async def _profile_keyboard(
    adapter: AionAdapter, user: AionUserRef, current: str
) -> Optional[InlineKeyboardMarkup]:
    kb = InlineKeyboardBuilder()
    count = 0
    for p in await adapter.list_profiles(user):
        data = PROFILE_CB + p.slug
        if len(data.encode()) > _CB_MAX:
            continue
        mark = "✓ " if p.slug == current else ""
        kb.button(text=f"{mark}{p.name}", callback_data=data)
        count += 1
    kb.adjust(1)
    return kb.as_markup() if count else None


async def cmd_profile(
    message: Message, bot: Bot, chat: ChatService, aion_user: AionUserRef
) -> None:
    state = await chat.session_for(target_of(message, bot), aion_user)
    current = await chat.current_profile(state, aion_user)
    markup = await _profile_keyboard(chat.adapter, aion_user, current)
    if markup is None:
        await message.answer("Nessun profilo disponibile per il tuo utente.")
        return
    await message.answer(
        f"Profilo attuale: <b>{escape(chat.adapter.profile_name(current))}</b>\nScegli il profilo:",
        reply_markup=markup,
    )


async def on_profile_chosen(
    query: CallbackQuery, bot: Bot, chat: ChatService, aion_user: AionUserRef
) -> None:
    target = _callback_target(query, bot)
    slug = (query.data or "")[len(PROFILE_CB) :]
    if target is None or not slug:
        await query.answer()
        return
    try:
        resolved = await chat.adapter.resolve_profile(aion_user, slug)
    except ChatAccessError as e:
        await query.answer(str(e), show_alert=True)
        return
    state = await chat.session_for(target, aion_user)
    await chat.sessions.update(state.id, profile_slug=resolved)
    name = escape(chat.adapter.profile_name(resolved))
    await query.answer(f"Profilo: {chat.adapter.profile_name(resolved)}")
    await query.message.edit_text(
        f"✅ Profilo impostato: <b>{name}</b>\nVale dal prossimo messaggio; /new per ripartire da zero."
    )


# ---------- /project ----------
async def cmd_project(
    message: Message, bot: Bot, chat: ChatService, aion_user: AionUserRef
) -> None:
    state = await chat.session_for(target_of(message, bot), aion_user)
    profile = await chat.current_profile(state, aion_user)
    projects = await chat.adapter.list_projects(aion_user, profile)
    kb = InlineKeyboardBuilder()
    for p in projects:
        data = PROJECT_CB + p.slug
        if len(data.encode()) > _CB_MAX:
            continue
        mark = "✓ " if p.slug == state.project_slug else ""
        kb.button(text=f"{mark}{p.display_name}", callback_data=data)
    kb.button(
        text=("✓ " if not state.project_slug else "") + "Nessun progetto",
        callback_data=PROJECT_CB,
    )
    kb.adjust(1)
    current = escape(state.project_slug) if state.project_slug else "nessuno"
    await message.answer(
        f"Progetto attuale: <b>{current}</b>\nScegli il progetto:",
        reply_markup=kb.as_markup(),
    )


async def on_project_chosen(
    query: CallbackQuery, bot: Bot, chat: ChatService, aion_user: AionUserRef
) -> None:
    target = _callback_target(query, bot)
    if target is None:
        await query.answer()
        return
    slug = (query.data or "")[len(PROJECT_CB) :] or None
    state = await chat.session_for(target, aion_user)
    if slug:
        profile = await chat.current_profile(state, aion_user)
        try:
            await chat.adapter.check_project(aion_user, slug, profile)
        except ChatAccessError as e:
            await query.answer(str(e)[:190], show_alert=True)
            return
    await chat.sessions.update(state.id, project_slug=slug)
    label = escape(slug) if slug else "nessuno"
    await query.answer()
    await query.message.edit_text(
        f"✅ Progetto impostato: <b>{label}</b>\nVale dal prossimo messaggio."
    )


def build_router() -> Router:
    router = Router(name="telegram-chat")
    router.stopped_message_generation.register(on_generation_stopped)
    router.message.register(on_file, F.document | F.photo)
    router.message.register(on_voice, F.voice | F.video_note)
    router.message.register(cmd_new, Command("new"))
    router.message.register(cmd_stop, Command("stop"))
    router.message.register(cmd_profile, Command("profile"))
    router.message.register(cmd_project, Command("project"))
    router.callback_query.register(on_profile_chosen, F.data.startswith(PROFILE_CB))
    router.callback_query.register(on_project_chosen, F.data.startswith(PROJECT_CB))
    # Testo libero (non comandi): all'agente.
    router.message.register(on_text, F.text, ~F.text.startswith("/"))
    return router
