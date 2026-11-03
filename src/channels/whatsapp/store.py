"""Tabella ``whatsapp_messages``: dedup dei webhook, coda persistente, stati.

Il webhook salva ogni messaggio in entrata *prima* di rispondere 200 a Meta:
se il backend si riavvia durante un turno, ``pending_inbound`` lo riprende.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.data.engine import get_async_session_maker
from src.data.models import WhatsAppMessage

from .payload import InboundMessage, StatusUpdate

logger = logging.getLogger("aion.whatsapp.store")

# Gli stati di consegna arrivano anche fuori ordine: mai tornare indietro.
_OUT_RANK = {"sent": 1, "delivered": 2, "read": 3, "failed": 4}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def insert_inbound(tenant_id: str, msg: InboundMessage) -> bool:
    """True se nuovo; False se il ``wamid`` era già stato ricevuto (retry Meta)."""
    async with get_async_session_maker()() as session:
        if await session.get(WhatsAppMessage, msg.wamid) is not None:
            return False
        session.add(
            WhatsAppMessage(
                wamid=msg.wamid,
                tenant_id=tenant_id,
                direction="in",
                bsuid=msg.sender_key,
                status="received",
                payload_json=json.dumps(msg.to_dict()),
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False
    return True


async def record_outbound(
    tenant_id: str,
    wamid: Optional[str],
    *,
    bsuid: Optional[str],
    conversation_id: Optional[str] = None,
) -> None:
    if not wamid:
        return
    async with get_async_session_maker()() as session:
        if await session.get(WhatsAppMessage, wamid) is not None:
            return
        session.add(
            WhatsAppMessage(
                wamid=wamid,
                tenant_id=tenant_id,
                direction="out",
                bsuid=bsuid,
                conversation_id=conversation_id,
                status="sent",
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()


async def apply_status(st: StatusUpdate) -> None:
    async with get_async_session_maker()() as session:
        row = await session.get(WhatsAppMessage, st.wamid)
        if row is None or row.direction != "out":
            return
        if _OUT_RANK.get(st.status, 0) < _OUT_RANK.get(row.status, 0):
            return
        row.status = st.status[:16]
        if st.error_code:
            row.error_code = st.error_code[:32]
        await session.commit()
    if st.status == "failed":
        logger.warning(
            "WhatsApp outbound %s failed: %s %s",
            st.wamid,
            st.error_code,
            st.error_title,
        )


@dataclass
class StoredInbound:
    tenant_id: str
    status: str
    message: Optional[InboundMessage]


async def load_inbound(wamid: str) -> Optional[StoredInbound]:
    async with get_async_session_maker()() as session:
        row = await session.get(WhatsAppMessage, wamid)
    if row is None or row.direction != "in":
        return None
    msg = None
    if row.payload_json:
        try:
            msg = InboundMessage.from_dict(json.loads(row.payload_json))
        except (TypeError, ValueError):
            logger.warning("Unreadable WhatsApp payload for %s", wamid)
    return StoredInbound(tenant_id=row.tenant_id, status=row.status, message=msg)


async def set_inbound_status(
    wamid: str,
    status: str,
    *,
    conversation_id: Optional[str] = None,
    error_code: Optional[str] = None,
    clear_payload: bool = False,
) -> None:
    values: dict = {"status": status, "updated_at": _now()}
    if conversation_id:
        values["conversation_id"] = conversation_id
    if error_code:
        values["error_code"] = error_code[:32]
    if clear_payload:
        values["payload_json"] = None
    async with get_async_session_maker()() as session:
        await session.execute(
            update(WhatsAppMessage)
            .where(WhatsAppMessage.wamid == wamid)
            .values(**values)
        )
        await session.commit()


async def pending_inbound(max_age: timedelta) -> List[Tuple[str, str]]:
    """Messaggi non completati: quelli recenti da riprendere, i vecchi → failed."""
    cutoff = _now() - max_age
    resume: List[Tuple[str, str]] = []
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(WhatsAppMessage)
                    .where(
                        WhatsAppMessage.direction == "in",
                        WhatsAppMessage.status.in_(("received", "processing")),
                    )
                    .order_by(WhatsAppMessage.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            created = row.created_at
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created is not None and created < cutoff:
                row.status = "failed"
                row.error_code = "expired"
                row.payload_json = None
            else:
                resume.append((row.tenant_id, row.wamid))
        await session.commit()
    return resume
