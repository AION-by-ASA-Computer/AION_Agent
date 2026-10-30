"""Canale WhatsApp: webhook pubblico di Meta + collegamento dell'utente loggato.

- ``GET/POST /v1/channels/whatsapp/webhook``: senza auth, protetti dal verify
  token (handshake) e dalla firma ``X-Hub-Signature-256`` (eventi).
- ``/v1/me/whatsapp``: stato, codice ``COLLEGA`` con QR, scollegamento
  (chat-ui → Impostazioni → WhatsApp).

Setup e flusso completo: ``docs/integrations/whatsapp.md``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.channels.whatsapp import config_service, dispatcher, linking, store
from src.channels.whatsapp.payload import parse_webhook
from src.channels.whatsapp.signature import verify_signature

logger = logging.getLogger("aion.v1.whatsapp")

router = APIRouter(tags=["v1-whatsapp"])

# Meta invia al massimo 3 MB per notifica; un po' di margine.
MAX_WEBHOOK_BYTES = int(3.5 * 1024 * 1024)


@router.get("/channels/whatsapp/webhook", include_in_schema=False)
async def whatsapp_webhook_verify(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Handshake di Meta ("Verifica e salva" nella configurazione webhook)."""
    if hub_mode == "subscribe" and hub_verify_token:
        tenant_id = await config_service.find_tenant_by_verify_token(hub_verify_token)
        if tenant_id:
            await config_service.mark_webhook_verified(tenant_id)
            logger.info("WhatsApp webhook verified for tenant %s", tenant_id)
            return PlainTextResponse(hub_challenge or "")
    raise HTTPException(403, detail="verification_failed")


@router.post("/channels/whatsapp/webhook", include_in_schema=False)
async def whatsapp_webhook_receive(request: Request):
    """Eventi Meta: salva i messaggi (dedup per wamid) e risponde 200 subito.

    L'elaborazione (agente + risposta) avviene in background nel dispatcher:
    Meta ritenta per giorni se non riceve 200 in pochi secondi.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, detail="payload_too_large")
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, detail="payload_too_large")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = None
    parsed = parse_webhook(body)
    signature = request.headers.get("x-hub-signature-256")

    for pnid in parsed.phone_number_ids:
        cfg = await config_service.get_channel_by_phone_number_id(pnid)
        if cfg is None:
            # Numero non configurato qui: 200 così Meta non ritenta all'infinito.
            continue
        if not verify_signature(raw, signature, cfg.app_secret):
            logger.warning("WhatsApp webhook: invalid signature")
            raise HTTPException(403, detail="invalid_signature")
        await config_service.touch_webhook(cfg.tenant_id)
        if config_service.force_disabled() or not cfg.enabled:
            continue
        for st in parsed.statuses:
            if st.phone_number_id == pnid:
                await store.apply_status(st)
        for msg in parsed.messages:
            if msg.phone_number_id != pnid:
                continue
            if await store.insert_inbound(cfg.tenant_id, msg):
                dispatcher.enqueue(cfg.tenant_id, msg.wamid)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Utente loggato (chat-ui)
# ---------------------------------------------------------------------------


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


@router.get("/me/whatsapp", tags=["v1-me-whatsapp"])
async def me_whatsapp_status(auth: ChatAuthIdentity = Depends(_me)):
    tenant_id = config_service.default_tenant_id()
    cfg = await config_service.get_channel(tenant_id)
    ident = await linking.get_identity_for_user(tenant_id, auth.user_row_id or "")
    return {
        "channel_enabled": bool(cfg and cfg.active),
        "display_phone_number": cfg.display_phone_number if cfg else None,
        "linked": ident is not None,
        "wa_profile_name": ident.wa_profile_name if ident else None,
        "phone_hint": linking.phone_hint(ident.phone_e164) if ident else None,
        "linked_at": _iso(ident.linked_at) if ident else None,
    }


@router.post("/me/whatsapp/link-code", tags=["v1-me-whatsapp"])
async def me_whatsapp_link_code(auth: ChatAuthIdentity = Depends(_me)):
    tenant_id = config_service.default_tenant_id()
    cfg = await config_service.get_channel(tenant_id)
    if cfg is None or not cfg.active:
        raise HTTPException(
            409,
            detail={
                "code": "whatsapp_channel_disabled",
                "message": "WhatsApp channel is not active",
            },
        )
    link = await linking.create_link_code(
        tenant_id, auth.user_row_id or "", cfg.display_phone_number
    )
    return {
        "code": link.code,
        "expires_at": _iso(link.expires_at),
        "wa_link": link.wa_link,
        "qr_svg": link.qr_svg,
    }


@router.delete("/me/whatsapp", tags=["v1-me-whatsapp"])
async def me_whatsapp_unlink(auth: ChatAuthIdentity = Depends(_me)):
    await linking.unlink(
        config_service.default_tenant_id(), user_id=auth.user_row_id or ""
    )
    return {"ok": True}
