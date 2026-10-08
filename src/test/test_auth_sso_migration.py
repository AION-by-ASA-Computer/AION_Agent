import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.data.bootstrap import ensure_bootstrap_schema

PROVIDER = {"provider": "google", "auto_provision": True, "default_roles": ["user"]}


def _claims(sub: str, email: str) -> dict:
    return {"sub": sub, "email": email, "name": email}


@asynccontextmanager
async def _env(tmp_path: Path, monkeypatch):
    import src.auth.sso.login_mode as lm
    import src.auth.sso.provisioning as prov
    import src.data.engine as engine
    from src.data.models import AuthSettings
    from src.data.user_password import create_password_user

    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "x" * 40)
    monkeypatch.delenv("AION_SSO_FORCE_PASSWORD", raising=False)
    monkeypatch.delenv("AION_2FA_FORCE_DISABLE", raising=False)
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sso.db'}")
    await ensure_bootstrap_schema(eng)
    sm = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(engine, "get_async_session_maker", lambda: sm)
    import src.chat_auth as ca

    for mod in (lm, prov, ca):
        monkeypatch.setattr(mod, "get_async_session_maker", lambda: sm)
    lm._SETTINGS_CACHE.clear()
    lm._PENDING_CACHE.clear()

    async def mkuser(name: str, roles=None) -> str:
        return await create_password_user(
            tenant_id="default", identifier=name, password=f"pw-{name}", roles=roles, session_maker=sm
        )

    async def set_settings(**kw):
        async with sm() as s:
            row = await s.get(AuthSettings, "default")
            if row is None:
                row = AuthSettings(tenant_id="default")
                s.add(row)
            for k, v in kw.items():
                setattr(row, k, v)
            await s.commit()
        lm._invalidate_cache("default")

    async def get_user(uid):
        from src.data.models import User

        async with sm() as s:
            return await s.get(User, uid)

    yield {"sm": sm, "lm": lm, "prov": prov, "mkuser": mkuser, "set": set_settings, "get_user": get_user}
    await eng.dispose()


def with_env(fn):
    def wrapper(tmp_path, monkeypatch):
        async def run():
            async with _env(tmp_path, monkeypatch) as env:
                await fn(env, monkeypatch)

        asyncio.run(run())

    wrapper.__name__ = fn.__name__
    return wrapper


@with_env
async def test_link_clears_password_for_everyone(env, monkeypatch):
    await env["set"](login_mode="google", sso_origin="migration", clear_password_on_link=True)
    bob = await env["mkuser"]("bob")
    adm = await env["mkuser"]("root", roles=["admin"])
    for uid, sub in ((bob, "s-bob"), (adm, "s-adm")):
        await env["prov"].link_identity_to_user(
            "default", uid, _claims(sub, f"{sub}@x.io"), {}, PROVIDER, finalize_migration=True
        )
    assert (await env["get_user"](bob)).password_hash is None
    # Anche l'admin: l'accesso di emergenza passa da src.auth.recover.
    assert (await env["get_user"](adm)).password_hash is None


@with_env
async def test_link_without_finalize_keeps_password(env, monkeypatch):
    # admin_validate: ancora in modalita' password, anche se l'admin e' l'unico utente.
    await env["set"](login_mode="password", clear_password_on_link=True)
    adm = await env["mkuser"]("root", roles=["admin"])
    await env["prov"].link_identity_to_user("default", adm, _claims("s1", "a@x.io"), {}, PROVIDER)
    assert (await env["get_user"](adm)).password_hash is not None


@with_env
async def test_resolve_user_blocked_during_migration(env, monkeypatch):
    with pytest.raises(ValueError, match="sso_not_linked"):
        await env["prov"].resolve_user(
            _claims("new", "new@x.io"), {}, PROVIDER, migration_active=True
        )
    # Fuori migrazione l'auto-provisioning resta attivo.
    user = await env["prov"].resolve_user(_claims("new", "new@x.io"), {}, PROVIDER)
    assert user


