"""Webhook delivery for the Telegram channel (alternative to long polling).

With ``delivery_mode = "webhook"`` (Admin → Telegram) every bot of the channel —
the manager and each personal assistant — registers with Telegram a public URL
``<public API base>/v1/channels/telegram/webhook/<bot id>`` (``setWebhook``) instead
of keeping a ``getUpdates`` long poll open. Telegram then POSTs each update there;
``src/api/v1/me_telegram.py`` (``telegram_webhook``) looks up the receiver of that
bot in this module's registry and hands the update over.

``WebhookReceiver`` exposes the same ``run()`` / ``stop()`` / ``unauthorized``
surface as :class:`~src.channels.telegram.poller.UpdatePoller`, so the gateway and
the ``BotSupervisor`` pick one or the other (:func:`make_update_source`) and the
rest of the channel (dispatchers, handlers, turn queue) is unchanged.

Design notes:

- **Fast ack.** Agent turns last up to ``turn_timeout_sec``; Telegram expects a
  quick answer and re-delivers on timeout/errors. The endpoint therefore answers
  200 as soon as the update is accepted and the handler runs in a background task.
  Trade-off vs polling: an update still running when AION stops is not re-delivered
  (in polling the offset is committed only after handling). Fine for tests through
  the tunnel; polling stays the default for production.
- **Duplicates.** Telegram may deliver the same update twice (e.g. a retry after a
  slow answer): recent ``update_id``s are remembered per bot and skipped.
- **Authentication.** Telegram echoes the ``secret_token`` given to ``setWebhook``
  in the ``X-Telegram-Bot-Api-Secret-Token`` header. It is derived from the bot
  token (HMAC), so nothing extra is stored and a token rotation changes it too.
- **Lifecycle.** On AION shutdown the webhook stays registered: Telegram keeps the
  updates (and retries) until AION is back. When a bot stops being served for good
  (suspended, deleted, new token) the supervisor removes its webhook
  (:func:`remove_webhook`). Switching back to polling removes it as well, since the
  pollers call ``delete_webhook`` at start.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Union

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError
from aiogram.types import Update

from src.channels.telegram.config import TelegramSettings
from src.channels.telegram.poller import UpdatePoller
from src.channels.telegram.redact import redact

logger = logging.getLogger("aion.telegram")

# Path of the public endpoint, relative to the API base (Caddy adds/strips /api).
WEBHOOK_PATH = "/v1/channels/telegram/webhook"
# Header in which Telegram echoes the secret_token of setWebhook.
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

_SET_RETRY_START_SEC = 2.0
_SET_RETRY_MAX_SEC = 60.0
# Update ids remembered per bot to drop re-deliveries; Telegram re-sends only
# recent updates, so a small window is enough.
_DEDUP_WINDOW = 2048

# bot id (as in the URL) -> receiver currently serving it. One process only
# (uvicorn --workers 1), so an in-memory registry is the source of truth.
_receivers: Dict[str, "WebhookReceiver"] = {}


# ---------- helpers ----------
def bot_id_from_token(token: str) -> str:
    """Numeric bot id, i.e. the part of the token before ``:`` (public, used in the URL)."""
    return (token or "").split(":", 1)[0].strip()


def webhook_secret(token: str) -> str:
    """Secret for ``setWebhook``/header check, derived from the bot token.

    Telegram allows 1-256 chars in ``[A-Za-z0-9_-]``: a hex HMAC fits. Derived (not
    random) so it survives restarts without storage and changes with the token.
    """
    return hmac.new(
        token.encode("utf-8"), b"aion-telegram-webhook", hashlib.sha256
    ).hexdigest()


def public_webhook_base() -> str:
    """``<public API base>/v1/channels/telegram/webhook`` or "" when no public base.

    Same source as the WhatsApp callback URL (``_public_api_base_url``: the tunnel
    script overrides ``AION_PUBLIC_API_URL``/``AION_OAUTH_REDIRECT_BASE_URL``).
    """
    from src.api.public_urls import _public_api_base_url

    base = _public_api_base_url()
    return f"{base}{WEBHOOK_PATH}" if base else ""


def webhook_url_for(token: str) -> str:
    """Full webhook URL of a bot, "" when no public base is configured."""
    base = public_webhook_base()
    return f"{base}/{bot_id_from_token(token)}" if base else ""


def webhook_url_problem(url: str) -> Optional[str]:
    """Why Telegram would refuse ``url`` (None if it looks usable).

    Telegram accepts only HTTPS on ports 443, 80, 88 or 8443; a loopback host is
    never reachable from Telegram's servers.
    """
    from urllib.parse import urlparse

    if not url:
        return (
            "URL pubblico dell'API non configurato (AION_PUBLIC_API_URL): "
            "il webhook non può essere registrato"
        )
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return f"il webhook richiede HTTPS ({url})"
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost"):
        return f"host non raggiungibile da Telegram ({host})"
    if parsed.port not in (None, 443, 80, 88, 8443):
        return f"porta {parsed.port} non ammessa da Telegram (443, 80, 88, 8443)"
    return None


def get_receiver(bot_id: str) -> Optional["WebhookReceiver"]:
    """Receiver serving ``bot_id`` in this process, if any (used by the endpoint)."""
    return _receivers.get(bot_id)


async def remove_webhook(bot: Bot) -> None:
    """Unregister the webhook of a bot that is no longer served (best effort)."""
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:  # noqa: BLE001 — token revoked, network: nothing to do
        logger.info("telegram: rimozione webhook non riuscita: %s", redact(e))


# ---------- receiver ----------
class WebhookReceiver:
    """Serves one bot through the webhook; drop-in replacement of ``UpdatePoller``."""

    def __init__(
        self,
        bot: Bot,
        dispatcher: Dispatcher,
        *,
        name: str,
        token: str,
        shutdown_grace_sec: float = 10.0,
        allowed_updates: Optional[List[str]] = None,
        max_connections: Optional[int] = None,
    ) -> None:
        self.bot = bot
        self.dispatcher = dispatcher
        self.name = name
        self.bot_id = bot_id_from_token(token)
        self.url = webhook_url_for(token)
        self._secret = webhook_secret(token)
        self.shutdown_grace_sec = max(0.0, float(shutdown_grace_sec))
        self.allowed_updates = allowed_updates
        self.max_connections = max_connections
        # Same meaning as UpdatePoller.unauthorized: token rejected (401).
        self.unauthorized = False
        # Last setWebhook problem, shown in Admin → Telegram; None when registered.
        self.last_error: Optional[str] = None
        self.registered = False
        self._inflight: set[asyncio.Task] = set()
        self._seen: "OrderedDict[int, None]" = OrderedDict()
        self._stopping = asyncio.Event()

    # ---------- lifecycle (same contract as UpdatePoller) ----------
    async def run(self) -> None:
        """Register the webhook (retrying), then serve until :meth:`stop`.

        Returns early with ``unauthorized = True`` when Telegram rejects the token,
        like the poller does, so the supervisor can mark the bot as broken.
        """
        _receivers[self.bot_id] = self
        try:
            if not await self._register():
                return
            await self._stopping.wait()
        finally:
            if _receivers.get(self.bot_id) is self:
                _receivers.pop(self.bot_id, None)

    async def stop(self) -> None:
        """Stop accepting updates and give running handlers ``shutdown_grace_sec``.

        The webhook stays registered on Telegram (see module docstring).
        """
        self._stopping.set()
        if _receivers.get(self.bot_id) is self:
            _receivers.pop(self.bot_id, None)
        if self._inflight:
            _, pending = await asyncio.wait(
                list(self._inflight), timeout=self.shutdown_grace_sec or None
            )
            if pending:
                logger.warning(
                    "telegram[%s]: %d update ancora in corso allo shutdown: "
                    "con il webhook non verranno riconsegnati",
                    self.name,
                    len(pending),
                )
            for task in pending:
                task.cancel()

    # ---------- incoming updates ----------
    def check_secret(self, received: Optional[str]) -> bool:
        """Constant-time check of the ``X-Telegram-Bot-Api-Secret-Token`` header."""
        return bool(received) and hmac.compare_digest(received, self._secret)

    def accept(self, payload: Union[Dict[str, Any], Update]) -> bool:
        """Schedule one update for handling; False if duplicate or stopping.

        Called by the HTTP endpoint, which answers 200 right after: handling runs
        in a background task tracked for the shutdown grace period.
        """
        if self._stopping.is_set():
            return False
        update = (
            payload
            if isinstance(payload, Update)
            else Update.model_validate(payload, context={"bot": self.bot})
        )
        uid = update.update_id
        if uid in self._seen:
            return False
        self._seen[uid] = None
        while len(self._seen) > _DEDUP_WINDOW:
            self._seen.popitem(last=False)
        task = asyncio.create_task(
            self._handle(update), name=f"telegram-{self.name}-update-{uid}"
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return True

    async def _handle(self, update: Update) -> None:
        try:
            await self.dispatcher.feed_update(self.bot, update)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — a broken update must not stop the bot
            logger.error(
                "telegram[%s]: errore gestendo update %s: %s",
                self.name,
                update.update_id,
                redact(e),
            )

    # ---------- internals ----------
    async def _register(self) -> bool:
        """``setWebhook`` with backoff; False on 401 or when stopping."""
        delay = _SET_RETRY_START_SEC
        while not self._stopping.is_set():
            problem = webhook_url_problem(self.url)
            if problem is None:
                try:
                    await self.bot.set_webhook(
                        url=self.url,
                        secret_token=self._secret,
                        allowed_updates=self.allowed_updates,
                        max_connections=self.max_connections,
                        # Keep what Telegram queued while AION was down/polling.
                        drop_pending_updates=False,
                    )
                    self.registered = True
                    self.last_error = None
                    logger.info(
                        "telegram[%s]: webhook registrato su %s", self.name, self.url
                    )
                    return True
                except TelegramUnauthorizedError:
                    self.unauthorized = True
                    logger.error(
                        "telegram[%s]: token non valido (401), webhook non registrato",
                        self.name,
                    )
                    return False
                except asyncio.CancelledError:
                    raise
                except TelegramBadRequest as e:
                    # E.g. "bad webhook: Failed to resolve host": usually the tunnel
                    # DNS is not propagated yet, so it is retried like a network error.
                    problem = f"setWebhook rifiutato: {redact(e)}"
                except Exception as e:  # noqa: BLE001 — network/proxy
                    problem = f"setWebhook fallito ({type(e).__name__}: {redact(e)})"
            self.last_error = problem
            logger.warning(
                "telegram[%s]: %s, nuovo tentativo tra %.0fs", self.name, problem, delay
            )
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, _SET_RETRY_MAX_SEC)
        return False


UpdateSource = Union[UpdatePoller, WebhookReceiver]


def make_update_source(
    bot: Bot,
    dispatcher: Dispatcher,
    *,
    name: str,
    token: str,
    settings: TelegramSettings,
) -> UpdateSource:
    """Poller or webhook receiver for one bot, according to ``settings.delivery_mode``."""
    allowed = dispatcher.resolve_used_update_types()
    if settings.webhook_mode:
        return WebhookReceiver(
            bot,
            dispatcher,
            name=name,
            token=token,
            shutdown_grace_sec=settings.shutdown_grace_sec,
            allowed_updates=allowed,
        )
    return UpdatePoller(
        bot,
        dispatcher,
        name=name,
        polling_timeout=settings.polling_timeout,
        shutdown_grace_sec=settings.shutdown_grace_sec,
        allowed_updates=allowed,
    )
