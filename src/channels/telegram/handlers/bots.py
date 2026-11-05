"""Bot personali sul manager: wizard /newbot, gestione /mybots e update managed_bot.

Wizard (stato FSM in memoria: un riavvio di AION lo azzera, basta rifare /newbot):
nome → profilo → progetto → riepilogo → pulsante nativo ``request_managed_bot``.
La creazione vera avviene nel client Telegram; ``BotFactory.register`` la completa.
"""

from __future__ import annotations

import logging
from html import escape
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestManagedBot,
    ManagedBotUpdated,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.channels.telegram import groups
from src.channels.telegram.adapter import AionUserRef, ChatAccessError
from src.channels.telegram.bots import (
    MODE_LABELS,
    NAME_MAX,
    STATUS_LABELS,
    BotFactory,
    BotInfo,
    BotMode,
    BotStatus,
    QuotaExceeded,
    suggest_username,
)
from src.channels.telegram.redact import redact

logger = logging.getLogger("aion.telegram")

# Wizard /newbot
NEW_CB = "tgn:"
NEW_PROFILE = NEW_CB + "p:"
NEW_PROJECT = NEW_CB + "j:"
NEW_MODE = NEW_CB + "m:"
NEW_OK = NEW_CB + "ok"
NEW_CANCEL = NEW_CB + "x"
# /mybots
MY_CB = "tgb:"
MY_LIST = MY_CB + "ls"
MY_DETAILS = MY_CB + "d:"
MY_MODE = MY_CB + "mo:"
MY_PROFILE_MENU = MY_CB + "pe:"
MY_PROFILE_SET = MY_CB + "ps:"
MY_PROJECT_MENU = MY_CB + "je:"
MY_PROJECT_SET = MY_CB + "js:"
MY_SUSPEND = MY_CB + "su:"
MY_RETRY = MY_CB + "rt:"
MY_DELETE = MY_CB + "de:"
MY_DELETE_OK = MY_CB + "dy:"
MY_ROTATE = MY_CB + "rk:"
_CB_MAX = 64

CANCEL_HINT = "/cancel per annullare."


class NewBot(StatesGroup):
    name = State()
    mode = State()
    profile = State()
    project = State()
    confirm = State()


def _fits(data: str) -> bool:
    return len(data.encode()) <= _CB_MAX


# ---------- /newbot ----------
async def cmd_newbot(
    message: Message,
    state: FSMContext,
    bot_factory: BotFactory,
    aion_user: AionUserRef,
) -> None:
    reason = bot_factory.unavailable_reason()
    if reason:
        await message.answer(f"🚫 {reason}")
        return
    try:
        await bot_factory.check_quota(aion_user.row_id)
    except QuotaExceeded as e:
        await message.answer(f"🚫 {escape(str(e))}")
        return
    await state.clear()
    await state.set_state(NewBot.name)
    await message.answer(
        "🤖 <b>Nuovo bot personale</b>\n\n"
        "Come vuoi chiamarlo? (es. <i>Assistente RAG</i>)\n" + CANCEL_HINT
    )


async def cmd_cancel(
    message: Message, state: FSMContext, bot_factory: BotFactory
) -> None:
    had_state = await state.get_state() is not None
    await state.clear()
    await bot_factory.bots.discard_pending(message.from_user.id)
    await message.answer(
        "Creazione del bot annullata."
        if had_state
        else "Nessuna operazione da annullare.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def on_name(
    message: Message,
    state: FSMContext,
    bot_factory: BotFactory,
    aion_user: AionUserRef,
) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        # Qualsiasi altro comando interrompe il wizard.
        await state.clear()
        await message.answer("Creazione del bot annullata. Ripeti il comando.")
        return
    if not text or len(text) > NAME_MAX:
        await message.answer(
            f"Il nome deve avere da 1 a {NAME_MAX} caratteri. Riprova. " + CANCEL_HINT
        )
        return
    await state.update_data(name=text)
    await state.set_state(NewBot.mode)
    kb = InlineKeyboardBuilder()
    kb.button(
        text=MODE_LABELS[BotMode.PERSONAL.value], callback_data=NEW_MODE + "personal"
    )
    kb.button(text=MODE_LABELS[BotMode.SHARED.value], callback_data=NEW_MODE + "shared")
    kb.button(text="✖ Annulla", callback_data=NEW_CANCEL)
    kb.adjust(2, 1)
    await message.answer(
        f"Nome: <b>{escape(text)}</b>\n\n"
        "Chi potrà usarlo?\n"
        "🔒 <b>Personale</b>: solo tu, in chat privata.\n"
        "👥 <b>Condiviso</b>: chiunque abbia collegato il proprio account ad AION "
        "(ognuno con i propri permessi)"
        # Group mentions only while groups are enabled (``groups.GROUPS_ENABLED``).
        + ("; puoi aggiungerlo ai gruppi." if groups.GROUPS_ENABLED else "."),
        reply_markup=kb.as_markup(),
    )