@with_env
async def test_migration_completes_after_last_link(env, monkeypatch):
    lm = env["lm"]
    await env["set"](login_mode="google", sso_origin="migration")
    a = await env["mkuser"]("a")
    b = await env["mkuser"]("b")
    assert await lm.pending_users_count("default", "google") == 2  # riempie la cache
    await env["prov"].link_identity_to_user("default", a, _claims("sa", "a@x.io"), {}, PROVIDER, finalize_migration=True)
    assert await lm.is_migration_active("default")
    assert await lm.password_login_visible("default")
    await env["prov"].link_identity_to_user("default", b, _claims("sb", "b@x.io"), {}, PROVIDER, finalize_migration=True)
    lm._invalidate_cache("default")
    assert not await lm.is_migration_active("default")
    assert not await lm.password_login_visible("default")


@with_env
async def test_cleared_password_users_not_pending(env, monkeypatch):
    lm = env["lm"]
    await env["set"](login_mode="google", sso_origin="migration")
    a = await env["mkuser"]("a")
    await env["mkuser"]("b")
    await env["prov"].link_identity_to_user("default", a, _claims("sa", "a@x.io"), {}, PROVIDER, finalize_migration=True)
    assert await lm.pending_users_count("default", "google") == 1
    assert not await lm.user_needs_link("default", a)


@with_env
async def test_force_password_breakglass(env, monkeypatch):
    lm = env["lm"]
    await env["set"](login_mode="google", sso_origin="migration")
    uid = await env["mkuser"]("a")
    assert await lm.user_needs_link("default", uid)
    monkeypatch.setenv("AION_SSO_FORCE_PASSWORD", "1")
    assert not await lm.user_needs_link("default", uid)
    assert not await lm.is_migration_active("default")
    assert await lm.password_login_visible("default")


@with_env
async def test_exempt_user_never_needs_link(env, monkeypatch):
    from src.data.models import User

    await env["set"](login_mode="google", sso_origin="migration")
    uid = await env["mkuser"]("svc")
    async with env["sm"]() as s:
        u = await s.get(User, uid)
        u.sso_migration_exempt = True
        await s.commit()
    assert not await env["lm"].user_needs_link("default", uid)
    assert await env["lm"].pending_users_count("default", "google") == 0


@with_env
async def test_2fa_not_enforced_in_sso_mode_even_if_required(env, monkeypatch):
    from src.auth.mfa import totp

    await env["set"](login_mode="google", sso_origin="migration", totp_required=True)
    uid = await env["mkuser"]("a")
    # In modalita' SSO la politica TOTP non si applica (solo login_mode=password).
    assert hasattr(totp, "user_requires_enrollment")
    assert not await totp.user_requires_enrollment("default", uid)


async def _enroll_totp(env, uid):
    from datetime import datetime, timezone

    from src.data.models import User

    async with env["sm"]() as s:
        u = await s.get(User, uid)
        u.totp_secret_encrypted = "enc"
        u.totp_enabled_at = datetime.now(timezone.utc)
        await s.commit()


@with_env
async def test_link_wipes_totp_for_everyone(env, monkeypatch):
    await env["set"](login_mode="google", sso_origin="migration")
    adm = await env["mkuser"]("root", roles=["admin"])
    await _enroll_totp(env, adm)
    await env["prov"].link_identity_to_user(
        "default", adm, _claims("s1", "a@x.io"), {}, PROVIDER, finalize_migration=True
    )
    u = await env["get_user"](adm)
    assert u.totp_secret_encrypted is None and u.totp_enabled_at is None
    assert u.password_hash is None


async def _new_migration(env):
    """Simula SSO -> password -> SSO: apre una nuova migrazione ora."""
    from datetime import datetime, timezone

    await env["set"](login_mode="password", sso_origin=None, migration_started_at=None)
    await env["set"](
        login_mode="google",
        sso_origin="migration",
        migration_started_at=datetime.now(timezone.utc),
        migration_completed_at=None,
    )


async def _set_password(env, uid, pw="tmp"):
    from src.data.models import User
    from src.data.user_password import hash_password

    async with env["sm"]() as s:
        u = await s.get(User, uid)
        u.password_hash = hash_password(pw)
        await s.commit()


