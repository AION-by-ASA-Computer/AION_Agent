"""Tests for the Telegram webhook delivery mode.

Covers ``src/channels/telegram/webhook.py`` (secret/URL helpers, the
``WebhookReceiver`` lifecycle, de-duplication, the poller/receiver choice) and the
public endpoint ``POST /v1/channels/telegram/webhook/{bot_id}``
(``src/api/v1/telegram_webhook.py``). Telegram is faked: no network.
"""

from __future__ import annotations

import asyncio

import pytest
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.methods import SetWebhook
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.channels.telegram import config as tg_config
from src.channels.telegram import webhook as wh
from src.channels.telegram.config import TelegramSettings
from src.channels.telegram.poller import UpdatePoller

TOKEN = "123456789:AAbbccddeeffgghhiijjkkllmmnnooppqq"
BOT_ID = "123456789"


def _run(coro):
    return asyncio.run(coro)


class _FakeBot:
    """Records setWebhook calls; optionally fails with 401."""

    def __init__(self, unauthorized: bool = False):
        self.unauthorized = unauthorized
        self.set_calls = []
        self.deleted = 0

    async def set_webhook(self, **kwargs):
        if self.unauthorized:
            raise TelegramUnauthorizedError(
                method=SetWebhook(url="x"), message="Unauthorized"
            )
        self.set_calls.append(kwargs)
        return True

    async def delete_webhook(self, **kwargs):
        self.deleted += 1
        return True


class _FakeDispatcher:
    """Collects the update ids fed by the receiver."""

    def __init__(self):
        self.handled = []

    async def feed_update(self, bot, update):
        self.handled.append(update.update_id)

    def resolve_used_update_types(self):
        return ["message"]


@pytest.fixture
def public_base(monkeypatch):
    """Public API base as set by the tunnel script."""
    monkeypatch.delenv("AION_OAUTH_REDIRECT_BASE_URL", raising=False)
    monkeypatch.setenv("AION_PUBLIC_API_URL", "https://demo.trycloudflare.com/api")
    yield "https://demo.trycloudflare.com/api"


@pytest.fixture(autouse=True)
def _clean_state():
    """Each test starts with no registered receiver and default settings."""
    wh._receivers.clear()
    previous = tg_config.get_telegram_settings()
    yield
    wh._receivers.clear()
    tg_config.set_current_settings(previous)


# ---------- helpers ----------
def test_secret_is_stable_per_token_and_header_safe():
    """The secret is derived (same token → same secret) and uses allowed chars."""
    s1, s2 = wh.webhook_secret(TOKEN), wh.webhook_secret(TOKEN)
    assert s1 == s2 and s1 != wh.webhook_secret(TOKEN + "x")
    assert 1 <= len(s1) <= 256 and all(c in "0123456789abcdef" for c in s1)
    assert wh.bot_id_from_token(TOKEN) == BOT_ID


def test_webhook_url_uses_public_api_base(public_base):
    """The URL is the public API base + path + bot id, and is accepted as is."""
    url = wh.webhook_url_for(TOKEN)
    assert url == f"{public_base}/v1/channels/telegram/webhook/{BOT_ID}"
    assert wh.webhook_url_problem(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://demo.example.com/api/v1/channels/telegram/webhook/1",
        "https://localhost/api/v1/channels/telegram/webhook/1",
        "https://demo.example.com:9000/api/v1/channels/telegram/webhook/1",
    ],
)
def test_unusable_webhook_urls_are_reported(url):
    """Missing base, plain HTTP, loopback host and non-Telegram ports are flagged."""
    assert wh.webhook_url_problem(url)


def test_delivery_mode_setting_defaults_and_validation():
    """Blank means polling; only polling/webhook are accepted."""
    assert TelegramSettings().delivery_mode == "polling"
    assert TelegramSettings(delivery_mode="").delivery_mode == "polling"
    assert TelegramSettings(delivery_mode="Webhook").webhook_mode
    with pytest.raises(ValueError):
        TelegramSettings(delivery_mode="push")


def test_make_update_source_follows_delivery_mode(public_base):
    """Polling mode builds the poller, webhook mode the receiver."""
    dp, bot = _FakeDispatcher(), _FakeBot()
    polling = wh.make_update_source(
        bot, dp, name="m", token=TOKEN, settings=TelegramSettings()
    )
    hook = wh.make_update_source(
        bot,
        dp,
        name="m",
        token=TOKEN,
        settings=TelegramSettings(delivery_mode="webhook"),
    )
    assert isinstance(polling, UpdatePoller)
    assert isinstance(hook, wh.WebhookReceiver) and hook.url.endswith(f"/{BOT_ID}")


