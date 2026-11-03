"""Admin → Telegram: stato del gateway, verifica del token, assistenti, audit, quote.

Le variabili ``AION_TELEGRAM_*`` si salvano con ``POST /admin/settings`` come le
altre. Qui: stato e prova del token (``getMe``) per Impostazioni → Telegram, e la
pagina Admin → Telegram (tutti gli assistenti con le azioni dell'amministratore,
registro delle operazioni, quote per utente). I token non vengono mai restituiti
né scritti nei log.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from src.channels.telegram import runtime
from src.channels.telegram.config import get_telegram_settings

logger = logging.getLogger("aion.telegram")

router = APIRouter(prefix="/telegram", tags=["admin-telegram"])

_TOKEN_SHAPE = re.compile(r"^\d{5,16}:[A-Za-z0-9_-]{30,}$")
_TEST_TIMEOUT_SEC = 15.0


@router.get("/status")
async def telegram_status():
    settings = get_telegram_settings()
    gateway = runtime.get_gateway()
    factory = gateway.dispatcher["bot_factory"] if gateway is not None else None
    encryption_error: Optional[str] = None
    if settings.enabled:
        from src.channels.telegram.bots import token_encryption_error

        encryption_error = token_encryption_error()
    return {
        "enabled": settings.enabled,
        "token_configured": bool(settings.manager_token_value),
        "running": gateway is not None,
        # Username noto solo dopo un getMe riuscito: False = token rifiutato o rete giù.
        "connected": bool(gateway is not None and gateway.bot_username),
        "bot_username": gateway.bot_username if gateway is not None else None,
        "can_manage_bots": factory.can_manage_bots if factory is not None else None,
        "running_bots": gateway.supervisor.running if gateway is not None else 0,
        "encryption_ok": encryption_error is None,
        "encryption_error": encryption_error,
    }


class TokenTest(BaseModel):
    # Vuoto o mascherato ("***") = token già configurato.
    token: Optional[str] = None
    proxy_url: Optional[str] = None


def _is_placeholder(value: str) -> bool:
    return not value or set(value) <= {"*", "•", "…"}


@router.post("/test-token")
async def test_telegram_token(body: TokenTest):
    """``getMe`` con il token indicato: username del bot e gestione bot attiva."""
    settings = get_telegram_settings()
    token = (body.token or "").strip()
    if _is_placeholder(token):
        token = settings.manager_token_value or ""
    if not token:
        return {"ok": False, "error": "missing"}
    if not _TOKEN_SHAPE.match(token):
        return {"ok": False, "error": "malformed"}
    proxy = (body.proxy_url or "").strip() or settings.proxy_url

    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.exceptions import TelegramUnauthorizedError

    from src.channels.telegram.redact import redact

    bot = Bot(token=token, session=AiohttpSession(proxy=proxy) if proxy else None)
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=_TEST_TIMEOUT_SEC)
    except TelegramUnauthorizedError:
        return {"ok": False, "error": "unauthorized"}
    except Exception as e:  # noqa: BLE001 — rete, proxy, DNS
        logger.warning("telegram: verifica token fallita: %s", redact(e))
        return {"ok": False, "error": "network", "detail": redact(e)[:200]}
    finally:
        await bot.session.close()
    return {
        "ok": True,
        "id": me.id,
        "username": me.username,
        "can_manage_bots": bool(me.can_manage_bots),
    }


# ---------- assistenti (Admin → Telegram) ----------
async def _tables_ready() -> bool:
    if get_telegram_settings().enabled:
        return True
    from src.channels.telegram import _channel_tables_exist

    try:
        return await _channel_tables_exist()
    except Exception:  # noqa: BLE001
        return False


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    from datetime import timezone

    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


async def _users_by_id(ids) -> dict:
    from sqlalchemy import select

    from src.data.engine import get_async_session_maker
    from src.data.models import User

    ids = {i for i in ids if i}
    if not ids:
        return {}
    async with get_async_session_maker()() as session:
        rows = (await session.execute(select(User).where(User.id.in_(ids)))).scalars()
        return {
            u.id: {
                "row_id": u.id,
                "identifier": u.identifier,
                "display_name": u.display_name,
            }
            for u in rows
        }


async def _links() -> tuple[dict, dict]:
    """(per utente AION, per account Telegram) dei collegamenti esistenti."""
    from sqlalchemy import select

    from src.channels.telegram.models import TgLink
    from src.data.engine import get_async_session_maker

    async with get_async_session_maker()() as session:
        rows = (await session.execute(select(TgLink))).scalars().all()
    by_user = {
        r.aion_user_id: {"tg_user_id": int(r.tg_user_id), "tg_username": r.tg_username}
        for r in rows
    }
    by_tg = {int(r.tg_user_id): r.aion_user_id for r in rows}
    return by_user, by_tg


def _bots_repo():
    from src.channels.telegram.adapter import default_tenant_id
    from src.channels.telegram.bots import TelegramBots

    return TelegramBots(tenant_id=default_tenant_id())


@router.get("/bots")
async def admin_list_bots(include_deleted: bool = False):
    """Tutti gli assistenti dell'installazione (mai i token)."""
    settings = get_telegram_settings()
    if not await _tables_ready():
        return {"data": [], "default_quota": settings.max_bots_per_user}
    bots = await _bots_repo().list_admin(include_deleted=include_deleted)
    links_by_user, links_by_tg = await _links()
    pending_users = {
        links_by_tg.get(b.pending_owner_tg_user_id)
        for b in bots
        if b.pending_owner_tg_user_id is not None
    }
    users = await _users_by_id({b.owner_aion_user_id for b in bots} | pending_users)
    gateway = runtime.get_gateway()
    data = []
    for b in bots:
        owner = dict(
            users.get(b.owner_aion_user_id) or {"row_id": b.owner_aion_user_id}
        )
        owner["tg_username"] = (links_by_user.get(b.owner_aion_user_id) or {}).get(
            "tg_username"
        )
        pending = None
        if b.pending_owner_tg_user_id is not None:
            linked = links_by_tg.get(b.pending_owner_tg_user_id)
            pending = {
                "tg_user_id": b.pending_owner_tg_user_id,
                "linked_user": users.get(linked) if linked else None,
            }
        data.append(
            {
                "id": b.id,
                "bot_tg_id": b.bot_tg_id,
                "username": b.username,
                "name": b.name,
                "mode": b.mode,
                "status": b.status,
                "last_error": b.last_error,
                "profile_slug": b.profile_slug,
                "project_slug": b.project_slug,
                "owner": owner,
                "pending_owner": pending,
                "running": bool(
                    gateway is not None and gateway.supervisor.is_running(b.bot_tg_id)
                ),
                "created_at": _iso(b.created_at),
                "last_activity_at": _iso(b.last_activity_at),
            }
        )
    return {"data": data, "default_quota": settings.max_bots_per_user}


