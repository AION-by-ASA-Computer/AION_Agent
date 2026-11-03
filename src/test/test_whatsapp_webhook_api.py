"""Webhook pubblico (``/v1/channels/whatsapp/webhook``) e ``/v1/me/whatsapp``."""

import json

import httpx
import pytest
from fastapi import FastAPI

from src.test.whatsapp_test_helpers import (
    PNID,
    TENANT,
    configure_channel,
    fixture_bytes,
    load_fixture,
    signed_headers,
)

URL = "/v1/channels/whatsapp/webhook"


def _app(user_row_id="u1", via="chat_token") -> FastAPI:
    from src.api.auth_login import ChatAuthIdentity, require_chat_auth
    from src.api.v1 import whatsapp

    app = FastAPI()
    app.include_router(whatsapp.router, prefix="/v1")
    app.dependency_overrides[require_chat_auth] = lambda: ChatAuthIdentity(
        user_row_id=user_row_id, via=via
    )
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    )


@pytest.fixture
def enqueued(monkeypatch):
    from src.channels.whatsapp import dispatcher

    calls = []
    monkeypatch.setattr(dispatcher, "enqueue", lambda t, w: calls.append((t, w)))
    return calls


async def _message_row(wamid):
    from src.data.engine import get_async_session_maker
    from src.data.models import WhatsAppMessage

    async with get_async_session_maker()() as session:
        return await session.get(WhatsAppMessage, wamid)


@pytest.mark.anyio
async def test_verify_handshake(wa_db, monkeypatch, tmp_path):
    cfg = await configure_channel(validated=False, enabled=False)
    from src.channels.whatsapp import config_service

    async with _client(_app()) as c:
        ok = await c.get(
            URL,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": cfg.verify_token,
                "hub.challenge": "1158201444",
            },
        )
        assert ok.status_code == 200
        assert ok.text == "1158201444"
        assert ok.headers["content-type"].startswith("text/plain")

        bad = await c.get(
            URL,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "x",
            },
        )
        assert bad.status_code == 403
        assert (await c.get(URL)).status_code == 403

    config_service.invalidate_cache()
    assert (await config_service.get_channel(TENANT)).webhook_verified_at is not None


@pytest.mark.anyio
async def test_post_valid_message_is_stored_and_enqueued(
    wa_db, monkeypatch, tmp_path, enqueued
):
    await configure_channel()
    raw = fixture_bytes("text_with_phone")

    async with _client(_app()) as c:
        r = await c.post(URL, content=raw, headers=signed_headers(raw))
        assert r.status_code == 200 and r.json() == {"ok": True}
        # Retry di Meta con lo stesso wamid: ignorato.
        r2 = await c.post(URL, content=raw, headers=signed_headers(raw))
        assert r2.status_code == 200

    assert enqueued == [(TENANT, "wamid.TEXT1")]
    row = await _message_row("wamid.TEXT1")
    assert row.direction == "in" and row.status == "received"
    assert json.loads(row.payload_json)["text"] == "Quanti ordini ieri?"

    from src.channels.whatsapp import config_service

    config_service.invalidate_cache()
    assert (await config_service.get_channel(TENANT)).last_webhook_at is not None


@pytest.mark.anyio
async def test_post_invalid_signature_rejected(wa_db, monkeypatch, tmp_path, enqueued):
    await configure_channel()
    raw = fixture_bytes("text_with_phone")

    async with _client(_app()) as c:
        bad = await c.post(URL, content=raw, headers=signed_headers(raw, "wrong"))
        missing = await c.post(
            URL, content=raw, headers={"content-type": "application/json"}
        )
    assert bad.status_code == 403 and missing.status_code == 403
    assert enqueued == []
    assert await _message_row("wamid.TEXT1") is None


