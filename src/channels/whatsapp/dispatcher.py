"""Elaborazione dei messaggi WhatsApp in entrata (task asyncio in background).

Il webhook salva il messaggio e chiama ``enqueue``; qui, con un lock per
mittente (i messaggi della stessa persona vanno in ordine):

1. identità: BSUID → ``whatsapp_identities`` → utente AION;
   non collegato → ``COLLEGA <codice>`` oppure link alle impostazioni;
2. comandi ``/aiuto``, ``/nuova``, ``/scollega``;
3. turno dell'agente con la stessa pipeline della chat-ui (profili, memoria,
   tool MCP), nella conversazione attiva (``metadata.source = "whatsapp"``);
4. risposta convertita in formattazione WhatsApp e inviata a blocchi, seguita
   dai file generati dall'agente nel turno (``media.send_outputs``).

Photos and documents are saved in the conversation (``media.ingest_inbound_media``):
with a caption they start a turn right away, without one they are parked in
``whatsapp_identities.pending_attachments_json`` and attached to the user's
next text message (an album becomes a single turn).

Il turno è registrato in ``_background_runs``: dalla chat-ui si può seguire
dal vivo come quelli dei cron.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from src.data.engine import get_async_session_maker
from src.data.models import Conversation, User, WhatsAppIdentity
from src.identity import sanitize_user_id
from src.runtime.redis_client import cache_get, cache_set

from . import config_service, linking, media, store
from .config_service import ChannelConfig
from .formatting import prepare_reply
from .graph_client import GraphClient, GraphError, MediaTooLarge
from .payload import MEDIA_TYPES, InboundMessage

logger = logging.getLogger("aion.whatsapp.dispatcher")

DEFAULT_TURN_TIMEOUT_S = 600.0
DEFAULT_PROFILE_SLUG = "aion_std"
UNLINKED_REPLY_TTL_S = 10 * 60
RESUME_MAX_AGE = timedelta(hours=24)
TEXT_TYPES = ("text", "button", "interactive")
# Media received without a caption wait at most this long for the user's
# follow-up text; older ones stay in the session as historical files only.
PENDING_MEDIA_TTL = timedelta(hours=24)
# Keys of the pending entries that are bookkeeping, not part of AttachmentRef.
_PENDING_META_KEYS = ("added_at", "conversation_id")

_TASKS: Set[asyncio.Task] = set()
_LOCKS: Dict[str, asyncio.Lock] = {}

# Factory sostituibile nei test (``httpx.MockTransport``).
graph_client_factory = GraphClient


MESSAGES = {
    "help": (
        "*AION su WhatsApp*\n"
        "Scrivi la tua domanda e ti rispondo come nella chat di AION.\n"
        "Puoi anche inviarmi foto e documenti (PDF, Word, Excel…): "
        "aggiungi una didascalia o scrivimi dopo cosa vuoi che ne faccia.\n\n"
        "Comandi:\n"
        "• /nuova — inizia una nuova conversazione\n"
        "• /scollega — scollega questo WhatsApp dal tuo account\n"
        "• /aiuto — mostra questo messaggio\n\n"
        "Le conversazioni le ritrovi anche su {chat_url}"
    ),
    "welcome": "Ciao{name}! Il tuo WhatsApp è collegato ad AION ✅\n\n{help}",
    "link_invalid": (
        "Codice non valido. Genera un nuovo codice da AION → Impostazioni → "
        "WhatsApp: {settings_url}"
    ),
    "link_expired": (
        "Il codice è scaduto. Generane uno nuovo da AION → Impostazioni → "
        "WhatsApp: {settings_url}"
    ),
    "link_rate_limited": "Troppi tentativi. Riprova tra qualche minuto.",
    "unlinked": (
        "Ciao! Per usare l'assistente AION da WhatsApp collega prima il tuo "
        "account: apri {settings_url} e segui le istruzioni."
    ),
    "new_conversation": "Ok, nuova conversazione. Di cosa hai bisogno?",
    "unlinked_done": (
        "WhatsApp scollegato dal tuo account AION. Per ricollegarlo: {settings_url}"
    ),
    "text_only": "Per ora posso leggere solo messaggi di testo. Scrivimi la domanda 🙂",
    "media_unsupported": (
        "Per ora posso leggere testo, foto e documenti (PDF, Word, Excel, "
        "PowerPoint…). Vocali, video e sticker non sono ancora supportati 🙂"
    ),
    "media_received": (
        "📎 Ricevuto! Mandami altri file oppure scrivimi cosa vuoi che ne faccia."
    ),
    "media_too_large": (
        "Il file è troppo grande per WhatsApp (max {max_mb} MB). Caricalo dalla "
        "chat di AION: {chat_url}"
    ),
    "media_failed": (
        "Non sono riuscito a scaricare il file da WhatsApp. Riprova a inviarlo tra poco."
    ),
    "more_files": "📁 Altri {count} file sono disponibili su AION: {conversation_url}",
    "timeout": (
        "Ci sto mettendo troppo a rispondere. Trovi la conversazione su AION: "
        "{conversation_url}"
    ),
    "error": (
        "Si è verificato un errore e non sono riuscito a rispondere. Riprova tra poco."
    ),
    "empty": "Non ho una risposta testuale da mostrare qui. Vedi su AION: {conversation_url}",
    "continue_label": "Continua su AION",
}


def _turn_timeout_s() -> float:
    try:
        return max(
            30.0,
            float(os.getenv("AION_WHATSAPP_TURN_TIMEOUT_S") or DEFAULT_TURN_TIMEOUT_S),
        )
    except ValueError:
        return DEFAULT_TURN_TIMEOUT_S


def _chat_url() -> str:
    from src.api.public_urls import chat_base_url

    return chat_base_url().rstrip("/")


def settings_url() -> str:
    return f"{_chat_url()}/settings?tab=whatsapp"


def conversation_url(conversation_id: str) -> str:
    return f"{_chat_url()}/c/{conversation_id}"


def _help_text() -> str:
    return MESSAGES["help"].format(chat_url=_chat_url())


# ---------------------------------------------------------------------------
# Coda
# ---------------------------------------------------------------------------


def enqueue(tenant_id: str, wamid: str) -> None:
    """Avvia l'elaborazione in background (riferimento forte al task)."""
    task = asyncio.create_task(process(tenant_id, wamid), name=f"wa:{wamid[-12:]}")
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _lock_for(tenant_id: str, sender: str) -> asyncio.Lock:
    key = f"{tenant_id}:{sender}"
    lock = _LOCKS.get(key)
    if lock is None:
        lock = _LOCKS[key] = asyncio.Lock()
    return lock