# ---------- receiver ----------
def test_receiver_registers_webhook_and_dedupes_updates(public_base):
    """run() calls setWebhook with URL+secret and serves updates once each."""

    async def scenario():
        bot, dp = _FakeBot(), _FakeDispatcher()
        rx = wh.WebhookReceiver(
            bot, dp, name="m", token=TOKEN, allowed_updates=["message"]
        )
        task = asyncio.create_task(rx.run())
        for _ in range(100):
            if rx.registered:
                break
            await asyncio.sleep(0.01)
        assert wh.get_receiver(BOT_ID) is rx
        assert rx.accept({"update_id": 7}) is True
        assert rx.accept({"update_id": 7}) is False  # re-delivery
        await asyncio.sleep(0.05)
        await rx.stop()
        await asyncio.wait_for(task, 1)
        return bot, dp, rx

    bot, dp, rx = _run(scenario())
    call = bot.set_calls[0]
    assert call["url"] == rx.url and call["secret_token"] == wh.webhook_secret(TOKEN)
    assert call["drop_pending_updates"] is False
    assert dp.handled == [7]
    assert wh.get_receiver(BOT_ID) is None  # unregistered on stop
    assert rx.accept({"update_id": 8}) is False  # stopped: nothing accepted


def test_receiver_reports_rejected_token(public_base):
    """A 401 on setWebhook ends run() with unauthorized, like the poller."""

    async def scenario():
        rx = wh.WebhookReceiver(
            _FakeBot(unauthorized=True), _FakeDispatcher(), name="m", token=TOKEN
        )
        await asyncio.wait_for(rx.run(), 1)
        return rx

    rx = _run(scenario())
    assert rx.unauthorized and not rx.registered


def test_receiver_without_public_url_records_problem(monkeypatch):
    """No public HTTPS base: setWebhook is not even tried, the reason is exposed."""
    for key in (
        "AION_OAUTH_REDIRECT_BASE_URL",
        "AION_PUBLIC_API_URL",
        "AION_FASTAPI_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    async def scenario():
        bot = _FakeBot()
        rx = wh.WebhookReceiver(bot, _FakeDispatcher(), name="m", token=TOKEN)
        task = asyncio.create_task(rx.run())
        await asyncio.sleep(0.05)
        await rx.stop()
        await asyncio.wait_for(task, 1)
        return bot, rx

    bot, rx = _run(scenario())
    assert bot.set_calls == [] and rx.last_error


# ---------- endpoint ----------
def _client() -> TestClient:
    from src.api.v1.telegram_webhook import router

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    return TestClient(app)


class _RecordingReceiver:
    """Stands in for a running receiver: real secret check, recorded payloads."""

    def __init__(self):
        self.accepted = []
        self._secret = wh.webhook_secret(TOKEN)

    def check_secret(self, received):
        return received == self._secret

    def accept(self, payload):
        self.accepted.append(payload)
        return True


def _webhook_settings():
    tg_config.set_current_settings(
        TelegramSettings(enabled=True, delivery_mode="webhook")
    )


def test_endpoint_accepts_update_with_valid_secret():
    """Right secret → 200 and the update reaches the receiver."""
    _webhook_settings()
    rx = _RecordingReceiver()
    wh._receivers[BOT_ID] = rx
    r = _client().post(
        f"/v1/channels/telegram/webhook/{BOT_ID}",
        json={"update_id": 1},
        headers={wh.SECRET_HEADER: wh.webhook_secret(TOKEN)},
    )
    assert r.status_code == 200 and rx.accepted == [{"update_id": 1}]


def test_endpoint_rejects_wrong_secret():
    """Missing or wrong secret → 401, nothing dispatched."""
    _webhook_settings()
    rx = _RecordingReceiver()
    wh._receivers[BOT_ID] = rx
    client = _client()
    assert (
        client.post(
            f"/v1/channels/telegram/webhook/{BOT_ID}", json={"update_id": 1}
        ).status_code
        == 401
    )
    r = client.post(
        f"/v1/channels/telegram/webhook/{BOT_ID}",
        json={"update_id": 1},
        headers={wh.SECRET_HEADER: "nope"},
    )
    assert r.status_code == 401 and rx.accepted == []


def test_endpoint_asks_retry_when_bot_not_served():
    """Unknown bot (gateway restarting) → 503, so Telegram re-delivers later."""
    _webhook_settings()
    r = _client().post("/v1/channels/telegram/webhook/42", json={"update_id": 1})
    assert r.status_code == 503


def test_endpoint_ignores_updates_in_polling_mode():
    """Leftover webhook while in polling mode: acknowledged and dropped."""
    tg_config.set_current_settings(TelegramSettings(enabled=True))
    rx = _RecordingReceiver()
    wh._receivers[BOT_ID] = rx
    r = _client().post(f"/v1/channels/telegram/webhook/{BOT_ID}", json={"update_id": 1})
    assert r.status_code == 200 and r.json().get("ignored") and rx.accepted == []
