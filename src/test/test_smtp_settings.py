"""/admin/smtp: la password SMTP e' di sola scrittura e salvata cifrata."""

from __future__ import annotations

import json
import smtplib

import pytest
from fastapi import HTTPException

from src.test.smtp_fakes import install_fake_smtp

SECRET = "smtp-S3cret!"


async def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.delenv("AION_DEFAULT_TENANT_ID", raising=False)

    from src.data import engine as engine_mod
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_async_session_maker, init_engine
    from src.data.models import User
    from src.notifications import smtp_settings

    monkeypatch.setattr(engine_mod, "_engine", None)
    monkeypatch.setattr(engine_mod, "_session_factory", None)
    smtp_settings._CACHE.clear()
    eng = init_engine()
    await ensure_bootstrap_schema(eng)
    async with get_async_session_maker()() as session:
        session.add(
            User(
                id="a1",
                tenant_id="default",
                identifier="root",
                email="root@x.io",
                roles_json='["admin"]',
            )
        )
        await session.commit()
    return get_async_session_maker(), install_fake_smtp(monkeypatch)


def _auth():
    from src.api.auth_login import ChatAuthIdentity

    return ChatAuthIdentity(
        user_row_id="a1", identifier="root", via="chat_token", roles=["admin"]
    )


def _body(**kw):
    from src.api.admin_smtp import SmtpSettingsBody

    base = {
        "host": "smtp.test",
        "port": 587,
        "security": "starttls",
        "username": "mailer",
        "from_address": "NoReply@Aion.test",
    }
    base.update(kw)
    return SmtpSettingsBody(**base)


@pytest.mark.anyio
async def test_password_write_only_and_encrypted(monkeypatch, tmp_path):
    sm, _ = await _setup(monkeypatch, tmp_path)
    from src.api.admin_smtp import get_smtp, put_smtp
    from src.data.models import SmtpSettings
    from src.notifications.smtp_settings import get_smtp_config

    res = await put_smtp(_body(password=SECRET), auth=_auth())
    assert res["configured"] and res["password_present"]
    assert res["from_address"] == "noreply@aion.test"
    assert SECRET not in json.dumps(res, default=str)
    assert SECRET not in json.dumps(await get_smtp(auth=_auth()), default=str)

    async with sm() as session:
        row = await session.get(SmtpSettings, "default")
    assert row.password_encrypted and SECRET not in row.password_encrypted

    # Password vuota = mantieni quella salvata.
    await put_smtp(_body(password="", host="smtp2.test"), auth=_auth())
    cfg = await get_smtp_config("default")
    assert (cfg.host, cfg.password) == ("smtp2.test", SECRET)

    res = await put_smtp(_body(clear_password=True), auth=_auth())
    assert res["password_present"] is False


@pytest.mark.anyio
async def test_put_validation(monkeypatch, tmp_path):
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smtp import put_smtp

    for kw, code in (
        ({"security": "tls13"}, "invalid_security"),
        ({"host": "bad host"}, "invalid_host"),
        ({"from_address": "nope"}, "invalid_from_address"),
        ({"reply_to": "nope"}, "invalid_reply_to"),
        ({"email_language": "fr"}, "invalid_language"),
    ):
        with pytest.raises(HTTPException) as e:
            await put_smtp(_body(**kw), auth=_auth())
        assert e.value.detail == {"code": code}


@pytest.mark.anyio
async def test_send_test_email(monkeypatch, tmp_path):
    _, fake = await _setup(monkeypatch, tmp_path)
    from src.api.admin_smtp import SmtpTestBody, get_smtp, put_smtp, test_smtp

    with pytest.raises(HTTPException) as e:
        await test_smtp(SmtpTestBody(), auth=_auth())
    assert e.value.detail == {"code": "smtp_not_configured"}

    await put_smtp(_body(password=SECRET), auth=_auth())
    res = await test_smtp(SmtpTestBody(), auth=_auth())
    assert res == {"ok": True, "error": None, "to": "root@x.io"}
    assert fake.sent[0]["To"] == "root@x.io"
    assert fake.logins == [("mailer", SECRET)]
    assert (await get_smtp(auth=_auth()))["last_test_ok"] is True

    fake.fail_with = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    res = await test_smtp(SmtpTestBody(to="other@x.io"), auth=_auth())
    assert res == {"ok": False, "error": "smtp_auth_failed", "to": "other@x.io"}
    state = await get_smtp(auth=_auth())
    assert (state["last_test_ok"], state["last_test_error"]) == (
        False,
        "smtp_auth_failed",
    )


@pytest.mark.anyio
async def test_disabled_smtp_is_not_configured(monkeypatch, tmp_path):
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smtp import put_smtp
    from src.notifications.smtp_settings import smtp_configured

    res = await put_smtp(_body(enabled=False), auth=_auth())
    assert res["configured"] is False
    assert await smtp_configured("default") is False
