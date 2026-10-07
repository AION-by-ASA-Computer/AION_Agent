import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pyotp
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.data.bootstrap import ensure_bootstrap_schema


@asynccontextmanager
async def _env(tmp_path: Path, monkeypatch):
    import src.auth.sso.login_mode as lm
    import src.data.engine as engine
    from src.data.models import AuthSettings
    from src.data.user_password import create_password_user

    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "x" * 40)
    monkeypatch.delenv("AION_2FA_FORCE_DISABLE", raising=False)
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mfa.db'}")
    await ensure_bootstrap_schema(eng)
    sm = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(engine, "get_async_session_maker", lambda: sm)
    for mod in (lm,):
        monkeypatch.setattr(mod, "get_async_session_maker", lambda: sm)
    import src.auth.mfa.totp as totp
    import src.api.auth_login as al
    import src.api.auth_mfa as am
    import src.api.admin_auth_mode as aam

    import src.chat_auth as ca

    for mod in (totp, am, aam, ca):
        monkeypatch.setattr(mod, "get_async_session_maker", lambda: sm)
    lm._SETTINGS_CACHE.clear()
    uid = await create_password_user(
        tenant_id="default", identifier="alice", password="pw-alice", session_maker=sm
    )

    async def set_required(value: bool, mode: str = "password"):
        async with sm() as s:
            row = await s.get(AuthSettings, "default")
            if row is None:
                row = AuthSettings(tenant_id="default")
                s.add(row)
            row.totp_required = value
            row.login_mode = mode
            await s.commit()
        lm._invalidate_cache("default")

    yield {"sm": sm, "uid": uid, "set_required": set_required, "al": al, "am": am, "totp": totp}
    await eng.dispose()


def with_env(fn):
    """Esegue il test async in un solo event loop con DB temporaneo."""

    def wrapper(tmp_path, monkeypatch):
        async def run():
            async with _env(tmp_path, monkeypatch) as env:
                await fn(env, monkeypatch)

        asyncio.run(run())

    wrapper.__name__ = fn.__name__
    return wrapper


async def _login(al):
    return await al.login(al.LoginBody(username="alice", password="pw-alice"))


@with_env
async def test_login_unchanged_when_2fa_off(env, monkeypatch):
    res = await _login(env["al"])
    assert "access_token" in res and "mfa_required" not in res


@with_env
async def test_enroll_then_verify_flow(env, monkeypatch):
    al, am, totp = env["al"], env["am"], env["totp"]
    await env["set_required"](True)

    res = await _login(al)
    assert res["mfa_required"] and res["mfa_stage"] == "enroll"
    assert "access_token" not in res
    # il challenge non e' un chat token e viceversa
    assert al.verify_chat_token(res["mfa_token"]) is None

    start = await am.enroll_start(am.MfaTokenBody(mfa_token=res["mfa_token"]))
    assert start["qr_svg"].startswith("data:image/svg+xml;base64,")
    assert start["otpauth_uri"].startswith("otpauth://totp/")
    secret = start["secret"]

    with pytest.raises(HTTPException) as e:
        await am.enroll_confirm(am.MfaCodeBody(mfa_token=res["mfa_token"], code="000000"))
    assert e.value.status_code == 401

    code = pyotp.TOTP(secret).now()
    ok = await am.enroll_confirm(am.MfaCodeBody(mfa_token=res["mfa_token"], code=code))
    assert al.verify_chat_token(ok["access_token"])

    # replay dello stesso codice rifiutato
    res2 = await _login(al)
    assert res2["mfa_stage"] == "verify"
    with pytest.raises(HTTPException) as e:
        await am.verify(am.MfaCodeBody(mfa_token=res2["mfa_token"], code=code))
    assert e.value.status_code == 401

    # codice dello step successivo accettato
    nxt = pyotp.TOTP(secret).at(time.time() + 30)
    ok2 = await am.verify(am.MfaCodeBody(mfa_token=res2["mfa_token"], code=nxt))
    assert ok2["access_token"]

    # stage sbagliato
    with pytest.raises(HTTPException):
        await am.enroll_start(am.MfaTokenBody(mfa_token=res2["mfa_token"]))


