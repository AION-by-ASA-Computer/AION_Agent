"""PUT /admin/users/{id}: guard sul ruolo admin e sulla password degli utenti SSO."""

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
