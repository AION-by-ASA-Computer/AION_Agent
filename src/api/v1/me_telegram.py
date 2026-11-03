"""Collegamento Telegram dell'utente loggato (chat-ui → Impostazioni → Telegram).

Solo token chat, come le API key personali: il collegamento è un'azione dell'utente.
La logica sta in ``src/channels/telegram``; con ``AION_TELEGRAM_ENABLED=0`` gli
endpoint rispondono ``enabled: false`` e non importano aiogram.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.channels.telegram import runtime
from src.channels.telegram.accounts import LinkInfo, TelegramAccounts
from src.channels.telegram.config import get_telegram_settings

router = APIRouter(prefix="/me/telegram", tags=["v1-me-telegram"])


def _me(auth: ChatAuthIdentity = Depends(require_chat_auth)) -> ChatAuthIdentity:
    if auth.via != "chat_token" or not auth.user_row_id:
        raise HTTPException(
            403,
            detail={
                "code": "user_token_required",
                "message": "User login token required",
            },
        )
    return auth


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _serialize_link(link: Optional[LinkInfo]) -> Optional[dict]:
    if link is None:
        return None
    return {
        "tg_user_id": link.tg_user_id,
        "tg_username": link.tg_username,
        "tg_first_name": link.tg_first_name,
        "linked_at": _iso(link.created_at),
        "last_seen_at": _iso(link.last_seen_at),
    }


def _accounts() -> TelegramAccounts:
    from src.channels.telegram.adapter import default_tenant_id

    return TelegramAccounts(tenant_id=default_tenant_id())


def _qr_data_uri(url: str) -> Optional[str]:
    try:
        import segno

        return segno.make(url, error="m").svg_data_uri(scale=6, border=2)
    except Exception:  # noqa: BLE001 — il QR è un aiuto: il link resta utilizzabile
        return None


def _require_enabled() -> None:
    if not get_telegram_settings().enabled:
        raise HTTPException(
            409,
            detail={
                "code": "telegram_disabled",
                "message": "Telegram integration is not enabled on this server",
            },
        )


@router.get("")
async def get_my_telegram(auth: ChatAuthIdentity = Depends(_me)):
    settings = get_telegram_settings()
    bot_username = runtime.manager_username() if settings.enabled else None
    # Con il flag spento le tabelle del canale possono non esistere (DB nuovi).
    link = (
        await _accounts().get_link_for_user(auth.user_row_id)
        if settings.enabled
        else None
    )
    return {
        "enabled": settings.enabled,
        "available": bool(bot_username),
        "bot_username": bot_username,
        "pairing_ttl_min": settings.pairing_code_ttl_min,
        "manager_chat": settings.manager_chat,
        "link": _serialize_link(link),
    }


@router.post("/link", status_code=201)
async def create_my_telegram_link(auth: ChatAuthIdentity = Depends(_me)):
    _require_enabled()
    settings = get_telegram_settings()
    bot_username = runtime.manager_username()
    if not bot_username:
        raise HTTPException(
            503,
            detail={
                "code": "telegram_unavailable",
                "message": "Telegram bot is not connected yet, retry shortly",
            },
        )
    code = await _accounts().create_pairing_code(
        auth.user_row_id, ttl_min=settings.pairing_code_ttl_min
    )
    url = f"https://t.me/{bot_username}?start={code.start_param}"
    return {
        "url": url,
        "bot_username": bot_username,
        "expires_at": _iso(code.expires_at),
        "qr_svg": _qr_data_uri(url),
    }


@router.delete("/link")
async def delete_my_telegram_link(auth: ChatAuthIdentity = Depends(_me)):
    _require_enabled()
    info = await _accounts().unlink(aion_user_id=auth.user_row_id, source="chat_ui")
    if info is None:
        raise HTTPException(
            404,
            detail={"code": "not_linked", "message": "No Telegram account linked"},
        )
    from src.channels.telegram import lifecycle_factory
    from src.channels.telegram.handlers.account import suspended_note

    # Gli assistenti dell'utente smettono di ascoltare finché non ricollega l'account.
    factory, _ = await lifecycle_factory()
    suspended = await factory.suspend_for_unlink(auth.user_row_id)
    gateway = runtime.get_gateway()
    if gateway is not None:
        # In background: la risposta HTTP non aspetta api.telegram.org.
        asyncio.create_task(
            gateway.notify(
                info.tg_user_id,
                "🔓 Questo account Telegram è stato scollegato da AION dalla Chat UI."
                + suspended_note(suspended),
            )
        )
    return {"ok": True, "suspended_bots": len(suspended)}


_PREVIEW_CHARS = 120


@router.get("/conversations")
async def list_my_telegram_conversations(
    limit: int = Query(50, ge=1, le=200),
    auth: ChatAuthIdentity = Depends(_me),
):
    """Chat avviate da Telegram (``metadata.source = "telegram"``): escluse dalla
    sidebar e mostrate solo in Impostazioni → Telegram."""
    from sqlalchemy import select

    from src.channels.telegram.adapter import SOURCE, default_tenant_id
    from src.data.engine import get_async_session_maker
    from src.data.models import Conversation, Message
    from src.identity import sanitize_user_id

    user_id = sanitize_user_id(auth.identifier or auth.user_row_id)
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(Conversation)
                    .where(
                        Conversation.tenant_id == default_tenant_id(),
                        Conversation.user_id == user_id,
                        Conversation.archived_at.is_(None),
                        Conversation.parent_conversation_id.is_(None),
                    )
                    .order_by(Conversation.updated_at.desc())
                    .limit(limit * 4)
                )
            )
            .scalars()
            .all()
        )
        metas = {r.id: json.loads(r.metadata_json or "{}") for r in rows}
        convs = [r for r in rows if metas[r.id].get("source") == SOURCE][:limit]
        # Primo messaggio dell'utente come anteprima (le chat Telegram spesso non hanno titolo).
        previews: dict = {}
        if convs:
            msgs = await session.execute(
                select(Message.conversation_id, Message.content)
                .where(
                    Message.conversation_id.in_([c.id for c in convs]),
                    Message.role == "user",
                )
                .order_by(Message.conversation_id, Message.seq)
            )
            for conv_id, content in msgs.all():
                previews.setdefault(conv_id, (content or "").strip()[:_PREVIEW_CHARS])
    return {
        "data": [
            {
                "id": c.id,
                "title": c.title,
                "preview": previews.get(c.id) or None,
                "profile_slug": c.profile_slug,
                # Username dell'assistente personale; None = chat sul bot manager.
                "telegram_bot": metas[c.id].get("telegram_bot"),
                # Titolo del gruppo per le domande fatte in un gruppo Telegram.
                "telegram_chat": metas[c.id].get("telegram_chat"),
                "message_count": c.message_count,
                "created_at": _iso(c.created_at),
                "updated_at": _iso(c.updated_at),
            }
            for c in convs
        ]
    }


@router.get("/bots")
async def list_my_telegram_bots(auth: ChatAuthIdentity = Depends(_me)):
    """Assistenti personali dell'utente (creati con /newbot), esclusi gli eliminati."""
    settings = get_telegram_settings()
    if not settings.enabled:
        return {"data": []}
    from src.agent_profile import profile_manager
    from src.channels.telegram.adapter import default_tenant_id
    from src.channels.telegram.bots import BotStatus, TelegramBots

    bots = await TelegramBots(tenant_id=default_tenant_id()).list_for_owner(
        auth.user_row_id
    )

    def profile_name(slug: Optional[str]) -> Optional[str]:
        if not slug:
            return None
        p = profile_manager.get_profile(slug)
        return (getattr(p, "name", None) or slug) if p else slug

    return {
        "data": [
            {
                "id": b.id,
                "username": b.username,
                "name": b.name,
                "status": b.status,
                "mode": b.mode,
                "profile_slug": b.profile_slug,
                "profile_name": profile_name(b.profile_slug),
                "project_slug": b.project_slug,
                "url": (
                    f"https://t.me/{b.username}"
                    if b.username and b.status == BotStatus.ACTIVE.value
                    else None
                ),
                "created_at": _iso(b.created_at),
            }
            for b in bots
        ]
    }