@with_env
async def test_lockout_after_failures(env, monkeypatch):
    al, am = env["al"], env["am"]
    await env["set_required"](True)
    res = await _login(al)
    await am.enroll_start(am.MfaTokenBody(mfa_token=res["mfa_token"]))
    for _ in range(5):
        with pytest.raises(HTTPException) as e:
            await am.enroll_confirm(am.MfaCodeBody(mfa_token=res["mfa_token"], code="123456"))
        assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:
        await am.enroll_confirm(am.MfaCodeBody(mfa_token=res["mfa_token"], code="123456"))
    assert e.value.status_code == 429


@with_env
async def test_old_token_blocked_until_enrolled_and_reset(env, monkeypatch):
    al, am, totp = env["al"], env["am"], env["totp"]
    old = (await _login(al))["access_token"]
    await env["set_required"](True)
    with pytest.raises(HTTPException) as e:
        await al.require_chat_auth(authorization=f"Bearer {old}", x_api_key=None,
                                   x_chat_ui_secret=None, access_token=None)
    assert e.value.status_code == 403
    assert e.value.detail["code"] == "mfa_enrollment_required"

    # enroll -> old token riabilitato
    res = await _login(al)
    secret = (await am.enroll_start(am.MfaTokenBody(mfa_token=res["mfa_token"])))["secret"]
    await am.enroll_confirm(
        am.MfaCodeBody(mfa_token=res["mfa_token"], code=pyotp.TOTP(secret).now())
    )
    ident = await al.require_chat_auth(authorization=f"Bearer {old}", x_api_key=None,
                                       x_chat_ui_secret=None, access_token=None)
    assert ident.via == "chat_token"

    # reset admin -> torna in enroll
    assert await totp.reset_user_totp(env["uid"])
    assert (await _login(al))["mfa_stage"] == "enroll"


@with_env
async def test_not_applied_with_sso_mode_and_force_disable(env, monkeypatch):
    am_admin = __import__("src.api.admin_auth_mode", fromlist=["x"])
    await env["set_required"](True, mode="microsoft")
    assert not await env["totp"].two_factor_effective("default")

    class _Auth:
        user_row_id = None
        identifier = "admin"
        roles = ["admin"]

    with pytest.raises(HTTPException) as e:
        await am_admin.put_two_factor(am_admin.SetTwoFactorBody(required=True), _Auth())
    assert e.value.status_code == 409

    await env["set_required"](True)
    assert await env["totp"].two_factor_effective("default")
    monkeypatch.setenv("AION_2FA_FORCE_DISABLE", "1")
    assert not await env["totp"].two_factor_effective("default")


def test_mfa_token_expiry(monkeypatch):
    import src.auth.mfa.totp as totp

    monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "y" * 40)
    tok = totp.issue_mfa_token(user_row_id="u1", stage="verify")
    assert totp.verify_mfa_token(tok)["user_row_id"] == "u1"
    assert totp.verify_mfa_token(tok[:-4] + "AAAA") is None
    monkeypatch.setattr(totp.time, "time", lambda: time.time() + 10_000)
    assert totp.verify_mfa_token(tok) is None


@with_env
async def test_concurrent_enroll_start_returns_same_secret(env, monkeypatch):
    """Regressione: due start concorrenti (StrictMode) devono dare lo stesso secret."""
    al, am = env["al"], env["am"]
    await env["set_required"](True)
    res = await _login(al)
    body = am.MfaTokenBody(mfa_token=res["mfa_token"])
    a, b = await asyncio.gather(am.enroll_start(body), am.enroll_start(body))
    assert a["secret"] == b["secret"]
    ok = await am.enroll_confirm(
        am.MfaCodeBody(mfa_token=res["mfa_token"], code=pyotp.TOTP(a["secret"]).now())
    )
    assert ok["access_token"]
