"""Test login desktop (PKCE + loopback): /auth/desktop/handoff e /exchange."""

import asyncio
import base64
import hashlib

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.data.bootstrap import ensure_bootstrap_schema

VERIFIER = "v" * 43
GOOD = "http://127.0.0.1:53211/callback"


def _challenge(v=VERIFIER):
    d = hashlib.sha256(v.encode()).digest()
    return base64.urlsafe_b64encode(d).decode().rstrip("=")


def _with_db(fn):
    def wrapper(tmp_path, monkeypatch):
        async def run():
            import src.api.auth_desktop as ad
            import src.api.auth_login as al
            import src.api.auth_sso as sso
            import src.auth.mfa.totp as totp
            import src.auth.sso.login_mode as lm
            import src.chat_auth as ca
            import src.data.engine as engine
            from src.data.user_password import create_password_user

            monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
            monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "x" * 40)
            monkeypatch.delenv("AION_DESKTOP_REDIRECT_ALLOWLIST", raising=False)
            eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'd.db'}")
            await ensure_bootstrap_schema(eng)
            sm = async_sessionmaker(eng, expire_on_commit=False)
            monkeypatch.setattr(engine, "get_async_session_maker", lambda: sm)
            for mod in (lm, totp, ca, ad, sso):
                monkeypatch.setattr(mod, "get_async_session_maker", lambda: sm)
            lm._SETTINGS_CACHE.clear()
            await create_password_user(
                tenant_id="default",
                identifier="alice",
                password="pw-alice",
                session_maker=sm,
            )
            try:
                await fn(ad, al, sso, sm)
            finally:
                await eng.dispose()

        asyncio.run(run())

    wrapper.__name__ = fn.__name__
    return wrapper


async def _login(al):
    res = await al.login(al.LoginBody(username="alice", password="pw-alice"))
    return f"Bearer {res['access_token']}"


def _body(ad, **kw):
    d = dict(challenge=_challenge(), state="st", redirect=GOOD)
    d.update(kw)
    return ad.HandoffBody(**d)


async def _code_of(exc_ctx):
    return exc_ctx.value.detail["code"]


@_with_db
async def test_handoff_requires_bearer_and_rejects_api_key(ad, al, sso, sm):
    for hdr in (None, "Basic abc", "Bearer garbage", "Bearer aion_sk_fake123"):
        with pytest.raises(HTTPException) as e:
            await ad.desktop_handoff(_body(ad), hdr)
        assert e.value.status_code == 401


@_with_db
async def test_handoff_redirect_allowlist(ad, al, sso, sm):
    auth = await _login(al)
    for ok in (
        GOOD,
        "http://[::1]:5000/callback",
        "http://localhost:8080/callback",
    ):
        r = await ad.desktop_handoff(_body(ad, redirect=ok), auth)
        assert r["code"] and r["expires_in"] == 60
    for bad in (
        "https://127.0.0.1:5000/callback",
        "https://evil.com/callback",
        "http://127.0.0.1.evil.com/callback",
        "http://127.0.0.1:5000/other",
        "http://127.0.0.1:5000/callback/",
        "http://user@127.0.0.1:5000/callback",
        "http://127.0.0.1:5000/callback?x=1",
        "http://127.0.0.1:5000/callback#f",
        "http://evil.com/?h=127.0.0.1/callback",
        "",
    ):
        with pytest.raises(HTTPException) as e:
            await ad.desktop_handoff(_body(ad, redirect=bad), auth)
        assert e.value.status_code == 400
        assert e.value.detail == {"code": "redirect_not_allowed"}
    # allow-list custom: URL esatti, il loopback di default non vale piu'
    import os

    os.environ["AION_DESKTOP_REDIRECT_ALLOWLIST"] = (
        "https://app.example.com/cb, myapp://callback"
    )
    assert (await ad.desktop_handoff(_body(ad, redirect="myapp://callback"), auth))[
        "code"
    ]
    try:
        for bad in (GOOD, "https://app.example.com/cb/x", "https://app.example.com"):
            with pytest.raises(HTTPException) as e:
                await ad.desktop_handoff(_body(ad, redirect=bad), auth)
            assert e.value.detail == {"code": "redirect_not_allowed"}
    finally:
        os.environ.pop("AION_DESKTOP_REDIRECT_ALLOWLIST", None)