async def on_new_mode(
    query: CallbackQuery,
    state: FSMContext,
    bot_factory: BotFactory,
    aion_user: AionUserRef,
) -> None:
    mode = (query.data or "")[len(NEW_MODE) :]
    if mode not in (BotMode.PERSONAL.value, BotMode.SHARED.value):
        await query.answer()
        return
    await state.update_data(mode=mode)
    markup = await _new_profile_keyboard(bot_factory, aion_user)
    await query.answer()
    if markup is None:
        await state.clear()
        await query.message.edit_text("Nessun profilo disponibile per il tuo utente.")
        return
    await state.set_state(NewBot.profile)
    await query.message.edit_text(
        f"Modalità: <b>{MODE_LABELS[mode]}</b>\n\n"
        "Scegli il profilo dell'agente per questo bot:",
        reply_markup=markup,
    )


async def _new_profile_keyboard(
    bot_factory: BotFactory, aion_user: AionUserRef
) -> Optional[InlineKeyboardMarkup]:
    kb = InlineKeyboardBuilder()
    count = 0
    default = bot_factory.settings.default_profile
    profiles = await bot_factory.adapter.list_profiles(aion_user)
    # Il profilo di default per primo: basta confermarlo.
    profiles.sort(key=lambda p: p.slug != default)
    for p in profiles:
        data = NEW_PROFILE + p.slug
        if _fits(data):
            label = f"⭐ {p.name}" if p.slug == default else p.name
            kb.button(text=label, callback_data=data)
            count += 1
    kb.button(text="✖ Annulla", callback_data=NEW_CANCEL)
    kb.adjust(1)
    return kb.as_markup() if count else None


async def on_new_profile(
    query: CallbackQuery,
    state: FSMContext,
    bot_factory: BotFactory,
    aion_user: AionUserRef,
) -> None:
    try:
        profile = await bot_factory.adapter.resolve_profile(
            aion_user, query.data[len(NEW_PROFILE) :]
        )
    except ChatAccessError as e:
        await query.answer(str(e)[:190], show_alert=True)
        return
    await state.update_data(profile=profile)
    await query.answer()
    projects = await bot_factory.adapter.list_projects(aion_user, profile)
    kb = InlineKeyboardBuilder()
    count = 0
    for p in projects:
        data = NEW_PROJECT + p.slug
        if _fits(data):
            kb.button(text=p.display_name, callback_data=data)
            count += 1
    if not count:
        await state.update_data(project=None)
        await _show_summary(query, state, bot_factory)
        return
    kb.button(text="Nessun progetto", callback_data=NEW_PROJECT)
    kb.button(text="✖ Annulla", callback_data=NEW_CANCEL)
    kb.adjust(1)
    await state.set_state(NewBot.project)
    await query.message.edit_text(
        f"Profilo: <b>{escape(bot_factory.adapter.profile_name(profile))}</b>\n\n"
        "Vuoi collegare un progetto?",
        reply_markup=kb.as_markup(),
    )


