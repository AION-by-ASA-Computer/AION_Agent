"""/admin/whatsapp: segreti mascherati, verifica con Meta (simulata), attivazione."""

import httpx
import pytest
from fastapi import HTTPException

from src.test.whatsapp_test_helpers import (
    ACCESS_TOKEN,
    APP_SECRET,
    PNID,
    TENANT,
    WABA_ID,
)


def _auth():
    from src.api.auth_login import ChatAuthIdentity

    return ChatAuthIdentity(user_row_id="u1", via="chat_token", roles=["admin"])


def _body(**kw):
    from src.api.admin_whatsapp import WhatsAppConfigBody

    data = {
        "waba_id": WABA_ID,
        "phone_number_id": PNID,
        "access_token": ACCESS_TOKEN,
        "app_secret": APP_SECRET,
    }
    data.update(kw)
    return WhatsAppConfigBody(**data)


class MetaMock:
    """Graph API finta: numero su Cloud API, nessuna app sottoscritta all'inizio."""

    def __init__(self, *, platform="CLOUD_API", token_ok=True):
        self.platform = platform
        self.token_ok = token_ok
        self.subscribed = False
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
        if not self.token_ok:
            return httpx.Response(
                401,
                json={
                    "error": {
                        "message": "Invalid OAuth access token",
                        "code": 190,
                    }
                },
            )
        path = request.url.path
        if path.endswith(f"/{PNID}"):
            return httpx.Response(
                200,
                json={
                    "id": PNID,
                    "display_phone_number": "+39 02 1234 5678",
                    "verified_name": "ACME S.p.A.",
                    "quality_rating": "GREEN",
                    "platform_type": self.platform,
                },
            )
        if path.endswith(f"/{WABA_ID}/subscribed_apps"):
            if request.method == "POST":
                self.subscribed = True
                return httpx.Response(200, json={"success": True})
            data = (
                [{"whatsapp_business_api_data": {"name": "AION", "id": "1"}}]
                if self.subscribed
                else []
            )
            return httpx.Response(200, json={"data": data})
        return httpx.Response(404, json={"error": {"message": "nope", "code": 100}})


@pytest.fixture
def meta(monkeypatch):
    from src.channels.whatsapp import dispatcher
    from src.channels.whatsapp.graph_client import GraphClient

    mock = MetaMock()
    transport = httpx.MockTransport(mock.handler)
    monkeypatch.setattr(
        dispatcher,
        "graph_client_factory",
        lambda token: GraphClient(token, "v26.0", transport=transport),
    )
    return mock


@pytest.mark.anyio
async def test_get_empty_config(wa_db):
    from src.api.admin_whatsapp import get_whatsapp_config

    view = await get_whatsapp_config()
    assert view["configured"] is False and view["enabled"] is False
    assert view["webhook_url"] == (
        "https://aion.example.com/api/v1/channels/whatsapp/webhook"
    )
    assert view["graph_api_version"] == "v26.0"


@pytest.mark.anyio
async def test_put_masks_secrets_and_keeps_them_when_empty(wa_db):
    from src.api.admin_whatsapp import put_whatsapp_config
    from src.channels.whatsapp import config_service

    view = await put_whatsapp_config(_body())
    assert view["configured"] is True
    assert ACCESS_TOKEN not in str(view) and APP_SECRET not in str(view)
    assert view["access_token_hint"].endswith(ACCESS_TOKEN[-4:])
    assert view["verify_token"]

    # Segreti vuoti = invariati.
    await put_whatsapp_config(_body(access_token="", app_secret=None))
    cfg = await config_service.get_channel(TENANT)
    assert cfg.access_token == ACCESS_TOKEN and cfg.app_secret == APP_SECRET

    # Nel DB sono cifrati.
    from src.data.engine import get_async_session_maker
    from src.data.models import WhatsAppChannel
    from sqlalchemy import select

    async with get_async_session_maker()() as session:
        row = (await session.execute(select(WhatsAppChannel))).scalars().one()
    assert ACCESS_TOKEN not in (row.access_token_encrypted or "")
    assert APP_SECRET not in (row.app_secret_encrypted or "")


@pytest.mark.anyio
async def test_put_unknown_profile(wa_db):
    from src.api.admin_whatsapp import put_whatsapp_config

    with pytest.raises(HTTPException) as e:
        await put_whatsapp_config(_body(default_profile_slug="non_esiste_xyz"))
    assert e.value.status_code == 400
    assert e.value.detail["code"] == "profile_not_found"

    view = await put_whatsapp_config(_body(default_profile_slug="aion_std"))
    assert view["default_profile_slug"] == "aion_std"


@pytest.mark.anyio
async def test_validate_requires_config(wa_db):
    from src.api.admin_whatsapp import validate_whatsapp

    with pytest.raises(HTTPException) as e:
        await validate_whatsapp(auth=_auth())
    assert e.value.status_code == 409


