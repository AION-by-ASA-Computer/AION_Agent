"""Link email per impostare la password: invito, reset, "Password dimenticata?".

L'admin non deve mai ricevere password o token: il token esiste solo nel corpo
dell'email (catturata da un SMTP finto).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from src.test.smtp_fakes import body_of, configure_smtp, install_fake_smtp, token_from

STRONG = "Str0ng!pass"


async def _setup(monkeypatch, tmp_path, *, smtp: bool = True):
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "x" * 40)
    monkeypatch.setenv("AION_CHAT_URL", "https://chat.example.com")
    monkeypatch.delenv("AION_DEFAULT_TENANT_ID", raising=False)
    monkeypatch.delenv("AION_SSO_FORCE_PASSWORD", raising=False)

    from src.auth.sso import login_mode
    from src.data import engine as engine_mod
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_async_session_maker, init_engine
    from src.data.models import User
    from src.notifications import smtp_settings

    monkeypatch.setattr(engine_mod, "_engine", None)
    monkeypatch.setattr(engine_mod, "_session_factory", None)
    login_mode._SETTINGS_CACHE.clear()
    login_mode._PENDING_CACHE.clear()
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
    fake = install_fake_smtp(monkeypatch)
    if smtp:
        await configure_smtp()
    return get_async_session_maker(), fake


def _auth(uid: str = "a1"):
    from src.api.auth_login import ChatAuthIdentity

    return ChatAuthIdentity(
        user_row_id=uid, identifier="root", via="chat_token", roles=["admin"]
    )


def _request(ip: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "client": (ip, 1234),
            "server": ("api.test", 80),
            "scheme": "http",
        }
    )


def _assert_no_secrets(payload, *tokens: str) -> None:
    dumped = json.dumps(payload, default=str)
    assert '"password":' not in dumped
    assert "set-password" not in dumped
    for t in tokens:
        assert t not in dumped


async def _create(identifier: str = "mario", email: str = "mario@x.io"):
    from src.api.admin import UserCreate, create_user

    return await create_user(
        UserCreate(identifier=identifier, email=email), request=None, auth=_auth()
    )


async def _user(sm, uid):
    from src.data.models import User

    async with sm() as session:
        return await session.get(User, uid)


@pytest.mark.anyio
async def test_create_user_sends_invite_without_exposing_it(monkeypatch, tmp_path):
    sm, fake = await _setup(monkeypatch, tmp_path)
    from src.auth.password_setup import consume_token, inspect_token
    from src.data.user_password import verify_password

    res = await _create()

    assert res["invite"]["sent"] is True
    assert len(fake.sent) == 1
    msg = fake.sent[0]
    assert msg["To"] == "mario@x.io"
    token = token_from(msg)
    assert body_of(msg).count("https://chat.example.com/set-password#token=") == 1
    _assert_no_secrets(res, token)
    assert (await _user(sm, res["id"])).password_hash is None

    info = await inspect_token(token)
    assert (info["purpose"], info["identifier"]) == ("invite", "mario")

    out = await consume_token(token, STRONG)
    assert out == {"status": "ok", "identifier": "mario", "is_admin": False}
    assert verify_password(STRONG, (await _user(sm, res["id"])).password_hash)


@pytest.mark.anyio
async def test_token_single_use_and_policy(monkeypatch, tmp_path):
    await _setup(monkeypatch, tmp_path)
    from src.auth.password_setup import SetupLinkError, consume_token

    await _create()
    from src.test.smtp_fakes import FakeSMTP

    token = token_from(FakeSMTP.sent[0])

    # Password debole: errore con le regole violate, il token resta valido.
    with pytest.raises(SetupLinkError) as e:
        await consume_token(token, "weak")
    assert e.value.code == "password_policy"
    assert "too_short" in e.value.violations

    await consume_token(token, STRONG)
    with pytest.raises(SetupLinkError) as e:
        await consume_token(token, STRONG)
    assert e.value.code == "token_invalid"


@pytest.mark.anyio
async def test_token_expired(monkeypatch, tmp_path):
    sm, fake = await _setup(monkeypatch, tmp_path)
    from sqlalchemy import update

    from src.auth.password_setup import SetupLinkError, inspect_token
    from src.data.models import PasswordSetupToken

    await _create()
    token = token_from(fake.sent[0])
    async with sm() as session:
        await session.execute(
            update(PasswordSetupToken).values(
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
            )
        )
        await session.commit()

    with pytest.raises(SetupLinkError) as e:
        await inspect_token(token)
    assert e.value.code == "token_expired"


@pytest.mark.anyio
async def test_password_link_reissue_invalidates_previous(monkeypatch, tmp_path):
    sm, fake = await _setup(monkeypatch, tmp_path)
    from src.api.admin import send_password_link
    from src.auth.password_setup import SetupLinkError, consume_token, inspect_token

    uid = (await _create())["id"]
    first = token_from(fake.sent[-1])

    res = await send_password_link(uid, request=None, auth=_auth())
    assert (res["purpose"], res["sent"]) == ("invite", True)
    second = token_from(fake.sent[-1])
    _assert_no_secrets(res, first, second)

    with pytest.raises(SetupLinkError):
        await inspect_token(first)
    await consume_token(second, STRONG)

    # Con la password impostata il link successivo e' un reset; la password
    # attuale resta valida finche' l'utente non ne sceglie un'altra.
    old_hash = (await _user(sm, uid)).password_hash
    res = await send_password_link(uid, request=None, auth=_auth())
    assert res["purpose"] == "reset"
    assert (await inspect_token(token_from(fake.sent[-1])))["purpose"] == "reset"
    assert (await _user(sm, uid)).password_hash == old_hash


@pytest.mark.anyio
async def test_create_user_requires_smtp_and_email(monkeypatch, tmp_path):
    sm, fake = await _setup(monkeypatch, tmp_path, smtp=False)
    from pydantic import ValidationError
    from sqlalchemy import select

    from src.api.admin import UserCreate
    from src.data.models import User

    with pytest.raises(ValidationError):
        UserCreate(identifier="mario")
    with pytest.raises(HTTPException) as e:
        await _create(email="not-an-email")
    assert e.value.status_code == 422

    with pytest.raises(HTTPException) as e:
        await _create()
    assert (e.value.status_code, e.value.detail) == (
        409,
        {"code": "smtp_not_configured"},
    )
    async with sm() as session:
        rows = (await session.execute(select(User.identifier))).scalars().all()
    assert "mario" not in rows
    assert fake.sent == []


@pytest.mark.anyio
async def test_send_failure_is_reported_and_link_kept(monkeypatch, tmp_path):
    sm, fake = await _setup(monkeypatch, tmp_path)
    import smtplib

    from src.auth.password_setup import active_links_by_user

    fake.fail_with = smtplib.SMTPRecipientsRefused({})
    res = await _create()

    assert res["invite"] == {"sent": False, "error": "smtp_send_failed"}
    links = await active_links_by_user("default")
    assert links[res["id"]]["send_error"] == "smtp_send_failed"


@pytest.mark.anyio
async def test_password_link_blocked_without_email(monkeypatch, tmp_path):
    sm, _ = await _setup(monkeypatch, tmp_path)
    from src.api.admin import send_password_link
    from src.data.models import User

    async with sm() as session:
        session.add(User(id="u2", tenant_id="default", identifier="noemail"))
        await session.commit()
    with pytest.raises(HTTPException) as e:
        await send_password_link("u2", request=None, auth=_auth())
    assert e.value.detail == {"code": "user_email_missing"}


@pytest.mark.anyio
async def test_list_users_shows_pending_invite(monkeypatch, tmp_path):
    await _setup(monkeypatch, tmp_path)
    from src.api.admin import list_users

    uid = (await _create())["id"]
    users = (await list_users())["users"]
    info = next(u for u in users if u["id"] == uid)
    assert info["setup_link_pending"] is True
    assert info["setup_link_purpose"] == "invite"
    assert info["setup_link_expires_at"]
    _assert_no_secrets(users)


@pytest.mark.anyio
async def test_delete_user_drops_tokens(monkeypatch, tmp_path):
    sm, _ = await _setup(monkeypatch, tmp_path)
    from sqlalchemy import func, select

    from src.api.admin import delete_user
    from src.data.models import PasswordSetupToken

    uid = (await _create())["id"]
    await delete_user(uid)
    async with sm() as session:
        n = (
            await session.execute(select(func.count()).select_from(PasswordSetupToken))
        ).scalar_one()
    assert n == 0


@pytest.mark.anyio
async def test_forgot_password_is_neutral(monkeypatch, tmp_path):
    sm, fake = await _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("AION_REDIS_URL", raising=False)
    from src.api.auth_password_setup import ForgotBody, forgot_password
    from src.data.user_password import create_password_user

    await create_password_user(
        tenant_id="default",
        identifier="anna",
        password=STRONG,
        email="anna@x.io",
    )

    async def ask(identifier: str, ip: str):
        bg = BackgroundTasks()
        res = await forgot_password(ForgotBody(identifier=identifier), _request(ip), bg)
        await bg()
        return res

    assert await ask("ghost", "10.0.0.1") == {"status": "accepted"}
    assert fake.sent == []
    # Per username o per email: stessa risposta, l'email parte con un reset.
    assert await ask("anna@x.io", "10.0.0.1") == {"status": "accepted"}
    assert len(fake.sent) == 1
    from src.auth.password_setup import inspect_token

    assert (await inspect_token(token_from(fake.sent[0])))["purpose"] == "reset"


@pytest.mark.anyio
async def test_forgot_password_rate_limits(monkeypatch, tmp_path):
    sm, fake = await _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("AION_REDIS_URL", raising=False)
    import src.api.auth_password_setup as aps
    from src.data.user_password import create_password_user

    monkeypatch.setattr(aps, "_FORGOT_LIMIT_PER_IP", 2)
    monkeypatch.setattr(aps, "_FORGOT_LIMIT_PER_ACCOUNT", 1)
    await create_password_user(
        tenant_id="default", identifier="luca", password=STRONG, email="luca@x.io"
    )

    async def ask(ip: str):
        bg = BackgroundTasks()
        await aps.forgot_password(aps.ForgotBody(identifier="luca"), _request(ip), bg)
        await bg()

    await ask("10.1.0.1")
    await ask("10.1.0.2")
    # Limite per account: una sola email nonostante due IP diversi.
    assert len(fake.sent) == 1

    await ask("10.1.0.3")
    await ask("10.1.0.3")
    with pytest.raises(HTTPException) as e:
        await ask("10.1.0.3")
    assert e.value.status_code == 429


@pytest.mark.anyio
async def test_forgot_password_hidden_without_smtp(monkeypatch, tmp_path):
    await _setup(monkeypatch, tmp_path, smtp=False)
    from src.api.auth_password_setup import password_reset_available

    assert await password_reset_available("default") is False
    await configure_smtp()
    assert await password_reset_available("default") is True
