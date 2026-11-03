"""Parsing tollerante dei webhook WhatsApp Cloud API (campo ``messages``).

Dal 2026 Meta identifica gli utenti con il BSUID (``user_id`` /
``from_user_id``); il numero (``wa_id`` / ``from``) può mancare per chi usa
uno username. Usiamo il BSUID come chiave e il numero solo se presente.
Campi sconosciuti o mancanti vengono ignorati: un payload strano non deve mai
far fallire il webhook (Meta ritenterebbe per giorni).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SystemChange:
    """Messaggio di sistema: l'utente ha cambiato numero o BSUID."""

    kind: str  # user_changed_number | user_changed_user_id | altro
    previous_bsuid: Optional[str] = None
    previous_phone: Optional[str] = None
    new_bsuid: Optional[str] = None
    new_phone: Optional[str] = None
    body: Optional[str] = None


# Message types that carry a media object keyed by the type name
# (``msg["image"]``, ``msg["document"]``, ...).
MEDIA_TYPES = ("image", "document", "audio", "video", "sticker")
# Media types whose ``caption`` doubles as the user's text for the turn.
CAPTIONED_TYPES = ("image", "document", "video")


@dataclass
class InboundMedia:
    """Media attached to an inbound message (Cloud API webhook ``messages[]``).

    ``url`` is the direct download link Meta started adding to webhooks in
    October 2025 (rolled out gradually, valid ~5 minutes): when it is missing
    or expired the dispatcher falls back to ``GET /{media-id}``.
    """

    id: str
    mime_type: Optional[str] = None
    sha256: Optional[str] = None
    caption: Optional[str] = None
    filename: Optional[str] = None
    url: Optional[str] = None
    voice: bool = False
    animated: bool = False


@dataclass
class InboundMessage:
    phone_number_id: str
    wamid: str
    bsuid: Optional[str]
    phone: Optional[str]
    profile_name: Optional[str]
    type: str
    text: Optional[str] = None
    timestamp: Optional[int] = None
    system: Optional[SystemChange] = None
    media: Optional[InboundMedia] = None

    @property
    def sender_key(self) -> Optional[str]:
        """Chiave del mittente: BSUID, o il numero per i payload senza BSUID."""
        return self.bsuid or self.phone

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InboundMessage":
        data = dict(data)
        system = data.pop("system", None)
        # ``media`` is absent from payloads queued before media support.
        media = data.pop("media", None)
        return cls(
            **data,
            system=SystemChange(**system) if system else None,
            media=InboundMedia(**media) if media else None,
        )


@dataclass
class StatusUpdate:
    phone_number_id: str
    wamid: str
    status: str  # sent | delivered | read | failed
    bsuid: Optional[str] = None
    phone: Optional[str] = None
    error_code: Optional[str] = None
    error_title: Optional[str] = None


@dataclass
class ParsedWebhook:
    messages: List[InboundMessage] = field(default_factory=list)
    statuses: List[StatusUpdate] = field(default_factory=list)

    @property
    def phone_number_ids(self) -> List[str]:
        ids = {m.phone_number_id for m in self.messages}
        ids |= {s.phone_number_id for s in self.statuses}
        return sorted(i for i in ids if i)


def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _contacts_by_key(contacts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for c in contacts:
        if not isinstance(c, dict):
            continue
        for key in (_str(c.get("user_id")), _str(c.get("wa_id"))):
            if key:
                out[key] = c
    return out


def _parse_media(obj: Any) -> Optional[InboundMedia]:
    """Media object of an inbound message; ``None`` without a media id."""
    if not isinstance(obj, dict):
        return None
    media_id = _str(obj.get("id"))
    if not media_id:
        return None
    return InboundMedia(
        id=media_id,
        mime_type=_str(obj.get("mime_type")),
        sha256=_str(obj.get("sha256")),
        caption=_str(obj.get("caption")),
        filename=_str(obj.get("filename")),
        url=_str(obj.get("url")),
        voice=bool(obj.get("voice")),
        animated=bool(obj.get("animated")),
    )


def _parse_message(
    msg: Dict[str, Any], phone_number_id: str, contacts: Dict[str, Dict[str, Any]]
) -> Optional[InboundMessage]:
    wamid = _str(msg.get("id"))
    if not wamid:
        return None
    bsuid = _str(msg.get("from_user_id"))
    phone = _str(msg.get("from"))
    contact = contacts.get(bsuid or "") or contacts.get(phone or "") or {}
    bsuid = bsuid or _str(contact.get("user_id"))
    phone = phone or _str(contact.get("wa_id"))
    profile_name = _str((contact.get("profile") or {}).get("name"))
    mtype = _str(msg.get("type")) or "unknown"

    text: Optional[str] = None
    system: Optional[SystemChange] = None
    media: Optional[InboundMedia] = None
    if mtype == "text":
        text = (msg.get("text") or {}).get("body")
    elif mtype == "button":
        text = (msg.get("button") or {}).get("text")
    elif mtype == "interactive":
        inter = msg.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        text = reply.get("title")
    elif mtype == "system":
        sysd = msg.get("system") or {}
        kind = _str(sysd.get("type")) or "unknown"
        # Il mittente è l'identità *precedente*: per user_changed_number il
        # BSUID resta uguale e cambia solo il numero.
        system = SystemChange(
            kind=kind,
            previous_bsuid=_str(sysd.get("previous_user_id"))
            or _str(msg.get("previous_user_id"))
            or bsuid,
            previous_phone=phone,
            new_bsuid=_str(sysd.get("user_id")) or _str(sysd.get("new_user_id")),
            new_phone=_str(sysd.get("wa_id")) or _str(sysd.get("new_wa_id")),
            body=_str(sysd.get("body")),
        )
    elif mtype in MEDIA_TYPES:
        media = _parse_media(msg.get(mtype))
        if media and mtype in CAPTIONED_TYPES:
            text = media.caption
    if isinstance(text, str):
        text = text.strip() or None

    return InboundMessage(
        phone_number_id=phone_number_id,
        wamid=wamid,
        bsuid=bsuid,
        phone=phone,
        profile_name=profile_name,
        type=mtype,
        text=text,
        timestamp=_int(msg.get("timestamp")),
        system=system,
        media=media,
    )


def _parse_status(st: Dict[str, Any], phone_number_id: str) -> Optional[StatusUpdate]:
    wamid = _str(st.get("id"))
    status = _str(st.get("status"))
    if not wamid or not status:
        return None
    errors = st.get("errors") or []
    first = errors[0] if errors and isinstance(errors[0], dict) else {}
    return StatusUpdate(
        phone_number_id=phone_number_id,
        wamid=wamid,
        status=status,
        bsuid=_str(st.get("recipient_user_id")),
        phone=_str(st.get("recipient_id")),
        error_code=_str(first.get("code")),
        error_title=_str(first.get("title") or first.get("message")),
    )


def parse_webhook(body: Any) -> ParsedWebhook:
    out = ParsedWebhook()
    if not isinstance(body, dict):
        return out
    for entry in body.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            pnid = _str((value.get("metadata") or {}).get("phone_number_id")) or ""
            contacts = _contacts_by_key(value.get("contacts") or [])
            for msg in value.get("messages") or []:
                if isinstance(msg, dict):
                    parsed = _parse_message(msg, pnid, contacts)
                    if parsed:
                        out.messages.append(parsed)
            for st in value.get("statuses") or []:
                if isinstance(st, dict):
                    parsed_st = _parse_status(st, pnid)
                    if parsed_st:
                        out.statuses.append(parsed_st)
    return out