@pytest.mark.anyio
async def test_enable_requires_validation(wa_db):
    from src.api.admin_whatsapp import (
        WhatsAppEnableBody,
        enable_whatsapp,
        put_whatsapp_config,
    )

    with pytest.raises(HTTPException) as e:
        await enable_whatsapp(WhatsAppEnableBody(enabled=True))
    assert e.value.detail == {"code": "not_configured"}

    await put_whatsapp_config(_body())
    with pytest.raises(HTTPException) as e:
        await enable_whatsapp(WhatsAppEnableBody(enabled=True))
    assert e.value.status_code == 409
    assert e.value.detail == {"code": "not_validated"}


@pytest.mark.anyio
async def test_full_validation_flow(wa_db, meta, monkeypatch):
    from src.api.admin_whatsapp import (
        WhatsAppEnableBody,
        enable_whatsapp,
        put_whatsapp_config,
        regenerate_verify_token,
        validate_whatsapp,
    )
    from src.channels.whatsapp import config_service

    await put_whatsapp_config(_body())

    # Webhook non ancora verificato da Meta: checklist incompleta.
    res = await validate_whatsapp(auth=_auth())
    assert res["ok"] is False
    checks = {c["id"]: c for c in res["checks"]}
    assert (
        checks["token_phone"]["ok"] and "ACME S.p.A." in checks["token_phone"]["detail"]
    )
    assert checks["cloud_api_registered"]["ok"]
    assert checks["app_subscribed"]["ok"]
    assert "subscribed now" in checks["app_subscribed"]["detail"]
    assert checks["webhook_verified"]["ok"] is False
    assert res["channel"]["validated_at"] is None
    assert res["channel"]["last_error"].startswith("webhook_verified")
    assert res["channel"]["display_phone_number"] == "+39 02 1234 5678"
    assert ("POST", f"/v26.0/{WABA_ID}/subscribed_apps") in meta.requests

    await config_service.mark_webhook_verified(TENANT)
    res = await validate_whatsapp(auth=_auth())
    assert res["ok"] is True
    assert res["channel"]["validated_at"] is not None
    assert res["channel"]["last_error"] is None

    assert await enable_whatsapp(WhatsAppEnableBody(enabled=True)) == {
        "ok": True,
        "enabled": True,
    }
    assert (await config_service.get_channel(TENANT)).active

    # Kill switch: non si può riattivare.
    await enable_whatsapp(WhatsAppEnableBody(enabled=False))
    monkeypatch.setenv("AION_WHATSAPP_FORCE_DISABLE", "1")
    with pytest.raises(HTTPException) as e:
        await enable_whatsapp(WhatsAppEnableBody(enabled=True))
    assert e.value.detail == {"code": "force_disabled"}
    monkeypatch.delenv("AION_WHATSAPP_FORCE_DISABLE")

    # Nuovo verify token → il webhook va riverificato.
    token = (await regenerate_verify_token())["verify_token"]
    cfg = await config_service.get_channel(TENANT)
    assert cfg.verify_token == token and cfg.webhook_verified_at is None

    # Cambio credenziali → canale disattivato e da riverificare.
    await enable_whatsapp(WhatsAppEnableBody(enabled=True))
    await put_whatsapp_config(_body(access_token="EAAG-new-token"))
    cfg = await config_service.get_channel(TENANT)
    assert cfg.enabled is False and cfg.validated_at is None


@pytest.mark.anyio
async def test_validate_reports_meta_errors(wa_db, meta):
    from src.api.admin_whatsapp import put_whatsapp_config, validate_whatsapp

    await put_whatsapp_config(_body())
    meta.token_ok = False
    res = await validate_whatsapp(auth=_auth())
    checks = {c["id"]: c for c in res["checks"]}
    assert res["ok"] is False
    assert checks["token_phone"]["ok"] is False
    assert "[190] Invalid OAuth access token" in checks["token_phone"]["detail"]
    assert checks["cloud_api_registered"]["detail"] == "skipped"
    assert res["channel"]["last_error"].startswith("token_phone")


@pytest.mark.anyio
async def test_validate_on_premise_number_fails(wa_db, meta):
    from src.api.admin_whatsapp import put_whatsapp_config, validate_whatsapp

    await put_whatsapp_config(_body())
    meta.platform = "ON_PREMISE"
    res = await validate_whatsapp(auth=_auth())
    checks = {c["id"]: c for c in res["checks"]}
    assert checks["cloud_api_registered"] == {
        "id": "cloud_api_registered",
        "ok": False,
        "detail": "ON_PREMISE",
    }


@pytest.mark.anyio
async def test_identities_list_and_delete(wa_db):
    from src.api.admin_whatsapp import (
        delete_whatsapp_identity,
        list_whatsapp_identities,
    )
    from src.channels.whatsapp import linking

    assert (await list_whatsapp_identities()) == {"items": []}
    code = (await linking.create_link_code(TENANT, "u1", None)).code
    assert (
        await linking.consume_code(
            TENANT, code=code, bsuid="IT.1", phone="393331112233", profile_name="M"
        )
    ).ok

    (item,) = (await list_whatsapp_identities())["items"]
    assert item["user_identifier"] == "mario" and item["phone_hint"] == "••• 233"

    assert await delete_whatsapp_identity(item["id"]) == {"ok": True}
    with pytest.raises(HTTPException) as e:
        await delete_whatsapp_identity(item["id"])
    assert e.value.status_code == 404