async def resume_pending() -> int:
    """All'avvio: riprende i messaggi rimasti a metà (< 24h), i più vecchi → failed."""
    pending = await store.pending_inbound(RESUME_MAX_AGE)
    for tenant_id, wamid in pending:
        enqueue(tenant_id, wamid)
    if pending:
        logger.info("WhatsApp: resuming %d pending inbound messages", len(pending))
    return len(pending)


async def process(tenant_id: str, wamid: str) -> None:
    loaded = await store.load_inbound(wamid)
    if loaded is None or loaded.status in ("done", "failed"):
        return
    msg = loaded.message
    if msg is None:
        await store.set_inbound_status(wamid, "failed", error_code="bad_payload")
        return
    async with _lock_for(tenant_id, msg.sender_key or wamid):
        await _process(tenant_id, msg)


# ---------------------------------------------------------------------------
# Elaborazione di un messaggio
# ---------------------------------------------------------------------------


class _Replier:
    """Invia risposte al mittente di ``msg`` e registra i wamid in uscita."""

    def __init__(self, cfg: ChannelConfig, msg: InboundMessage):
        self.cfg = cfg
        self.msg = msg
        self.client = graph_client_factory(cfg.access_token or "")
        self.conversation_id: Optional[str] = None

    async def send(self, text: str) -> None:
        out_wamid = await self.client.send_text(
            self.cfg.phone_number_id or "",
            text,
            to=self.msg.phone,
            recipient=self.msg.bsuid,
        )
        await store.record_outbound(
            self.cfg.tenant_id,
            out_wamid,
            bsuid=self.msg.sender_key,
            conversation_id=self.conversation_id,
        )

    async def send_media(
        self, kind: str, data: bytes, mime: str, filename: str
    ) -> None:
        """Upload ``data`` to Meta and send it as an ``image``/``document`` message."""
        pnid = self.cfg.phone_number_id or ""
        media_id = await self.client.upload_media(pnid, data, mime, filename)
        out_wamid = await self.client.send_media(
            pnid,
            kind,
            media_id,
            filename=filename,
            to=self.msg.phone,
            recipient=self.msg.bsuid,
        )
        await store.record_outbound(
            self.cfg.tenant_id,
            out_wamid,
            bsuid=self.msg.sender_key,
            conversation_id=self.conversation_id,
        )

    async def mark_read(self) -> None:
        """Blue ticks for messages we acknowledge without starting a turn."""
        try:
            await self.client.mark_read(self.cfg.phone_number_id or "", self.msg.wamid)
        except GraphError as e:
            logger.debug("WhatsApp read receipt failed: %s", e)

    async def typing(self) -> None:
        try:
            await self.client.mark_read_typing(
                self.cfg.phone_number_id or "", self.msg.wamid
            )
        except GraphError as e:
            logger.debug("WhatsApp typing indicator failed: %s", e)