@with_env
async def test_second_migration_starts_fresh(env, monkeypatch):
    lm, prov = env["lm"], env["prov"]
    await env["set"](login_mode="google", sso_origin="migration")
    adm = await env["mkuser"]("root", roles=["admin"])
    bob = await env["mkuser"]("bob")
    for uid, sub in ((adm, "sa"), (bob, "sb")):
        await prov.link_identity_to_user(
            "default", uid, _claims(sub, f"{sub}@x.io"), {}, PROVIDER, finalize_migration=True
        )
    assert not await lm.is_migration_active("default")

    # Ritorno a password (password temporanee per tutti) e di nuovo SSO.
    await _new_migration(env)
    await _set_password(env, bob)
    await _set_password(env, adm)
    await _enroll_totp(env, bob)

    # Le identita' della migrazione precedente non contano.
    assert await lm.is_migration_active("default")
    assert await lm.pending_users_count("default", "google") == 2
    assert await lm.user_needs_link("default", bob)
    # Il passaggio a SSO non deve cancellare le password temporanee.
    assert await lm.finalize_linked_users("default", "google") == 0
    await lm._check_migration_completion("default", "google")
    assert (await env["get_user"](bob)).password_hash is not None
    assert await lm.is_migration_active("default")

    # Bob ricollega lo stesso account: migrato, password e TOTP rimossi.
    await prov.link_identity_to_user(
        "default", bob, _claims("sb", "sb@x.io"), {}, PROVIDER, finalize_migration=True
    )
    assert not await lm.user_needs_link("default", bob)
    b = await env["get_user"](bob)
    assert b.password_hash is None and b.totp_secret_encrypted is None
    assert await lm.is_migration_active("default")

    # Anche l'admin riconferma: migrazione completata.
    await prov.link_identity_to_user(
        "default", adm, _claims("sa", "sa@x.io"), {}, PROVIDER, finalize_migration=True
    )
    assert not await lm.is_migration_active("default")


@with_env
async def test_relink_stale_identity_with_new_subject(env, monkeypatch):
    lm, prov = env["lm"], env["prov"]
    await env["set"](login_mode="google", sso_origin="migration")
    bob = await env["mkuser"]("bob")
    await prov.link_identity_to_user("default", bob, _claims("old", "old@x.io"), {}, PROVIDER)
    # Nella stessa migrazione un subject diverso resta vietato.
    with pytest.raises(ValueError, match="sso_user_already_linked"):
        await prov.link_identity_to_user("default", bob, _claims("new", "new@x.io"), {}, PROVIDER)

    await _new_migration(env)
    await _set_password(env, bob)
    await prov.link_identity_to_user(
        "default", bob, _claims("new", "new@x.io"), {}, PROVIDER, finalize_migration=True
    )
    from src.data.models import UserSsoIdentity

    async with env["sm"]() as s:
        rows = (
            await s.execute(select(UserSsoIdentity).where(UserSsoIdentity.user_id == bob))
        ).scalars().all()
    assert [r.subject for r in rows] == ["new"]
    assert not await lm.user_needs_link("default", bob)


@with_env
async def test_sso_login_with_stale_identity_confirms(env, monkeypatch):
    lm, prov = env["lm"], env["prov"]
    await env["set"](login_mode="google", sso_origin="migration")
    bob = await env["mkuser"]("bob")
    await prov.link_identity_to_user("default", bob, _claims("sb", "sb@x.io"), {}, PROVIDER)

    await _new_migration(env)
    await _set_password(env, bob)
    assert await lm.user_needs_link("default", bob)
    user = await prov.resolve_user(_claims("sb", "sb@x.io"), {}, PROVIDER, migration_active=True)
    assert user
    assert not await lm.user_needs_link("default", bob)
    assert (await env["get_user"](bob)).password_hash is None
    assert not await lm.is_migration_active("default")


@with_env
async def test_recover_sets_temporary_password(env, monkeypatch):
    from src.auth import recover
    from src.data.user_password import verify_password

    await env["set"](login_mode="google", sso_origin="migration")
    adm = await env["mkuser"]("root", roles=["admin"])
    await env["prov"].link_identity_to_user(
        "default", adm, _claims("s1", "a@x.io"), {}, PROVIDER, finalize_migration=True
    )
    assert (await env["get_user"](adm)).password_hash is None
    assert await recover._set_password("root", "emergency-pw") == 0
    u = await env["get_user"](adm)
    assert verify_password("emergency-pw", u.password_hash)
    assert u.must_change_password
    assert await recover._set_password("ghost", None) == 1