@_with_db
async def test_handoff_challenge_and_state_validation(ad, al, sso, sm):
    auth = await _login(al)
    for kw in (
        {"challenge": "short"},
        {"challenge": "!" * 43},
        {"challenge": "a" * 44},
        {"state": ""},
        {"state": "s" * 257},
    ):
        with pytest.raises(HTTPException) as e:
            await ad.desktop_handoff(_body(ad, **kw), auth)
        assert e.value.detail == {"code": "invalid_challenge"}


@_with_db
async def test_exchange_success_returns_working_token(ad, al, sso, sm):
    auth = await _login(al)
    h = await ad.desktop_handoff(_body(ad), auth)
    res = await ad.desktop_exchange(
        ad.ExchangeBody(code=h["code"], code_verifier=VERIFIER)
    )
    assert res["identifier"] == "alice"
    assert res["expires_in"] > 0 and res["expires_at"].endswith("Z")
    assert "must_change_password" in res and res["sso_link_required"] is False
    parsed = al.verify_chat_token(res["access_token"])
    assert parsed and parsed["identifier"] == "alice"
    me = await al.me(f"Bearer {res['access_token']}")
    assert me["identifier"] == "alice"


@_with_db
async def test_exchange_wrong_verifier_burns_code(ad, al, sso, sm):
    h = await ad.desktop_handoff(_body(ad), await _login(al))
    with pytest.raises(HTTPException) as e:
        await ad.desktop_exchange(ad.ExchangeBody(code=h["code"], code_verifier="x" * 43))
    assert e.value.detail == {"code": "invalid_verifier"}
    with pytest.raises(HTTPException) as e:
        await ad.desktop_exchange(
            ad.ExchangeBody(code=h["code"], code_verifier=VERIFIER)
        )
    assert e.value.detail == {"code": "code_already_used"}


@_with_db
async def test_exchange_replay_and_unknown_code(ad, al, sso, sm):
    h = await ad.desktop_handoff(_body(ad), await _login(al))
    b = ad.ExchangeBody(code=h["code"], code_verifier=VERIFIER)
    await ad.desktop_exchange(b)
    with pytest.raises(HTTPException) as e:
        await ad.desktop_exchange(b)
    assert e.value.detail == {"code": "code_already_used"}
    with pytest.raises(HTTPException) as e:
        await ad.desktop_exchange(ad.ExchangeBody(code="nope", code_verifier=VERIFIER))
    assert e.value.detail == {"code": "invalid_code"}


@_with_db
async def test_exchange_expired_code(ad, al, sso, sm):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from src.data.models import SsoAuthState

    h = await ad.desktop_handoff(_body(ad), await _login(al))
    async with sm() as s:
        await s.execute(
            update(SsoAuthState).values(
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        )
        await s.commit()
    with pytest.raises(HTTPException) as e:
        await ad.desktop_exchange(
            ad.ExchangeBody(code=h["code"], code_verifier=VERIFIER)
        )
    assert e.value.detail == {"code": "code_expired"}


@_with_db
async def test_codes_not_interchangeable_with_sso_exchange(ad, al, sso, sm):
    h = await ad.desktop_handoff(_body(ad), await _login(al))
    with pytest.raises(HTTPException) as e:
        await sso.sso_exchange(sso.ExchangeBody(code=h["code"]))
    assert e.value.detail == {"code": "invalid_code"}
    # il codice desktop non e' stato consumato dal tentativo sso
    await ad.desktop_exchange(ad.ExchangeBody(code=h["code"], code_verifier=VERIFIER))

    sso_code = await sso._create_handoff_code(
        {"access_token": "t", "user_id": "u", "return_to": "/"}, "default"
    )
    with pytest.raises(HTTPException) as e:
        await ad.desktop_exchange(
            ad.ExchangeBody(code=sso_code, code_verifier=VERIFIER)
        )
    assert e.value.detail == {"code": "invalid_code"}


def test_routes_registered():
    from src.api.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/auth/desktop/handoff" in paths and "/auth/desktop/exchange" in paths