async def on_new_project(
    query: CallbackQuery,
    state: FSMContext,
    bot_factory: BotFactory,
    aion_user: AionUserRef,
) -> None:
    project = query.data[len(NEW_PROJECT) :] or None
    if project:
        data = await state.get_data()
        try:
            await bot_factory.adapter.check_project(aion_user, project, data["profile"])
        except ChatAccessError as e:
            await query.answer(str(e)[:190], show_alert=True)
            return
    await state.update_data(project=project)
    await query.answer()
    await _show_summary(query, state, bot_factory)


async def _show_summary(
    query: CallbackQuery, state: FSMContext, bot_factory: BotFactory
) -> None:
    data = await state.get_data()
    await state.set_state(NewBot.confirm)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Crea il bot", callback_data=NEW_OK)
    kb.button(text="✖ Annulla", callback_data=NEW_CANCEL)
    kb.adjust(2)
    project = escape(data["project"]) if data.get("project") else "nessuno"
    mode = data.get("mode", BotMode.PERSONAL.value)
    access = (
        "Lo potranno usare tutti gli utenti AION che hanno collegato Telegram"
        + ("; solo tu potrai aggiungerlo ai gruppi." if groups.GROUPS_ENABLED else ".")
        if mode == BotMode.SHARED.value
        else "Il bot sarà accessibile solo a te."
    )
    await query.message.edit_text(
        "<b>Riepilogo</b>\n"
        f"Nome: <b>{escape(data['name'])}</b>\n"
        f"Modalità: <b>{MODE_LABELS[mode]}</b>\n"
        f"Profilo: <b>{escape(bot_factory.adapter.profile_name(data['profile']))}</b>\n"
        f"Progetto: <b>{project}</b>\n\n" + access,
        reply_markup=kb.as_markup(),
    )


async def on_new_confirm(
    query: CallbackQuery,
    state: FSMContext,
    bot_factory: BotFactory,
    aion_user: AionUserRef,
) -> None:
    data = await state.get_data()
    await state.clear()
    try:
        await bot_factory.check_quota(aion_user.row_id)
    except QuotaExceeded as e:
        await query.answer(str(e)[:190], show_alert=True)
        return
    pending = await bot_factory.bots.save_pending(
        owner_tg_user_id=query.from_user.id,
        owner_aion_user_id=aion_user.row_id,
        name=data["name"],
        profile_slug=data.get("profile"),
        project_slug=data.get("project"),
        mode=data.get("mode", BotMode.PERSONAL.value),
    )
    await query.answer()
    await query.message.edit_text(
        f"Ultimo passo per <b>{escape(data['name'])}</b>: conferma la creazione in Telegram."
    )
    username = suggest_username(data["name"])
    button = KeyboardButton(
        text="🤖 Crea il bot",
        request_managed_bot=KeyboardButtonRequestManagedBot(
            request_id=pending.request_id,
            suggested_name=data["name"][:NAME_MAX],
            suggested_username=username,
        ),
    )
    lines = [
        "Premi <b>🤖 Crea il bot</b> qui sotto: Telegram ti chiederà di confermare "
        "il nome e lo username (deve finire con <code>bot</code>, puoi cambiarlo).",
    ]
    link = bot_factory.creation_link(username, data["name"])
    if link:
        lines.append(
            f'\nSe il pulsante non compare, usa <a href="{escape(link)}">questo link</a>.'
        )
    lines.append("\nLa richiesta vale 30 minuti. " + CANCEL_HINT)
    await query.message.answer(
        "\n".join(lines),
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[button]], resize_keyboard=True, one_time_keyboard=True
        ),
    )


