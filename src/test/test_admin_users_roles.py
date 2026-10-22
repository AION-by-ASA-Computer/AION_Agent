"""/admin/users: guard sul ruolo admin, sulla password degli utenti SSO e sulla
creazione di utenti con SSO attivo; /admin/auth/signup-policy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException


async def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("AION_UNIFIED_DB", "1")

    from src.data import engine as engine_mod
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_async_session_maker, init_engine
    from src.data.models import User

    # DB isolato per test: init_engine e' un singleton di modulo.
    monkeypatch.setattr(engine_mod, "_engine", None)
    monkeypatch.setattr(engine_mod, "_session_factory", None)
    # login_mode ha una cache di modulo (15s) che altri test possono sporcare.
    from src.auth.sso import login_mode

    login_mode._SETTINGS_CACHE.clear()
    eng = init_engine()
    await ensure_bootstrap_schema(eng)
    async with get_async_session_maker()() as session:
        for uid, roles in (("a1", '["admin"]'), ("u1", "[]")):
            session.add(
                User(id=uid, tenant_id="default", identifier=uid, roles_json=roles)
            )
        await session.commit()
    return get_async_session_maker()


def _auth(uid: str = "someone"):
    from src.api.auth_login import ChatAuthIdentity

    return ChatAuthIdentity(user_row_id=uid, via="chat_token", roles=["admin"])


async def _roles(sm, uid: str):
    from src.data.models import User
    from src.data.user_password import get_roles

    async with sm() as session:
        return get_roles(await session.get(User, uid))


@pytest.mark.anyio
async def test_promote_and_demote(monkeypatch, tmp_path):
    db = await _setup(monkeypatch, tmp_path)
    from src.api.admin import UserUpdate, update_user

    await update_user("u1", UserUpdate(roles=["admin"]), auth=_auth("a1"))
    assert await _roles(db, "u1") == ["admin"]

    await update_user("u1", UserUpdate(roles=[]), auth=_auth("a1"))
    assert await _roles(db, "u1") == []


@pytest.mark.anyio
async def test_cannot_demote_self_or_last_admin(monkeypatch, tmp_path):
    db = await _setup(monkeypatch, tmp_path)
    from src.api.admin import UserUpdate, update_user

    with pytest.raises(HTTPException) as e:
        await update_user("a1", UserUpdate(roles=[]), auth=_auth("a1"))
    assert e.value.status_code == 400

    with pytest.raises(HTTPException) as e:
        await update_user("a1", UserUpdate(roles=[]), auth=_auth("other"))
    assert e.value.status_code == 409
    assert await _roles(db, "a1") == ["admin"]


@pytest.mark.anyio
async def test_password_rejected_for_sso_user(monkeypatch, tmp_path):
    db = await _setup(monkeypatch, tmp_path)
    from src.api.admin import UserUpdate, update_user
    from src.auth.sso import login_mode
    from src.data.models import UserSsoIdentity

    async def fake_settings(_tenant):
        return {
            "login_mode": "microsoft",
            "sso_provider": "microsoft",
            "migration_started_at": None,
        }

    monkeypatch.setattr(login_mode, "get_login_settings", fake_settings)

    # Senza identita' confermata la password si puo' ancora impostare.
    await update_user("u1", UserUpdate(password="Secret-123"), auth=_auth())

    async with db() as session:
        session.add(
            UserSsoIdentity(
                id="i1",
                tenant_id="default",
                user_id="u1",
                provider="microsoft",
                subject="sub",
                last_login_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    with pytest.raises(HTTPException) as e:
        await update_user("u1", UserUpdate(password="Secret-123"), auth=_auth())
    assert e.value.status_code == 400


@pytest.mark.anyio
async def test_weak_password_rejected(monkeypatch, tmp_path):
    await _setup(monkeypatch, tmp_path)
    from src.api.admin import UserCreate, UserUpdate, create_user, update_user

    with pytest.raises(HTTPException) as e:
        await create_user(UserCreate(identifier="mario", password="secret123"))
    assert e.value.status_code == 422

    with pytest.raises(HTTPException) as e:
        await update_user("u1", UserUpdate(password="short"), auth=_auth())
    assert e.value.status_code == 422

    res = await create_user(UserCreate(identifier="mario", password="Str0ng!pw"))
    assert res["status"] == "success"


@pytest.mark.anyio
async def test_api_key_policy_fields(monkeypatch, tmp_path):
    sm = await _setup(monkeypatch, tmp_path)
    from pydantic import ValidationError

    from src.api.admin import UserCreate, UserUpdate, create_user, update_user
    from sqlalchemy import select

    from src.data import api_keys as api_keys_db
    from src.data.models import User

    res = await create_user(
        UserCreate(
            identifier="mario",
            password="Str0ng!pw",
            can_create_api_keys=True,
            max_api_keys=3,
            api_key_max_ttl_days=10,
        )
    )
    async with sm() as session:
        u = (
            await session.execute(select(User).where(User.identifier == "mario"))
        ).scalar_one()
        assert (u.can_create_api_keys, u.max_api_keys, u.api_key_max_ttl_days) == (
            True,
            3,
            10,
        )
        row, _ = await api_keys_db.create_user_key(
            session, u, name="k", scopes=["chat"], ttl_days=5
        )
        await session.commit()
        uid, key_id = u.id, row.id
    assert res["status"] == "success"

    with pytest.raises(ValidationError):
        UserUpdate(max_api_keys=0)

    # Disabilitare la funzione revoca subito le chiavi attive.
    await update_user(uid, UserUpdate(can_create_api_keys=False), auth=_auth())
    from src.data.models import ApiKey

    async with sm() as session:
        assert (await session.get(ApiKey, key_id)).revoked_at is not None
        assert await api_keys_db.count_active(session, uid) == 0


async def _set_login_mode(sm, mode: str) -> None:
    from src.auth.sso import login_mode
    from src.data.models import AuthSettings

    async with sm() as session:
        session.add(AuthSettings(tenant_id="default", login_mode=mode))
        await session.commit()
    login_mode._invalidate_cache("default")


@pytest.mark.anyio
async def test_create_user_blocked_when_sso_active(monkeypatch, tmp_path):
    sm = await _setup(monkeypatch, tmp_path)
    from src.api.admin import UserCreate, create_user

    await _set_login_mode(sm, "microsoft")
    with pytest.raises(HTTPException) as e:
        await create_user(UserCreate(identifier="mario", password="Str0ng!pw"))
    assert e.value.status_code == 409
    assert e.value.detail == {"code": "sso_active_user_creation_disabled"}


@pytest.mark.anyio
async def test_signup_policy_endpoints(monkeypatch, tmp_path):
    sm = await _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("AION_DEFAULT_TENANT_ID", raising=False)
    from src.api.admin_auth_mode import (
        SetSignupPolicyBody,
        get_signup_policy,
        put_signup_policy,
    )
    from src.data.models import AuthSettings

    res = await get_signup_policy(auth=_auth("a1"))
    assert (res["policy"], res["allowlist"], res["applies"]) == ("open", [], False)

    res = await put_signup_policy(
        SetSignupPolicyBody(
            policy="allowlist",
            allowlist=[" Anna@X.io", "@Pilot.x.io", "anna@x.io", ""],
        ),
        auth=_auth("a1"),
    )
    assert res["policy"] == "allowlist"
    assert res["allowlist"] == ["anna@x.io", "@pilot.x.io"]
    async with sm() as session:
        row = await session.get(AuthSettings, "default")
        assert row.login_mode == "password"
        assert row.updated_by_user_id == "a1"

    with pytest.raises(HTTPException) as e:
        await put_signup_policy(
            SetSignupPolicyBody(policy="allowlist", allowlist=["not-an-email"]),
            auth=_auth("a1"),
        )
    assert e.value.status_code == 400
    assert e.value.detail == {
        "code": "invalid_allowlist_entry",
        "entry": "not-an-email",
    }

    with pytest.raises(HTTPException) as e:
        await put_signup_policy(SetSignupPolicyBody(policy="maybe"), auth=_auth("a1"))
    assert e.value.detail == {"code": "invalid_signup_policy"}

    # L'elenco resta salvato anche passando a "closed".
    res = await put_signup_policy(
        SetSignupPolicyBody(policy="closed", allowlist=res["allowlist"]),
        auth=_auth("a1"),
    )
    assert (res["policy"], res["allowlist"]) == ("closed", ["anna@x.io", "@pilot.x.io"])