@pytest.mark.anyio
async def test_post_unknown_phone_number_id_ignored(
    wa_db, monkeypatch, tmp_path, enqueued
):
    await configure_channel()
    body = load_fixture("text_with_phone")
    body["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "999"
    raw = json.dumps(body).encode()

    async with _client(_app()) as c:
        # Nessuna firma valida possibile per un numero sconosciuto: 200 lo stesso.
        r = await c.post(URL, content=raw, headers={"x-hub-signature-256": "x"})
    assert r.status_code == 200
    assert enqueued == []


@pytest.mark.anyio
async def test_post_disabled_channel_does_nothing(
    wa_db, monkeypatch, tmp_path, enqueued
):
    await configure_channel(enabled=False)
    raw = fixture_bytes("text_with_phone")

    async with _client(_app()) as c:
        r = await c.post(URL, content=raw, headers=signed_headers(raw))
    assert r.status_code == 200
    assert enqueued == []
    assert await _message_row("wamid.TEXT1") is None


@pytest.mark.anyio
async def test_post_force_disabled(wa_db, monkeypatch, tmp_path, enqueued):
    await configure_channel()
    monkeypatch.setenv("AION_WHATSAPP_FORCE_DISABLE", "1")
    raw = fixture_bytes("text_with_phone")

    async with _client(_app()) as c:
        r = await c.post(URL, content=raw, headers=signed_headers(raw))
    assert r.status_code == 200
    assert enqueued == []


@pytest.mark.anyio
async def test_post_status_updates_outbound(wa_db, monkeypatch, tmp_path, enqueued):
    await configure_channel()
    from src.channels.whatsapp import store

    await store.record_outbound(TENANT, "wamid.OUT1", bsuid="IT.1")
    await store.record_outbound(TENANT, "wamid.OUT2", bsuid="IT.1")
    raw = fixture_bytes("status")

    async with _client(_app()) as c:
        assert (
            await c.post(URL, content=raw, headers=signed_headers(raw))
        ).status_code == 200

    assert (await _message_row("wamid.OUT1")).status == "delivered"
    out2 = await _message_row("wamid.OUT2")
    assert (out2.status, out2.error_code) == ("failed", "131047")

    # Stato più vecchio arrivato dopo: non torna indietro.
    from src.channels.whatsapp.payload import StatusUpdate

    await store.apply_status(StatusUpdate(PNID, "wamid.OUT1", "sent"))
    assert (await _message_row("wamid.OUT1")).status == "delivered"


@pytest.mark.anyio
async def test_post_too_large(wa_db, monkeypatch, tmp_path, enqueued):
    from src.api.v1.whatsapp import MAX_WEBHOOK_BYTES

    async with _client(_app()) as c:
        r = await c.post(URL, content=b"x" * (MAX_WEBHOOK_BYTES + 1))
    assert r.status_code == 413


@pytest.mark.anyio
async def test_me_endpoints(wa_db, monkeypatch, tmp_path):

    async with _client(_app()) as c:
        status = (await c.get("/v1/me/whatsapp")).json()
        assert status["channel_enabled"] is False and status["linked"] is False
        r = await c.post("/v1/me/whatsapp/link-code")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "whatsapp_channel_disabled"

    await configure_channel()
    async with _client(_app()) as c:
        status = (await c.get("/v1/me/whatsapp")).json()
        assert status["channel_enabled"] is True
        assert status["display_phone_number"] == "+39 02 1234 5678"

        link = (await c.post("/v1/me/whatsapp/link-code")).json()
        assert set(link) == {"code", "expires_at", "wa_link", "qr_svg"}
        assert link["wa_link"].startswith("https://wa.me/390212345678?text=COLLEGA")

        from src.channels.whatsapp import linking

        assert (
            await linking.consume_code(
                TENANT,
                code=link["code"],
                bsuid="IT.1",
                phone="393331112233",
                profile_name="Mario",
            )
        ).ok
        status = (await c.get("/v1/me/whatsapp")).json()
        assert status["linked"] is True
        assert status["wa_profile_name"] == "Mario"
        assert status["phone_hint"] == "••• 233"

        assert (await c.delete("/v1/me/whatsapp")).json() == {"ok": True}
        assert (await c.get("/v1/me/whatsapp")).json()["linked"] is False


@pytest.mark.anyio
async def test_me_requires_user_token(wa_db, monkeypatch, tmp_path):
    async with _client(_app(user_row_id=None, via="open")) as c:
        r = await c.get("/v1/me/whatsapp")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "user_token_required"