async def on_new_cancel(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await query.answer()
    await query.message.edit_text("Creazione del bot annullata.")


async def on_new_expired(query: CallbackQuery) -> None:
    # Pulsanti di un wizard non più in corso (completato, annullato o AION riavviato).
    await query.answer("Procedura scaduta: ricomincia con /newbot.", show_alert=True)


# ---------- creazione completata su Telegram ----------
async def on_bot_created(message: Message, bot: Bot, bot_factory: BotFactory) -> None:
    created = message.managed_bot_created
    await _register(bot, bot_factory, message.from_user, created.bot_user, False)


async def on_managed_bot(
    event: ManagedBotUpdated, bot: Bot, bot_factory: BotFactory
) -> None:
    await _register(bot, bot_factory, event.user, event.bot_user, True)


async def _register(bot, bot_factory, owner, bot_user, refresh_token: bool) -> None:
    try:
        await bot_factory.register(
            bot, owner=owner, bot_user=bot_user, refresh_token=refresh_token
        )
    except Exception as e:  # noqa: BLE001 — getManagedBotToken/rete: l'utente va avvisato
        logger.exception(
            "telegram: registrazione del bot %s fallita: %s", bot_user.id, redact(e)
        )
        try:
            await bot.send_message(
                owner.id,
                "⚠️ Il bot è stato creato su Telegram ma AION non è riuscito a "
                "registrarlo. Riprova tra poco o contatta l'amministratore.",
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception:  # noqa: BLE001
            pass


# ---------- /mybots ----------
def _list_view(bots: list[BotInfo]) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    if not bots:
        return "Non hai ancora bot personali. Creane uno con /newbot.", None
    kb = InlineKeyboardBuilder()
    lines = ["<b>I tuoi bot</b>"]
    for b in bots:
        lines.append(f"• {escape(b.mention)} — {STATUS_LABELS.get(b.status, b.status)}")
        row = [
            InlineKeyboardButton(
                text=f"⚙️ {b.mention}", callback_data=f"{MY_DETAILS}{b.id}"
            )
        ]
        url = open_url(b)
        if url:
            row.append(InlineKeyboardButton(text="💬 Apri", url=url))
        kb.row(*row)
    return "\n".join(lines), kb.as_markup()


def open_url(info: BotInfo) -> Optional[str]:
    """Link alla chat con l'assistente (solo se attivo e con username)."""
    if info.status != BotStatus.ACTIVE.value or not info.username:
        return None
    return f"https://t.me/{info.username}"


# ---------- testo libero sul manager (chat disattivata) ----------
async def on_manager_text(
    message: Message, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    """Il manager non chatta: indica gli assistenti, senza imporre la creazione."""
    bots = [
        b
        for b in await bot_factory.bots.list_for_owner(aion_user.row_id)
        if open_url(b)
    ]
    if not bots:
        await message.answer(
            "Sono il bot di gestione di AION: qui non rispondo alle domande.\n\n"
            "Per chattare con l'agente serve un assistente personale: se vuoi, "
            "creane uno con /newbot."
        )
        return
    kb = InlineKeyboardBuilder()
    for b in bots:
        kb.button(text=f"💬 {b.name or b.mention}", url=open_url(b))
    kb.adjust(1)
    await message.answer(
        "Sono il bot di gestione di AION: qui non rispondo alle domande.\n\n"
        "Scrivi a uno dei tuoi assistenti:",
        reply_markup=kb.as_markup(),
    )


def _details_view(
    info: BotInfo, bot_factory: BotFactory
) -> tuple[str, InlineKeyboardMarkup]:
    profile = (
        escape(bot_factory.adapter.profile_name(info.profile_slug))
        if info.profile_slug
        else "—"
    )
    project = escape(info.project_slug) if info.project_slug else "nessuno"
    lines = [
        f"<b>{escape(info.name or info.mention)}</b> ({escape(info.mention)})",
        f"Stato: {STATUS_LABELS.get(info.status, info.status)}",
        f"Modalità: {MODE_LABELS.get(info.mode, info.mode)}",
        f"Profilo: <b>{profile}</b>",
        f"Progetto: <b>{project}</b>",
    ]
    if info.last_error:
        lines.append(f"Ultimo errore: <i>{escape(info.last_error[:200])}</i>")
    kb = InlineKeyboardBuilder()
    kb.button(text="Profilo", callback_data=f"{MY_PROFILE_MENU}{info.id}")
    kb.button(text="Progetto", callback_data=f"{MY_PROJECT_MENU}{info.id}")
    if info.status == BotStatus.ACTIVE.value:
        kb.button(text="⏸️ Sospendi", callback_data=f"{MY_SUSPEND}{info.id}")
    elif info.status == BotStatus.SUSPENDED.value:
        kb.button(text="▶️ Riattiva", callback_data=f"{MY_SUSPEND}{info.id}")
    elif info.status in (BotStatus.ERROR.value, BotStatus.PROVISIONING.value):
        kb.button(
            text="🔁 Riprova configurazione", callback_data=f"{MY_RETRY}{info.id}"
        )
    sizes = [2, 1]
    if info.has_token and info.status != BotStatus.PROVISIONING.value:
        kb.button(
            text="🔒 Rendi personale" if info.shared else "👥 Rendi condiviso",
            callback_data=f"{MY_MODE}{info.id}",
        )
        sizes.append(1)
        kb.button(text="🔑 Rigenera token", callback_data=f"{MY_ROTATE}{info.id}")
        sizes.append(1)
    kb.button(text="🗑️ Elimina", callback_data=f"{MY_DELETE}{info.id}")
    kb.button(text="« I tuoi bot", callback_data=MY_LIST)
    kb.adjust(*sizes, 1, 1)
    return "\n".join(lines), kb.as_markup()


async def cmd_mybots(
    message: Message, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    text, markup = _list_view(await bot_factory.bots.list_for_owner(aion_user.row_id))
    await message.answer(text, reply_markup=markup)


async def _owned(
    query: CallbackQuery, bot_factory: BotFactory, aion_user: AionUserRef, prefix: str
) -> Optional[BotInfo]:
    """Bot indicato nel callback, solo se appartiene all'utente e non è eliminato."""
    raw = (query.data or "")[len(prefix) :].split(":", 1)[0]
    info = await bot_factory.bots.get(int(raw)) if raw.isdigit() else None
    if (
        info is None
        or info.owner_aion_user_id != aion_user.row_id
        or info.status == BotStatus.DELETED.value
    ):
        await query.answer("Bot non trovato.", show_alert=True)
        return None
    return info


async def _show_details(
    query: CallbackQuery, info: BotInfo, bot_factory: BotFactory
) -> None:
    text, markup = _details_view(info, bot_factory)
    await query.message.edit_text(text, reply_markup=markup)


async def on_my_list(
    query: CallbackQuery, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    text, markup = _list_view(await bot_factory.bots.list_for_owner(aion_user.row_id))
    await query.answer()
    await query.message.edit_text(text, reply_markup=markup)


async def on_my_details(
    query: CallbackQuery, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_DETAILS)
    if info is None:
        return
    await query.answer()
    await _show_details(query, info, bot_factory)


async def on_my_profile_menu(
    query: CallbackQuery, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_PROFILE_MENU)
    if info is None:
        return
    kb = InlineKeyboardBuilder()
    for p in await bot_factory.adapter.list_profiles(aion_user):
        data = f"{MY_PROFILE_SET}{info.id}:{p.slug}"
        if _fits(data):
            mark = "✓ " if p.slug == info.profile_slug else ""
            kb.button(text=f"{mark}{p.name}", callback_data=data)
    kb.button(text="« Indietro", callback_data=f"{MY_DETAILS}{info.id}")
    kb.adjust(1)
    await query.answer()
    await query.message.edit_text(
        f"Profilo di {escape(info.mention)}:", reply_markup=kb.as_markup()
    )


async def on_my_profile_set(
    query: CallbackQuery, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_PROFILE_SET)
    if info is None:
        return
    slug = query.data[len(MY_PROFILE_SET) :].split(":", 1)[1]
    try:
        profile = await bot_factory.adapter.resolve_profile(aion_user, slug)
    except ChatAccessError as e:
        await query.answer(str(e)[:190], show_alert=True)
        return
    updated = await bot_factory.bots.update(
        info.id,
        profile_slug=profile,
        audit="bot_profile_changed",
        actor_tg_user_id=query.from_user.id,
    )
    await query.answer("Profilo aggiornato")
    await _show_details(query, updated or info, bot_factory)


async def on_my_project_menu(
    query: CallbackQuery, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_PROJECT_MENU)
    if info is None:
        return
    kb = InlineKeyboardBuilder()
    for p in await bot_factory.adapter.list_projects(aion_user, info.profile_slug):
        data = f"{MY_PROJECT_SET}{info.id}:{p.slug}"
        if _fits(data):
            mark = "✓ " if p.slug == info.project_slug else ""
            kb.button(text=f"{mark}{p.display_name}", callback_data=data)
    kb.button(
        text=("✓ " if not info.project_slug else "") + "Nessun progetto",
        callback_data=f"{MY_PROJECT_SET}{info.id}:",
    )
    kb.button(text="« Indietro", callback_data=f"{MY_DETAILS}{info.id}")
    kb.adjust(1)
    await query.answer()
    await query.message.edit_text(
        f"Progetto di {escape(info.mention)}:", reply_markup=kb.as_markup()
    )


async def on_my_project_set(
    query: CallbackQuery, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_PROJECT_SET)
    if info is None:
        return
    project = query.data[len(MY_PROJECT_SET) :].split(":", 1)[1] or None
    if project and info.profile_slug:
        try:
            await bot_factory.adapter.check_project(
                aion_user, project, info.profile_slug
            )
        except ChatAccessError as e:
            await query.answer(str(e)[:190], show_alert=True)
            return
    updated = await bot_factory.bots.update(
        info.id,
        project_slug=project,
        audit="bot_project_changed",
        actor_tg_user_id=query.from_user.id,
    )
    await query.answer("Progetto aggiornato")
    await _show_details(query, updated or info, bot_factory)


async def on_my_suspend(
    query: CallbackQuery, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_SUSPEND)
    if info is None:
        return
    if info.status == BotStatus.ACTIVE.value:
        new_status, audit, note = BotStatus.SUSPENDED, "bot_suspended", "Bot sospeso"
    elif info.status == BotStatus.SUSPENDED.value:
        if info.last_error == "quota superata":
            try:
                await bot_factory.check_quota(aion_user.row_id)
            except QuotaExceeded as e:
                await query.answer(str(e)[:190], show_alert=True)
                return
        new_status, audit, note = BotStatus.ACTIVE, "bot_resumed", "Bot riattivato"
    else:
        await query.answer()
        return
    updated = await bot_factory.bots.update(
        info.id,
        status=new_status,
        last_error=None,
        audit=audit,
        actor_tg_user_id=query.from_user.id,
    )
    await bot_factory.sync_runtime(updated)
    await query.answer(note)
    await _show_details(query, updated or info, bot_factory)


async def on_my_retry(
    query: CallbackQuery, bot: Bot, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_RETRY)
    if info is None:
        return
    await query.answer("Configuro il bot…")
    try:
        info = await bot_factory.retry_provision(bot, info)
    except Exception as e:  # noqa: BLE001
        logger.warning("telegram: nuova configurazione fallita: %s", redact(e))
    await _show_details(query, info, bot_factory)


async def on_my_mode(
    query: CallbackQuery, bot: Bot, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_MODE)
    if info is None:
        return
    target = BotMode.PERSONAL.value if info.shared else BotMode.SHARED.value
    try:
        info = await bot_factory.set_mode(
            bot, info, target, actor_tg_user_id=query.from_user.id
        )
    except Exception as e:  # noqa: BLE001 — rete: il DB è già aggiornato
        logger.warning(
            "telegram: cambio modalità non applicato su Telegram: %s", redact(e)
        )
        info = await bot_factory.bots.get(info.id) or info
    note = (
        "Ora è condiviso: tutti gli utenti AION collegati possono usarlo."
        if info.shared
        else "Ora è personale: risponde solo a te"
        + (" e non nei gruppi." if groups.GROUPS_ENABLED else ".")
    )
    await query.answer(note, show_alert=True)
    await _show_details(query, info, bot_factory)


async def on_my_rotate(
    query: CallbackQuery, bot: Bot, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_ROTATE)
    if info is None:
        return
    try:
        info = await bot_factory.rotate_token(
            bot, info, actor_tg_user_id=query.from_user.id
        )
    except Exception as e:  # noqa: BLE001 — rete o bot non più gestito dal manager
        logger.warning("telegram: rotazione token fallita: %s", redact(e))
        await query.answer("Rotazione non riuscita: riprova tra poco.", show_alert=True)
        return
    await query.answer("Nuovo token generato: quello precedente non funziona più.")
    await _show_details(query, info, bot_factory)


async def on_my_delete(
    query: CallbackQuery, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_DELETE)
    if info is None:
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑️ Sì, elimina", callback_data=f"{MY_DELETE_OK}{info.id}")
    kb.button(text="« Annulla", callback_data=f"{MY_DETAILS}{info.id}")
    kb.adjust(2)
    await query.answer()
    await query.message.edit_text(
        f"Eliminare {escape(info.mention)} da AION?\n\n"
        "Il token viene revocato e il bot smette di funzionare. Per cancellarlo "
        "anche da Telegram usa poi @BotFather.",
        reply_markup=kb.as_markup(),
    )


async def on_my_delete_ok(
    query: CallbackQuery, bot: Bot, bot_factory: BotFactory, aion_user: AionUserRef
) -> None:
    info = await _owned(query, bot_factory, aion_user, MY_DELETE_OK)
    if info is None:
        return
    await bot_factory.delete(bot, info, actor_tg_user_id=query.from_user.id)
    await query.answer("Bot eliminato")
    text, markup = _list_view(await bot_factory.bots.list_for_owner(aion_user.row_id))
    await query.message.edit_text(
        f"🗑️ {escape(info.mention)} eliminato.\n\n{text}", reply_markup=markup
    )


def build_guide_router() -> Router:
    """Testo libero sul manager quando la chat è disattivata (dopo il wizard)."""
    router = Router(name="telegram-guide")
    router.message.register(on_manager_text, F.text, ~F.text.startswith("/"))
    return router


def build_router() -> Router:
    router = Router(name="telegram-bots")
    router.message.register(cmd_cancel, Command("cancel"))
    router.message.register(cmd_newbot, Command("newbot"))
    router.message.register(cmd_mybots, Command("mybots"))
    # Prima della chat: durante il wizard il testo è il nome del bot, non una domanda.
    router.message.register(on_name, StateFilter(NewBot.name), F.text)
    router.message.register(on_bot_created, F.managed_bot_created)
    router.managed_bot.register(on_managed_bot)

    router.callback_query.register(
        on_new_cancel, F.data == NEW_CANCEL, StateFilter("*")
    )
    router.callback_query.register(
        on_new_mode, StateFilter(NewBot.mode), F.data.startswith(NEW_MODE)
    )
    router.callback_query.register(
        on_new_profile, StateFilter(NewBot.profile), F.data.startswith(NEW_PROFILE)
    )
    router.callback_query.register(
        on_new_project, StateFilter(NewBot.project), F.data.startswith(NEW_PROJECT)
    )
    router.callback_query.register(
        on_new_confirm, StateFilter(NewBot.confirm), F.data == NEW_OK
    )
    router.callback_query.register(on_new_expired, F.data.startswith(NEW_CB))

    router.callback_query.register(on_my_list, F.data == MY_LIST)
    router.callback_query.register(on_my_details, F.data.startswith(MY_DETAILS))
    router.callback_query.register(
        on_my_profile_menu, F.data.startswith(MY_PROFILE_MENU)
    )
    router.callback_query.register(on_my_profile_set, F.data.startswith(MY_PROFILE_SET))
    router.callback_query.register(
        on_my_project_menu, F.data.startswith(MY_PROJECT_MENU)
    )
    router.callback_query.register(on_my_project_set, F.data.startswith(MY_PROJECT_SET))
    router.callback_query.register(on_my_suspend, F.data.startswith(MY_SUSPEND))
    router.callback_query.register(on_my_retry, F.data.startswith(MY_RETRY))
    router.callback_query.register(on_my_mode, F.data.startswith(MY_MODE))
    router.callback_query.register(on_my_rotate, F.data.startswith(MY_ROTATE))
    router.callback_query.register(on_my_delete, F.data.startswith(MY_DELETE))
    router.callback_query.register(on_my_delete_ok, F.data.startswith(MY_DELETE_OK))
    return router