async def _process(tenant_id: str, msg: InboundMessage) -> None:
    await store.set_inbound_status(msg.wamid, "processing")
    cfg = await config_service.get_channel(tenant_id)
    if cfg is None or not cfg.active:
        await store.set_inbound_status(msg.wamid, "done", clear_payload=True)
        return

    replier = _Replier(cfg, msg)
    try:
        if msg.type == "system":
            if msg.system:
                await linking.apply_number_change(
                    tenant_id,
                    previous_bsuid=msg.system.previous_bsuid,
                    new_bsuid=msg.system.new_bsuid,
                    new_phone=msg.system.new_phone,
                    previous_phone=msg.system.previous_phone,
                )
        elif msg.sender_key:
            ident = await linking.get_identity(tenant_id, msg.bsuid, msg.phone)
            user = await _load_user(ident) if ident else None
            if ident is not None and user is None:
                # Utente cancellato: il collegamento non vale più.
                await linking.unlink(tenant_id, identity_id=ident.id)
                ident = None
            if ident is None or user is None:
                await _handle_unlinked(tenant_id, msg, replier)
            else:
                await _handle_linked(tenant_id, cfg, msg, ident, user, replier)
        await store.set_inbound_status(
            msg.wamid,
            "done",
            conversation_id=replier.conversation_id,
            clear_payload=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("WhatsApp message %s failed", msg.wamid)
        await store.set_inbound_status(
            msg.wamid,
            "failed",
            conversation_id=replier.conversation_id,
            error_code=str(getattr(e, "code", "") or type(e).__name__),
            clear_payload=True,
        )
        await config_service.set_last_error(tenant_id, f"{type(e).__name__}: {e}")
        if not isinstance(e, GraphError):
            try:
                await replier.send(MESSAGES["error"])
            except Exception:  # noqa: BLE001
                pass


async def _load_user(ident: WhatsAppIdentity) -> Optional[User]:
    async with get_async_session_maker()() as session:
        return await session.get(User, ident.user_id)


async def _try_link(
    tenant_id: str, msg: InboundMessage, code: str, replier: _Replier
) -> None:
    result = await linking.consume_code(
        tenant_id,
        code=code,
        bsuid=msg.sender_key or "",
        phone=msg.phone,
        profile_name=msg.profile_name,
    )
    if result.ok and result.user is not None:
        name = (
            msg.profile_name or result.user.display_name or result.user.identifier or ""
        ).strip()
        await replier.send(
            MESSAGES["welcome"].format(
                name=f" {name}" if name else "", help=_help_text()
            )
        )
        return
    key = {
        "expired": "link_expired",
        "rate_limited": "link_rate_limited",
    }.get(result.reason, "link_invalid")
    await replier.send(MESSAGES[key].format(settings_url=settings_url()))


async def _handle_unlinked(
    tenant_id: str, msg: InboundMessage, replier: _Replier
) -> None:
    code = linking.parse_link_command(msg.text)
    if code:
        await _try_link(tenant_id, msg, code, replier)
        return
    # Una sola risposta ogni 10 minuti: niente spam verso chi scrive per sbaglio.
    throttle_key = f"wa_unlinked_reply:{tenant_id}:{msg.sender_key}"
    if await cache_get(throttle_key):
        return
    await cache_set(throttle_key, "1", ttl_sec=UNLINKED_REPLY_TTL_S)
    await replier.send(MESSAGES["unlinked"].format(settings_url=settings_url()))


async def _handle_linked(
    tenant_id: str,
    cfg: ChannelConfig,
    msg: InboundMessage,
    ident: WhatsAppIdentity,
    user: User,
    replier: _Replier,
) -> None:
    updates: dict = {"last_inbound_at": datetime.now(timezone.utc)}
    if msg.profile_name and msg.profile_name != ident.wa_profile_name:
        updates["wa_profile_name"] = msg.profile_name
    if msg.phone and msg.phone != ident.phone_e164:
        updates["phone_e164"] = msg.phone
    await linking.update_identity(ident.id, **updates)

    text = (msg.text or "").strip()
    is_media = (
        msg.type in media.SUPPORTED_INBOUND_TYPES
        and msg.media is not None
        and media.media_enabled()
    )
    if not is_media and (msg.type not in TEXT_TYPES or not text):
        if msg.type == "reaction":
            return  # an emoji reaction needs no answer
        unsupported = msg.type in MEDIA_TYPES and media.media_enabled()
        await replier.send(
            MESSAGES["media_unsupported" if unsupported else "text_only"]
        )
        return

    if not is_media:
        code = linking.parse_link_command(text)
        if code:
            await _try_link(tenant_id, msg, code, replier)
            return

        command = text.split()[0].lower() if text.startswith("/") else ""
        if command in ("/aiuto", "/help"):
            await replier.send(_help_text())
            return
        if command in ("/nuova", "/new"):
            # Files waiting for a follow-up belong to the old conversation.
            await linking.update_identity(
                ident.id, active_conversation_id=None, pending_attachments_json=None
            )
            await replier.send(MESSAGES["new_conversation"])
            return
        if command in ("/scollega", "/unlink"):
            await linking.unlink(tenant_id, identity_id=ident.id)
            await replier.send(
                MESSAGES["unlinked_done"].format(settings_url=settings_url())
            )
            return

    title_hint = text
    if is_media and not title_hint:
        title_hint = f"📎 {media.inbound_filename(msg.type, msg.media)}"
    conversation_id, profile = await _resolve_conversation(
        tenant_id=tenant_id, cfg=cfg, ident=ident, user=user, first_text=title_hint
    )
    replier.conversation_id = conversation_id
    pending = _load_pending(ident, conversation_id)

    if is_media:
        attachment = await _ingest_media(tenant_id, cfg, msg, conversation_id, replier)
        if attachment is None:
            return
        if not text:
            # No caption: park the file until the user tells us what to do.
            # One acknowledgement per burst (album), read receipts afterwards.
            pending.append(
                {
                    **attachment,
                    "added_at": datetime.now(timezone.utc).isoformat(),
                    "conversation_id": conversation_id,
                }
            )
            await linking.update_identity(
                ident.id, pending_attachments_json=json.dumps(pending)
            )
            if len(pending) == 1:
                await replier.send(MESSAGES["media_received"])
            else:
                await replier.mark_read()
            return
        pending.append(attachment)

    if pending or ident.pending_attachments_json:
        # Consumed by this turn (also drops expired/foreign entries).
        await linking.update_identity(ident.id, pending_attachments_json=None)
    turn_attachments = [_attachment_ref(a) for a in pending]

    await replier.typing()
    result = await run_turn(
        tenant_id=tenant_id,
        cfg=cfg,
        user=user,
        conversation_id=conversation_id,
        profile=profile,
        text=text,
        wamid=msg.wamid,
        turn_attachments=turn_attachments,
    )
    replier.conversation_id = result.conversation_id
    conv_url = conversation_url(result.conversation_id)
    if result.timed_out:
        await replier.send(MESSAGES["timeout"].format(conversation_url=conv_url))
        return
    if result.error and not result.text:
        await replier.send(MESSAGES["error"])
        return
    chunks = prepare_reply(
        result.text,
        continue_url=conv_url,
        continue_label=MESSAGES["continue_label"],
    )
    send_files = bool(result.files) and media.media_enabled()
    if not chunks and not send_files:
        chunks = [MESSAGES["empty"].format(conversation_url=conv_url)]
    for chunk in chunks:
        await replier.send(chunk)
    if send_files:
        # Files after the text, so the answer explains what is being sent.
        _sent, left_out = await media.send_outputs(
            replier, result.conversation_id, result.files
        )
        if left_out:
            await replier.send(
                MESSAGES["more_files"].format(count=left_out, conversation_url=conv_url)
            )


async def _ingest_media(
    tenant_id: str,
    cfg: ChannelConfig,
    msg: InboundMessage,
    conversation_id: str,
    replier: _Replier,
) -> Optional[Dict[str, Any]]:
    """Download and store the message's media; on failure reply and return None."""
    assert msg.media is not None
    try:
        return await media.ingest_inbound_media(
            replier.client,
            tenant_id=tenant_id,
            phone_number_id=cfg.phone_number_id,
            conversation_id=conversation_id,
            msg_type=msg.type,
            media=msg.media,
        )
    except MediaTooLarge:
        await replier.send(
            MESSAGES["media_too_large"].format(
                max_mb=media.max_inbound_bytes() // (1024 * 1024),
                chat_url=conversation_url(conversation_id),
            )
        )
    except media.MediaIngestError as e:
        logger.warning("WhatsApp media %s not ingested: %s", msg.media.id, e)
        await replier.send(MESSAGES["media_failed"])
    return None


def _load_pending(
    ident: WhatsAppIdentity, conversation_id: str
) -> List[Dict[str, Any]]:
    """Pending (caption-less) media still usable in ``conversation_id``.

    Entries from another conversation (archived or replaced meanwhile) or older
    than ``PENDING_MEDIA_TTL`` are dropped: their files stay in that session.
    """
    try:
        items = json.loads(ident.pending_attachments_json or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    cutoff = datetime.now(timezone.utc) - PENDING_MEDIA_TTL
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("conversation_id") != conversation_id:
            continue
        try:
            added = datetime.fromisoformat(str(item.get("added_at")))
        except ValueError:
            continue
        if added.tzinfo is None:
            added = added.replace(tzinfo=timezone.utc)
        if added >= cutoff:
            out.append(item)
    return out


def _attachment_ref(item: Dict[str, Any]) -> Dict[str, Any]:
    """Upload metadata without the pending-queue bookkeeping keys."""
    return {k: v for k, v in item.items() if k not in _PENDING_META_KEYS}


# ---------------------------------------------------------------------------
# Turno dell'agente
# ---------------------------------------------------------------------------


@dataclass
class TurnResult:
    conversation_id: str
    text: str = ""
    timed_out: bool = False
    error: Optional[str] = None
    # Session-relative paths of the deliverables created during the turn.
    files: List[str] = field(default_factory=list)


async def _resolve_profile(user_row_id: str, preferred: Optional[str]) -> str:
    from fastapi import HTTPException

    from src.api.profile_access import allowed_profile_slugs, enforce_profile_access

    profile = (preferred or "").strip() or DEFAULT_PROFILE_SLUG
    try:
        return await enforce_profile_access(user_row_id, profile)
    except HTTPException:
        allowed = await allowed_profile_slugs(user_row_id)
        return allowed[0] if allowed else profile


def _resolve_thinking(cfg: ChannelConfig) -> str:
    """Turn-level reasoning (``off|min|medium|max``) for a WhatsApp turn.

    Mirrors what chat-ui sends (``thinking_enabled`` + ``reasoning_effort``)
    via ``resolve_turn_reasoning``, but the level comes from the channel config
    set in admin-ui instead of the user's composer:

    * ``off``                 → thinking disabled;
    * ``min|medium|max``      → thinking enabled at that effort (an explicit
      ``min`` is low-effort thinking, not "off", as in chat-ui);
    * unset (NULL)            → system default (``AION_DEFAULT_REASONING_EFFORT`` /
      ``AION_THINKING_ENABLED``), instead of the previously hard-coded medium.
    """
    from src.runtime.reasoning_effort import resolve_turn_reasoning

    level = (cfg.default_thinking_level or "").strip().lower()
    if level == "off":
        return resolve_turn_reasoning(None, False)
    if level in ("min", "medium", "max"):
        return resolve_turn_reasoning(level, True)
    return resolve_turn_reasoning(None, None)


async def _sync_thinking_metadata(conversation_id: str, level: str) -> None:
    """Mirror the turn's thinking level into the conversation metadata.

    chat-ui restores its Thinking toggle/effort from ``metadata.thinking_enabled``
    / ``metadata.reasoning_effort`` when a conversation is opened and otherwise
    falls back to the browser's last-used value (usually "medium"). Writing the
    level used by the WhatsApp turn keeps the chat-ui composer consistent with
    what the channel actually ran. Called on every turn so a change made in
    admin-ui reaches already-open conversations too; best-effort (never blocks
    the reply).
    """
    try:
        async with get_async_session_maker()() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv is None:
                return
            try:
                meta = json.loads(conv.metadata_json or "{}")
            except (TypeError, ValueError):
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            patch: Dict[str, object] = {"thinking_enabled": level != "off"}
            # chat-ui's effort selector only knows min|medium|max: "off" keeps
            # the previous effort and only flips the toggle.
            if level != "off":
                patch["reasoning_effort"] = level
            if all(meta.get(k) == v for k, v in patch.items()):
                return
            meta.update(patch)
            conv.metadata_json = json.dumps(meta)
            await session.commit()
    except Exception:
        logger.warning("WhatsApp: thinking metadata sync failed", exc_info=True)


async def _ensure_conversation(
    *,
    conversation_id: Optional[str],
    user_id: str,
    tenant_id: str,
    profile_slug: str,
    first_text: str,
) -> str:
    """Conversazione attiva dell'utente o una nuova (``metadata.source="whatsapp"``)."""
    from src.api.ownership import claim_session_owner_marker, read_session_owner_marker

    async with get_async_session_maker()() as session:
        if conversation_id:
            existing = await session.get(Conversation, conversation_id)
            usable = (
                existing is not None
                and existing.archived_at is None
                and sanitize_user_id(existing.user_id) == sanitize_user_id(user_id)
                and (existing.tenant_id or "default") == tenant_id
            )
            if usable:
                existing.updated_at = datetime.now(timezone.utc)
                await session.commit()
                return conversation_id

        new_id = str(uuid.uuid4())
        marker = read_session_owner_marker(new_id)
        if marker is not None and sanitize_user_id(marker) != sanitize_user_id(user_id):
            raise PermissionError("session_not_owned")
        claim_session_owner_marker(new_id, sanitize_user_id(user_id))
        title = " ".join(first_text.split())
        if len(title) > 60:
            title = title[:57].rstrip() + "…"
        session.add(
            Conversation(
                id=new_id,
                tenant_id=tenant_id,
                user_id=user_id,
                profile_slug=profile_slug,
                title=title or "WhatsApp",
                message_count=0,
                metadata_json=json.dumps({"source": "whatsapp"}),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return new_id


async def _resolve_conversation(
    *,
    tenant_id: str,
    cfg: ChannelConfig,
    ident: WhatsAppIdentity,
    user: User,
    first_text: str,
) -> Tuple[str, str]:
    """``(conversation_id, profile)`` for the user's next message.

    Resolved before the turn because a caption-less media must be stored in a
    conversation even when no turn runs. Persists the active conversation on
    the identity when a new one is created.
    """
    uid = sanitize_user_id(user.identifier or user.id)
    profile = await _resolve_profile(user.id, cfg.default_profile_slug)
    conversation_id = await _ensure_conversation(
        conversation_id=ident.active_conversation_id,
        user_id=uid,
        tenant_id=tenant_id,
        profile_slug=profile,
        first_text=first_text,
    )
    if conversation_id != ident.active_conversation_id:
        await linking.update_identity(ident.id, active_conversation_id=conversation_id)
    return conversation_id, profile


def _session_attachments(
    conversation_id: str, turn_attachments: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Every upload of the session, as chat-ui sends it in ``attachments``.

    The pipeline lists them to the agent split into "new this turn" (the ones
    in ``turn_attachments``) and "historical", so earlier photos/documents
    stay reachable in follow-up questions.
    """
    from src.session_workspace import list_dir

    turn_paths = {a.get("relative_path") for a in turn_attachments}
    historical = [
        {
            "relative_path": f["relative_path"],
            "original_name": f.get("name"),
            "mime": f.get("mime"),
        }
        for f in list_dir(conversation_id, "uploads")
        if f.get("relative_path") not in turn_paths
    ]
    return list(turn_attachments) + historical


async def run_turn(
    *,
    tenant_id: str,
    cfg: ChannelConfig,
    user: User,
    conversation_id: str,
    profile: str,
    text: str,
    wamid: str,
    turn_attachments: Optional[List[Dict[str, Any]]] = None,
) -> TurnResult:
    """Un turno dell'agente, come ``cron_runner.execute_job`` ma per l'utente.

    ``turn_attachments`` are the files sent with (or just before) this
    message. The session output folders are snapshotted around the turn to
    report the files the agent created in ``TurnResult.files``.
    """
    from src.agent_pipeline import AgentPipeline
    from src.api.v1.chat import BackgroundChatRun, _background_runs, _clamped_runtime
    from src.main import get_agent, set_event_loop
    from src.runtime.redis_client import (
        redis_clear_stream_active,
        redis_set_stream_active,
        redis_set_stream_cancel,
    )

    uid = sanitize_user_id(user.identifier or user.id)
    turn_attachments = list(turn_attachments or [])
    attachments = await asyncio.to_thread(
        _session_attachments, conversation_id, turn_attachments
    )
    outputs_before = await asyncio.to_thread(media.snapshot_outputs, conversation_id)

    thinking_level = _resolve_thinking(cfg)
    await _sync_thinking_metadata(conversation_id, thinking_level)

    result = TurnResult(conversation_id=conversation_id)
    user_message_id = str(uuid.uuid4())
    assistant_message_id = str(uuid.uuid4())
    await redis_set_stream_active(
        conversation_id,
        assistant_message_id=assistant_message_id,
        user_message_id=user_message_id,
        profile_name=profile,
    )
    run = BackgroundChatRun(conversation_id)
    _background_runs[conversation_id] = run

    async def _stream() -> None:
        set_event_loop(asyncio.get_running_loop())
        agent_instance, profile_name = await get_agent(
            profile,
            session_id=conversation_id,
            user_id=uid,
            tenant_id=tenant_id,
            agent_mode="normal",
            message_source="user_input",
        )
        pipeline = AgentPipeline(
            agent=agent_instance,
            session_id=conversation_id,
            profile_name=profile_name,
            user_id=uid,
            agent_mode="normal",
        )
        runtime = await _clamped_runtime(None, uid, profile_name)
        tokens: list[str] = []
        async for chunk in pipeline.run_stream(
            text,
            attachments=attachments or None,
            # Always a list (possibly empty): with ``None`` the pipeline would
            # persist every historical upload as an attachment of this message.
            turn_attachments=turn_attachments,
            # Thinking level configured for the channel (reasoning chunks are
            # not forwarded: only "token"/"final" reach the WhatsApp reply).
            reasoning_effort=thinking_level,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            message_source="user_input",
            metadata={"channel": "whatsapp", "wamid": wamid},
            runtime=runtime,
        ):
            event = {"event": "message", "data": json.dumps(chunk, default=str)}
            run.history.append(event)
            for q in list(run.queues):
                await q.put(event)
            ctype = str(chunk.get("type") or "")
            if ctype == "token":
                tokens.append(str(chunk.get("content") or ""))
            elif ctype == "final":
                result.text = str(chunk.get("text") or "")
            elif ctype == "error":
                result.error = str(chunk.get("content") or "error")
        if not result.text:
            result.text = "".join(tokens).strip()
        outputs_after = await asyncio.to_thread(media.snapshot_outputs, conversation_id)
        result.files = media.collect_new_outputs(outputs_before, outputs_after)

    try:
        await asyncio.wait_for(_stream(), timeout=_turn_timeout_s())
    except asyncio.TimeoutError:
        logger.warning("WhatsApp turn timed out (conversation %s)", conversation_id)
        await redis_set_stream_cancel(conversation_id)
        result.timed_out = True
    finally:
        run.is_done = True
        for q in list(run.queues):
            await q.put(None)
        _background_runs.pop(conversation_id, None)
        await redis_clear_stream_active(conversation_id)
    return result
