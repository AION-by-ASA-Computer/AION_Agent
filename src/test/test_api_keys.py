"""API key per-utente: creazione da /v1/me/api-keys, validazione chiave+scope,
identita' del proprietario, policy admin."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.test.test_api_endpoints import _reset_unified_db


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _key(token: str) -> dict:
    return {"X-Api-Key": token}


async def _make_user(
    identifier: str, *, roles=None, can_keys=False, max_keys=5, ttl=90
):
    from src.data.engine import get_async_session_maker
    from src.data.models import User
    from src.data.user_password import create_password_user

    uid = await create_password_user(
        tenant_id="default",
        identifier=identifier,
        password=f"pw-{identifier}",
        roles=roles,
    )
    async with get_async_session_maker()() as s:
        u = await s.get(User, uid)
        u.can_create_api_keys = can_keys
        u.max_api_keys = max_keys
        u.api_key_max_ttl_days = ttl
        await s.commit()
    return uid


async def _set_key_field(key_id: str, **fields):
    from src.data.engine import get_async_session_maker
    from src.data.models import ApiKey

    async with get_async_session_maker()() as s:
        row = await s.get(ApiKey, key_id)
        for k, v in fields.items():
            setattr(row, k, v)
        await s.commit()


async def _get_key(key_id: str):
    from src.data.engine import get_async_session_maker
    from src.data.models import ApiKey

    async with get_async_session_maker()() as s:
        return await s.get(ApiKey, key_id)


async def _insert_legacy_key(full_key: str):
    from src.api.auth.api_key import hash_api_key
    from src.data.engine import get_async_session_maker
    from src.data.models import ApiKey

    async with get_async_session_maker()() as s:
        row = ApiKey(
            id="legacy-key",
            tenant_id="default",
            name="legacy",
            prefix=full_key.split("_")[1],
            hash=hash_api_key(full_key),
            scopes_json='["chat"]',
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        s.add(row)
        await s.commit()


async def _restrict_profiles(uid: str, slugs: list[str]):
    from src.data.engine import get_async_session_maker
    from src.data.models import UserProfileAccess

    async with get_async_session_maker()() as s:
        for slug in slugs:
            s.add(
                UserProfileAccess(tenant_id="default", user_id=uid, profile_slug=slug)
            )
        await s.commit()


@pytest.fixture()
def env(monkeypatch, tmp_path: Path):
    asyncio.run(_reset_unified_db(monkeypatch, tmp_path))
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_ADMIN_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_SETUP_ADMIN_BOOTSTRAP", "0")
    monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "s" * 40)

    from src.api.auth_login import issue_chat_token
    from src.api.main import app

    with TestClient(app) as client:
        call = client.portal.call
        alice = call(lambda: _make_user("alice", can_keys=True, max_keys=2, ttl=30))
        admin = call(lambda: _make_user("boss", roles=["admin"]))
        yield {
            "client": client,
            "call": call,
            "alice": alice,
            "alice_token": issue_chat_token(user_row_id=alice, user_identifier="alice"),
            "admin_token": issue_chat_token(
                user_row_id=admin, user_identifier="boss", roles=["admin"]
            ),
        }


def _create(env, scopes=("chat",), days=30, name="k"):
    return env["client"].post(
        "/v1/me/api-keys",
        headers=_bearer(env["alice_token"]),
        json={"name": name, "scopes": list(scopes), "expires_in_days": days},
    )


def test_create_returns_secret_once(env):
    res = _create(env, scopes=["chat", "conversations:read"])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["key"].startswith("aion_")
    assert body["status"] == "active"

    listing = env["client"].get("/v1/me/api-keys", headers=_bearer(env["alice_token"]))
    data = listing.json()
    assert data["policy"]["enabled"] is True
    assert data["policy"]["active_count"] == 1
    assert data["policy"]["max_keys"] == 2
    assert "key" not in data["keys"][0]
    assert body["key"] not in listing.text


def test_create_validation_errors(env):
    assert _create(env, scopes=["admin"]).json()["detail"]["code"] == "invalid_scopes"
    res = _create(env, days=31)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_expiration"

    assert _create(env).status_code == 201
    assert _create(env).status_code == 201
    res = _create(env)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "api_key_quota_exceeded"


def test_create_forbidden_when_disabled(env):
    bob = env["call"](lambda: _make_user("bob"))
    from src.api.auth_login import issue_chat_token

    res = env["client"].post(
        "/v1/me/api-keys",
        headers=_bearer(issue_chat_token(user_row_id=bob, user_identifier="bob")),
        json={"name": "k", "scopes": ["chat"], "expires_in_days": 7},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "api_keys_disabled"


def test_key_cannot_manage_keys_or_reach_other_endpoints(env):
    key = _create(env)
    full = key.json()["key"]
    c = env["client"]
    for path in ("/v1/me/api-keys", "/v1/user-memory/notes", "/admin/users"):
        res = c.get(path, headers=_key(full))
        assert res.status_code == 403, (path, res.text)
        assert res.json()["detail"]["code"] == "api_key_not_allowed"
    # anche come Bearer
    res = c.get("/v1/user-memory/notes", headers=_bearer(full))
    assert res.json()["detail"]["code"] == "api_key_not_allowed"


def test_scopes_enforced(env):
    c = env["client"]
    chat_key = _create(env, scopes=["chat"]).json()["key"]
    read_key = _create(env, scopes=["conversations:read"]).json()["key"]

    assert c.get("/profiles", headers=_key(chat_key)).status_code == 200

    res = c.post("/v1/chat", headers=_key(read_key), json={"message": "hi"})
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "missing_scope"

    res = c.get("/profiles", headers=_key(read_key))
    assert res.status_code == 403
    assert c.get("/chat-ui/conversations", headers=_key(read_key)).status_code == 200
    res = c.post("/chat-ui/conversations", headers=_key(read_key), json={})
    assert res.json()["detail"]["code"] == "missing_scope"


def test_key_acts_as_owner(env):
    c = env["client"]
    key = _create(env, scopes=["conversations:read", "conversations:write"]).json()
    res = c.post(
        "/chat-ui/conversations", headers=_key(key["key"]), json={"title": "via key"}
    )
    assert res.status_code == 200, res.text

    listing = c.get("/chat-ui/conversations", headers=_bearer(env["alice_token"]))
    titles = [r.get("title") for r in listing.json()["data"]]
    assert "via key" in titles

    row = env["call"](lambda: _get_key(key["id"]))
    assert row.last_used_at is not None


def test_revoked_expired_and_legacy_keys_rejected(env):
    c = env["client"]
    k1 = _create(env).json()
    k2 = _create(env).json()

    res = c.delete(f"/v1/me/api-keys/{k1['id']}", headers=_bearer(env["alice_token"]))
    assert res.status_code == 200
    res = c.get("/profiles", headers=_key(k1["key"]))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "api_key_revoked"

    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    env["call"](lambda: _set_key_field(k2["id"], expires_at=past))
    res = c.get("/profiles", headers=_key(k2["key"]))
    assert res.json()["detail"]["code"] == "api_key_expired"

    legacy = "aion_abcdefgh_" + "x" * 32
    env["call"](lambda: _insert_legacy_key(legacy))
    res = c.get("/profiles", headers=_key(legacy))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "api_key_owner_disabled"

    res = c.get("/profiles", headers=_key("aion_nope"))
    assert res.json()["detail"]["code"] == "api_key_invalid_format"
    res = c.get("/profiles", headers=_key("aion_zzzzzzzz_" + "y" * 32))
    assert res.json()["detail"]["code"] == "api_key_invalid"


def test_admin_disable_revokes_and_delete_removes(env):
    c = env["client"]
    key = _create(env).json()
    admin = _bearer(env["admin_token"])

    users = c.get("/admin/users", headers=admin).json()
    row = next(u for u in (users.get("users") or users) if u["identifier"] == "alice")
    assert row["can_create_api_keys"] is True
    assert row["api_keys_active"] == 1

    res = c.put(
        f"/admin/users/{env['alice']}",
        headers=admin,
        json={"can_create_api_keys": False},
    )
    assert res.status_code == 200, res.text
    res = c.get("/profiles", headers=_key(key["key"]))
    assert res.status_code == 401
    assert env["call"](lambda: _get_key(key["id"])).revoked_at is not None

    c.put(
        f"/admin/users/{env['alice']}",
        headers=admin,
        json={"can_create_api_keys": True},
    )
    key2 = _create(env).json()
    assert c.delete(f"/admin/users/{env['alice']}", headers=admin).status_code == 200
    assert env["call"](lambda: _get_key(key2["id"])) is None
    assert c.get("/profiles", headers=_key(key2["key"])).status_code == 401


def test_profile_restriction_applies_to_keys(env):
    env["call"](lambda: _restrict_profiles(env["alice"], ["only_this"]))
    key = _create(env).json()["key"]
    res = env["client"].post(
        "/v1/chat",
        headers=_key(key),
        json={"message": "hi", "profile": "generic_assistant"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "profile_not_allowed"


def test_open_mode_still_validates_keys(env, monkeypatch):
    key = _create(env).json()["key"]
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "0")
    c = env["client"]
    assert c.get("/profiles", headers=_key(key)).status_code == 200
    res = c.get("/profiles", headers=_key("aion_zzzzzzzz_" + "y" * 32))
    assert res.status_code == 401
