"""Test API client Enterprise: /v1/client/info, expires_at, /auth/refresh,
/auth/logout, e il fix dei segreti org_shared su /v1/integrations/credentials."""

import asyncio
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.data.bootstrap import ensure_bootstrap_schema


def _with_db(fn):
    def wrapper(tmp_path, monkeypatch):
        async def run():
            import src.api.auth_login as al
            import src.auth.mfa.totp as totp
            import src.auth.sso.login_mode as lm
            import src.chat_auth as ca
            import src.data.engine as engine
            from src.data.user_password import create_password_user

            monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
            monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "x" * 40)
            monkeypatch.delenv("AION_2FA_FORCE_DISABLE", raising=False)
            eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ent.db'}")
            await ensure_bootstrap_schema(eng)
            sm = async_sessionmaker(eng, expire_on_commit=False)
            monkeypatch.setattr(engine, "get_async_session_maker", lambda: sm)
            for mod in (lm, totp, ca):
                monkeypatch.setattr(mod, "get_async_session_maker", lambda: sm)
            lm._SETTINGS_CACHE.clear()
            await create_password_user(
                tenant_id="default",
                identifier="alice",
                password="pw-alice",
                session_maker=sm,
            )
            try:
                await fn(al)
            finally:
                await eng.dispose()

        asyncio.run(run())

    wrapper.__name__ = fn.__name__
    return wrapper


@_with_db
async def test_login_has_expires_fields(al):
    res = await al.login(al.LoginBody(username="alice", password="pw-alice"))
    exp = datetime.strptime(res["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    assert abs(exp.timestamp() - (time.time() + res["expires_in"])) < 5
    assert abs(res["expires_in"] - al._TOKEN_TTL_SEC) < 5


@_with_db
async def test_refresh_issues_new_token(al):
    res = await al.login(al.LoginBody(username="alice", password="pw-alice"))
    await asyncio.sleep(1.1)  # exp in secondi: garantisce un token diverso
    new = await al.refresh_token(f"Bearer {res['access_token']}")
    assert new["access_token"] != res["access_token"]
    assert al.verify_chat_token(new["access_token"])["identifier"] == "alice"
    assert new["expires_in"] > 0 and new["expires_at"] >= res["expires_at"]
    assert new["identifier"] == "alice"


@_with_db
async def test_refresh_rejects_bad_tokens(al, monkeypatch=None):
    for hdr in (None, "Bearer garbage", "Basic abc"):
        with pytest.raises(HTTPException) as e:
            await al.refresh_token(hdr)
        assert e.value.status_code == 401


@_with_db
async def test_refresh_rejects_expired_token(al):
    orig = al._TOKEN_TTL_SEC
    tok, _ = al.issue_chat_token_with_exp(user_row_id="u", user_identifier="alice")
    real_time = al.time.time
    al.time.time = lambda: real_time() + orig + 10
    try:
        with pytest.raises(HTTPException) as e:
            await al.refresh_token(f"Bearer {tok}")
    finally:
        al.time.time = real_time
    assert e.value.status_code == 401


@_with_db
async def test_logout(al):
    res = await al.login(al.LoginBody(username="alice", password="pw-alice"))
    assert await al.logout(f"Bearer {res['access_token']}") == {"ok": True}
    with pytest.raises(HTTPException) as e:
        await al.logout(None)
    assert e.value.status_code == 401


@_with_db
async def test_client_info(al):
    from src.api.v1.client_info import client_info
    from src.version import __version__

    info = await client_info()
    assert info["product"] == "aion-agent"
    assert info["api_version"] == 1
    assert info["version"] == __version__
    assert info["min_client_version"] == "1.0.0"
    assert info["features"] == {
        "llm_proxy": True,
        "client_bootstrap": False,
        "desktop_login": True,
    }
    assert info["login_url"] is None or info["login_url"].endswith("/login")
    assert info["login_url"] is None or "//login" not in info["login_url"]
    st = await al.auth_status()
    for k in (
        "login_mode",
        "password_auth_enabled",
        "sso_enabled",
        "two_factor_required",
        "token_ttl_seconds",
    ):
        assert info[k] == st[k]


def test_client_info_route_is_public_and_registered():
    from src.api.main import app

    routes = {r.path: r for r in app.routes if hasattr(r, "path")}
    assert "/v1/client/info" in routes
    assert "/auth/refresh" in routes and "/auth/logout" in routes


# --- Fix sicurezza: credenziali org_shared mai in chiaro ------------------


def _fake_store(monkeypatch, mode):
    import src.runtime.credential_store as cs

    rows = {
        ("alice", "srv", "API_KEY"): "alice-secret",
        ("org_shared", "srv", "API_KEY"): "ORG-SECRET",
        ("default", "srv", "OTHER"): "DEFAULT-SECRET",
    }

    async def fake_mode(_slug):
        return mode

    async def fake_row(uid, slug, key, *, tenant_id="default"):
        v = rows.get((uid, slug, key))
        return SimpleNamespace(value_encrypted=v, expires_at=None) if v else None

    monkeypatch.setattr(cs, "_get_server_credential_mode", fake_mode)
    monkeypatch.setattr(cs, "_get_credential_row", fake_row)
    monkeypatch.setattr(cs, "decrypt_value", lambda v: v)
    return cs


@pytest.mark.parametrize("mode", ["org_shared", "per_user"])
def test_get_credential_user_only_never_falls_back(monkeypatch, mode):
    cs = _fake_store(monkeypatch, mode)

    async def run():
        assert await cs.get_credential("alice", "srv", "API_KEY", user_only=True) == (
            "alice-secret"
        )
        assert await cs.get_credential("bob", "srv", "API_KEY", user_only=True) is None
        assert await cs.get_credential("alice", "srv", "OTHER", user_only=True) is None
        assert (
            await cs.get_credential("default", "srv", "OTHER", user_only=True) is None
        )

    asyncio.run(run())


def test_get_credential_runtime_fallback_unchanged(monkeypatch):
    cs = _fake_store(monkeypatch, "org_shared")

    async def run():
        # uso server-side (runtime MCP): il fallback org_shared resta attivo
        assert await cs.get_credential("bob", "srv", "API_KEY") == "ORG-SECRET"
        assert await cs.get_credential("bob", "srv", "OTHER") == "DEFAULT-SECRET"

    asyncio.run(run())


def test_credentials_endpoint_hides_org_shared(monkeypatch):
    _fake_store(monkeypatch, "org_shared")
    import src.api.v1.mcp_integrations as mi
    from src.api.auth_login import ChatAuthIdentity

    monkeypatch.setattr(mi, "user_credentials_enabled", lambda: True)

    async def run():
        mine = ChatAuthIdentity(via="chat_token", identifier="alice")
        out = await mi.get_user_credential_value("srv", "API_KEY", auth=mine)
        assert out["value"] == "alice-secret"
        other = ChatAuthIdentity(via="chat_token", identifier="bob")
        with pytest.raises(HTTPException) as e:
            await mi.get_user_credential_value("srv", "API_KEY", auth=other)
        assert e.value.status_code == 404

    asyncio.run(run())
