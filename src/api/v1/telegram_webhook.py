"""Public webhook endpoint of the Telegram channel (``delivery_mode = "webhook"``).

``POST /v1/channels/telegram/webhook/{bot_id}`` is called by Telegram for every
update of the manager bot and of the personal assistants, once they registered
their webhook (``src/channels/telegram/webhook.py``). No AION auth: requests are
authenticated by the per-bot secret Telegram echoes in
``X-Telegram-Bot-Api-Secret-Token``. Behind Caddy the public URL is
``https://<domain>/api/v1/channels/telegram/webhook/<bot id>``.

Counterpart of the WhatsApp webhook in ``src/api/v1/whatsapp.py``. With the channel
off or in polling mode nothing of aiogram is imported here.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request

from src.channels.telegram.config import get_telegram_settings

logger = logging.getLogger("aion.telegram")

router = APIRouter(tags=["v1-telegram-webhook"])

# Telegram updates are small JSON documents (files are fetched separately with
# getFile): anything bigger is not from Telegram.
MAX_WEBHOOK_BYTES = 1024 * 1024


@router.post("/channels/telegram/webhook/{bot_id}", include_in_schema=False)
async def telegram_webhook(bot_id: str, request: Request):
    """Receive one update and hand it to the bot's receiver; answers fast.

    Status codes are chosen for Telegram's retry behaviour (it re-delivers on any
    non-2xx): 200 also when the update is dropped on purpose (channel off, polling
    mode, duplicate), 503 while the bot is not served yet (gateway restarting) so
    the update is retried, 401 on a wrong secret.
    """
    settings = get_telegram_settings()
    if not settings.enabled or not settings.webhook_mode:
        # Leftover webhook (channel disabled or switched to polling): drop quietly,
        # the next polling start removes the webhook on Telegram's side.
        return {"ok": True, "ignored": True}

    from src.channels.telegram.webhook import SECRET_HEADER, get_receiver

    receiver = get_receiver(bot_id)
    if receiver is None:
        raise HTTPException(503, detail="bot not served")
    if not receiver.check_secret(request.headers.get(SECRET_HEADER)):
        logger.warning("telegram webhook: secret non valido per il bot %s", bot_id)
        raise HTTPException(401, detail="invalid secret")

    # Size check before parsing (Content-Length can be missing: re-checked on body).
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, detail="payload too large")
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, detail="payload too large")

    try:
        payload = json.loads(raw)
        receiver.accept(payload)
    except Exception as e:  # noqa: BLE001 — authenticated but unparsable: don't loop
        # The sender proved the secret, so this is Telegram: a 4xx would only make
        # it re-deliver the same broken update. Log and acknowledge.
        logger.error(
            "telegram webhook: update non valido per il bot %s: %s",
            bot_id,
            type(e).__name__,
        )
    return {"ok": True}
