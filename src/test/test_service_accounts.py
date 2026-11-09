"""Service accounts: admin lifecycle, API-key auth, login lockout, LTM gating.

Covers ``/admin/service-accounts`` (``src/api/admin_service_accounts.py``),
the auth gates for ``account_type='service'`` (password login, chat tokens,
disabled owner), the reserved ``svc-`` prefix on ``/admin/users`` and the
per-account LTM switch in ``src/memory/ltm_orchestrator.py``.
See ``docs/security/service-accounts.md``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.test.test_api_endpoints import _reset_unified_db
from src.test.test_api_keys import _bearer, _key, _make_user, _restrict_profiles


async def _get_user(uid: str):
    from src.data.engine import get_async_session_maker
    from src.data.models import User

    async with get_async_session_maker()() as s:
        return await s.get(User, uid)


async def _force_password(uid: str, plain: str) -> None:
    """Simulate a stray password hash (e.g. manual SQL) on a service account."""
    from src.data.engine import get_async_session_maker
    from src.data.models import User
    from src.data.user_password import hash_password

    async with get_async_session_maker()() as s:
        u = await s.get(User, uid)
        u.password_hash = hash_password(plain)
        await s.commit()


def _clear_login_caches() -> None:
    """Login settings are cached per process: never leak SSO mode across tests."""
    import src.auth.sso.login_mode as lm

    lm._SETTINGS_CACHE.clear()
    lm._PENDING_CACHE.clear()


async def _set_login_mode(mode: str, *, exempt_user: str) -> None:
    """Switch the tenant to an SSO login mode (as PUT /admin/auth/login-mode would).

    ``exempt_user`` (the test admin) is marked exempt so its password-based
    token keeps working instead of hitting the "link your account" gate.
    """
    import src.auth.sso.login_mode as lm
    from src.data.engine import get_async_session_maker
    from src.data.models import AuthSettings, User

    async with get_async_session_maker()() as s:
        (await s.get(User, exempt_user)).sso_migration_exempt = True
        row = await s.get(AuthSettings, "default")
        if row is None:
            row = AuthSettings(tenant_id="default")
            s.add(row)
        row.login_mode = mode
        row.sso_origin = "first_setup"
        await s.commit()
    lm._invalidate_cache("default")


@pytest.fixture()
def env(monkeypatch, tmp_path: Path):
    asyncio.run(_reset_unified_db(monkeypatch, tmp_path))
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_ADMIN_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_SETUP_ADMIN_BOOTSTRAP", "0")
    monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "s" * 40)

    from src.api.auth_login import issue_chat_token
    from src.api.main import app
    from src.data import service_accounts as svc

    svc.invalidate_ltm_cache()
    _clear_login_caches()
    with TestClient(app) as client:
        call = client.portal.call
        admin = call(lambda: _make_user("boss", roles=["admin"]))
        alice = call(lambda: _make_user("alice", can_keys=True))
        yield {
            "client": client,
            "call": call,
            "admin_id": admin,
            "alice": alice,
            "alice_token": issue_chat_token(user_row_id=alice, user_identifier="alice"),
            "admin": _bearer(
                issue_chat_token(
                    user_row_id=admin, user_identifier="boss", roles=["admin"]
                )
            ),
        }
    svc.invalidate_ltm_cache()
    _clear_login_caches()


def _create_account(env, slug="ci-bot", **extra):
    return env["client"].post(
        "/admin/service-accounts",
        headers=env["admin"],
        json={"slug": slug, "display_name": "CI bot", **extra},
    )


def _create_key(env, account_id, scopes=("chat",), days=30, name="k"):
    return env["client"].post(
        f"/admin/service-accounts/{account_id}/keys",
        headers=env["admin"],
        json={"name": name, "scopes": list(scopes), "expires_in_days": days},
    )


def test_create_account_and_key_acts_as_service_identity(env):
    """An admin-created key authenticates as ``svc-<slug>`` and owns its data."""
    c = env["client"]
    res = _create_account(env, description="nightly jobs")
    assert res.status_code == 201, res.text
    acc = res.json()
    assert acc["identifier"] == "svc-ci-bot"
    assert acc["ltm_enabled"] is False
    assert acc["disabled"] is False
    assert acc["created_by"] == "boss"

    key = _create_key(env, acc["id"], scopes=["conversations:read", "conversations:write"])
    assert key.status_code == 201, key.text
    secret = key.json()["key"]
    assert secret.startswith("aion_")

    res = c.post("/chat-ui/conversations", headers=_key(secret), json={"title": "svc"})
    assert res.status_code == 200, res.text
    # The conversation belongs to the service account, not to any person.
    alice_titles = [
        r.get("title")
        for r in c.get(
            "/chat-ui/conversations", headers=_bearer(env["alice_token"])
        ).json()["data"]
    ]
    assert "svc" not in alice_titles
    svc_titles = [
        r.get("title")
        for r in c.get("/chat-ui/conversations", headers=_key(secret)).json()["data"]
    ]
    assert "svc" in svc_titles

    # Listing shows key stats but never the secret.
    listing = c.get("/admin/service-accounts", headers=env["admin"])
    item = listing.json()["items"][0]
    assert item["active_keys"] == 1
    assert item["last_used_at"] is not None
    assert secret not in listing.text
    keys = c.get(f"/admin/service-accounts/{acc['id']}/keys", headers=env["admin"])
    assert secret not in keys.text
    assert keys.json()["policy"]["max_ttl_days"] == 90


def test_create_validation(env):
    """Bad slugs are 422, duplicates 409, TTL is capped at 365 days."""
    assert _create_account(env, slug="Bad Slug!").json()["detail"]["code"] == (
        "invalid_service_slug"
    )
    assert _create_account(env).status_code == 201
    res = _create_account(env, slug="svc-ci-bot")  # prefix is accepted and stripped
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "user_exists"
    assert _create_account(env, slug="other", api_key_max_ttl_days=366).status_code == 422


def test_key_policy_enforced(env):
    """Expiry beyond the account max, unknown scopes and quota are refused."""
    acc = _create_account(env, max_api_keys=1, api_key_max_ttl_days=10).json()
    res = _create_key(env, acc["id"], days=11)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_expiration"
    res = _create_key(env, acc["id"], scopes=["admin"])
    assert res.json()["detail"]["code"] == "invalid_scopes"
    assert _create_key(env, acc["id"], days=10).status_code == 201
    res = _create_key(env, acc["id"], days=10)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "api_key_quota_exceeded"


def test_disable_enable_and_revoke(env):
    """Disabling rejects keys (401) without losing them; revoke is permanent."""
    c = env["client"]
    acc = _create_account(env).json()
    secret = _create_key(env, acc["id"]).json()
    assert c.get("/profiles", headers=_key(secret["key"])).status_code == 200

    res = c.patch(
        f"/admin/service-accounts/{acc['id']}", headers=env["admin"], json={"disabled": True}
    )
    assert res.json()["disabled"] is True
    res = c.get("/profiles", headers=_key(secret["key"]))
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "api_key_owner_disabled"

    c.patch(
        f"/admin/service-accounts/{acc['id']}", headers=env["admin"], json={"disabled": False}
    )
    assert c.get("/profiles", headers=_key(secret["key"])).status_code == 200

    res = c.delete(
        f"/admin/service-accounts/{acc['id']}/keys/{secret['id']}", headers=env["admin"]
    )
    assert res.json()["status"] == "revoked"
    res = c.get("/profiles", headers=_key(secret["key"]))
    assert res.json()["detail"]["code"] == "api_key_revoked"


def test_service_account_cannot_log_in_or_use_chat_tokens(env):
    """No password login (even with a stray hash) and no chat-token sessions."""
    from src.api.auth_login import issue_chat_token

    c = env["client"]
    acc = _create_account(env).json()
    env["call"](lambda: _force_password(acc["id"], "hunter2-hunter2"))
    res = c.post(
        "/auth/login", json={"username": "svc-ci-bot", "password": "hunter2-hunter2"}
    )
    assert res.status_code == 401, res.text

    token = issue_chat_token(user_row_id=acc["id"], user_identifier="svc-ci-bot")
    res = c.get("/chat-ui/conversations", headers=_bearer(token))
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "service_account_token_not_allowed"


def test_service_key_cannot_reach_admin(env):
    """``/admin/*`` stays closed to API keys, service accounts included."""
    acc = _create_account(env).json()
    secret = _create_key(env, acc["id"]).json()["key"]
    for path in ("/admin/users", "/admin/service-accounts"):
        res = env["client"].get(path, headers=_key(secret))
        assert res.status_code == 403, (path, res.text)


def test_users_endpoints_keep_service_accounts_apart(env):
    """People list hides them, ``svc-`` is reserved, people endpoints refuse them."""
    c = env["client"]
    acc = _create_account(env).json()

    users = c.get("/admin/users", headers=env["admin"]).json()["users"]
    assert "svc-ci-bot" not in [u["identifier"] for u in users]
    users = c.get("/admin/users?include_service=1", headers=env["admin"]).json()["users"]
    row = next(u for u in users if u["identifier"] == "svc-ci-bot")
    assert row["account_type"] == "service"

    res = c.post(
        "/admin/users",
        headers=env["admin"],
        json={"identifier": "svc-sneaky", "email": "x@example.com"},
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "identifier_reserved"

    res = c.put(f"/admin/users/{acc['id']}", headers=env["admin"], json={"roles": ["admin"]})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "service_account_use_dedicated_endpoint"
    res = c.post(f"/admin/users/{acc['id']}/password-link", headers=env["admin"])
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "service_account_no_password"

    # Human ids are not service accounts on the dedicated endpoints.
    res = c.patch(
        f"/admin/service-accounts/{env['alice']}", headers=env["admin"], json={"disabled": True}
    )
    assert res.status_code == 404


def test_create_allowed_in_sso_mode(env):
    """SSO mode blocks new people with passwords, not service accounts."""
    env["call"](lambda: _set_login_mode("google", exempt_user=env["admin_id"]))
    res = env["client"].post(
        "/admin/users",
        headers=env["admin"],
        json={"identifier": "carol", "email": "carol@example.com"},
    )
    assert res.status_code == 409
    assert _create_account(env).status_code == 201


def test_profile_restriction_applies(env):
    """Profile allowlists on the service account apply to its keys."""
    acc = _create_account(env).json()
    env["call"](lambda: _restrict_profiles(acc["id"], ["only_this"]))
    secret = _create_key(env, acc["id"]).json()["key"]
    res = env["client"].post(
        "/v1/chat",
        headers=_key(secret),
        json={"message": "hi", "profile": "generic_assistant"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "profile_not_allowed"


def test_delete_removes_account_and_keys(env):
    """Deleting the account drops its keys so they stop authenticating."""
    c = env["client"]
    acc = _create_account(env).json()
    secret = _create_key(env, acc["id"]).json()["key"]
    res = c.delete(f"/admin/service-accounts/{acc['id']}", headers=env["admin"])
    assert res.json() == {"deleted": True}
    assert env["call"](lambda: _get_user(acc["id"])) is None
    assert c.get("/profiles", headers=_key(secret)).status_code == 401


def test_ltm_extraction_gated_per_account(env, monkeypatch):
    """LTM is skipped for service accounts until the admin enables it."""
    import src.memory.ltm_orchestrator as ltm_mod

    calls: list[str] = []

    async def fake_complete(system, prompt):
        calls.append(prompt)
        return {}

    async def fake_apply(data, **kw):
        return None

    monkeypatch.setattr(ltm_mod, "complete_json_async", fake_complete)
    monkeypatch.setattr(ltm_mod.mnemos_orchestrator, "apply_extraction", fake_apply)
    monkeypatch.setenv("AION_LTM_EXTRACT", "1")

    acc = _create_account(env).json()
    orch = ltm_mod.ltm_orchestrator

    def extract(user_id):
        return env["call"](
            lambda: orch.extract_and_persist("s1", user_id, "hello", "world")
        )

    extract("svc-ci-bot")
    assert calls == []
    assert env["call"](lambda: orch.wake_up("s1", user_id="svc-ci-bot")) == ""

    env["client"].patch(
        f"/admin/service-accounts/{acc['id']}",
        headers=env["admin"],
        json={"ltm_enabled": True},
    )
    extract("svc-ci-bot")
    assert len(calls) == 1
    # People are never affected by the per-account switch.
    extract("alice")
    assert len(calls) == 2