_BOT_ACTIONS = ("suspend", "resume", "delete", "reassign")


@router.post("/bots/{bot_id}/{action}")
async def admin_bot_action(bot_id: int, action: str):
    from fastapi import HTTPException

    from src.channels.telegram import lifecycle_factory
    from src.channels.telegram.bots import BotStatus

    if action not in _BOT_ACTIONS:
        raise HTTPException(404, detail={"code": "unknown_action"})
    if not await _tables_ready():
        raise HTTPException(409, detail={"code": "telegram_disabled"})
    factory, manager = await lifecycle_factory()
    info = await factory.bots.get(bot_id)
    if info is None or info.status == BotStatus.DELETED.value:
        raise HTTPException(404, detail={"code": "bot_not_found"})
    if action == "delete":
        await factory.delete(manager, info, actor_tg_user_id=None)
        return {
            "ok": True,
            "status": BotStatus.DELETED.value,
            # Senza gateway il token non si può revocare su Telegram.
            "revoked": manager is not None,
        }
    if action == "reassign":
        try:
            info = await factory.reassign_owner(manager, info)
        except ValueError as e:
            raise HTTPException(409, detail={"code": str(e)}) from e
        return {"ok": True, "status": info.status}
    info = await factory.admin_set_status(
        manager, info, active=action == "resume", actor="admin"
    )
    return {"ok": True, "status": info.status}


@router.get("/audit")
async def admin_audit(limit: int = 100):
    """Registro delle operazioni del canale (collegamenti, bot, quote)."""
    import json as _json

    from sqlalchemy import select

    from src.channels.telegram.models import TgAudit
    from src.data.engine import get_async_session_maker

    if not await _tables_ready():
        return {"data": []}
    limit = max(1, min(int(limit), 500))
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(TgAudit).order_by(TgAudit.id.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )
    users = await _users_by_id(r.aion_user_id for r in rows)
    data = []
    for r in rows:
        try:
            payload = _json.loads(r.payload_json) if r.payload_json else {}
        except ValueError:
            payload = {}
        data.append(
            {
                "id": r.id,
                "ts": _iso(r.ts),
                "action": r.action,
                "user": users.get(r.aion_user_id)
                or ({"row_id": r.aion_user_id} if r.aion_user_id else None),
                "actor_tg_user_id": r.actor_tg_user_id,
                "payload": payload,
            }
        )
    return {"data": data}


@router.get("/quotas")
async def admin_quotas():
    """Utenti con Telegram collegato, assistenti o quota personalizzata."""
    settings = get_telegram_settings()
    if not await _tables_ready():
        return {"default": settings.max_bots_per_user, "data": []}
    repo = _bots_repo()
    quotas = await repo.list_quotas()
    bots = await repo.list_admin()
    links_by_user, _ = await _links()
    counts: dict = {}
    for b in bots:
        counts[b.owner_aion_user_id] = counts.get(b.owner_aion_user_id, 0) + 1
    ids = set(quotas) | set(counts) | set(links_by_user)
    users = await _users_by_id(ids)
    data = [
        {
            **(users.get(uid) or {"row_id": uid}),
            "tg_username": (links_by_user.get(uid) or {}).get("tg_username"),
            "linked": uid in links_by_user,
            "bots": counts.get(uid, 0),
            "max_bots": quotas.get(uid),
        }
        for uid in sorted(
            ids, key=lambda u: ((users.get(u) or {}).get("identifier") or u).lower()
        )
    ]
    return {"default": settings.max_bots_per_user, "data": data}


class QuotaUpdate(BaseModel):
    # None = torna alla quota di default (AION_TELEGRAM_MAX_BOTS_PER_USER).
    max_bots: Optional[int] = None


@router.put("/quotas/{user_id}")
async def admin_set_quota(user_id: str, body: QuotaUpdate):
    from fastapi import HTTPException

    if body.max_bots is not None and not 0 <= body.max_bots <= 100:
        raise HTTPException(422, detail={"code": "invalid_quota"})
    if not await _tables_ready():
        raise HTTPException(409, detail={"code": "telegram_disabled"})
    if not await _users_by_id([user_id]):
        raise HTTPException(404, detail={"code": "user_not_found"})
    await _bots_repo().set_quota(user_id, body.max_bots, actor="admin")
    return {"ok": True, "max_bots": body.max_bots}
