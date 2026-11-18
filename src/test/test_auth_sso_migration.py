import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.data.bootstrap import ensure_bootstrap_schema
from src.test.smtp_fakes import configure_smtp, install_fake_smtp, patch_session_makers

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

    import src.auth.sso.config_service as cs
    from src.notifications import smtp_settings

    for mod in (lm, prov, ca, cs):
        monkeypatch.setattr(mod, "get_async_session_maker", lambda: sm)
    patch_session_makers(monkeypatch, sm)
    lm._SETTINGS_CACHE.clear()
    lm._PENDING_CACHE.clear()
    smtp_settings._CACHE.clear()
    monkeypatch.setenv("AION_CHAT_URL", "https://chat.example.com")
    fake_smtp = install_fake_smtp(monkeypatch)
    await configure_smtp()

    async def mkuser(name: str, roles=None) -> str:
        return await create_password_user(
            tenant_id="default",
            identifier=name,
            password=f"pw-{name}",
            roles=roles,
            session_maker=sm,
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

    yield {
        "sm": sm,
        "lm": lm,
        "prov": prov,
        "mkuser": mkuser,
        "set": set_settings,
        "get_user": get_user,
        "smtp": fake_smtp,
    }
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
    await env["set"](
        login_mode="google", sso_origin="migration", clear_password_on_link=True
    )
    bob = await env["mkuser"]("bob")
    adm = await env["mkuser"]("root", roles=["admin"])
    for uid, sub in ((bob, "s-bob"), (adm, "s-adm")):
        await env["prov"].link_identity_to_user(
            "default",
            uid,
            _claims(sub, f"{sub}@x.io"),
            {},
            PROVIDER,
            finalize_migration=True,
        )
    assert (await env["get_user"](bob)).password_hash is None
    # Anche l'admin: l'accesso di emergenza passa da src.auth.recover.
    assert (await env["get_user"](adm)).password_hash is None


@with_env
async def test_link_without_finalize_keeps_password(env, monkeypatch):
    # admin_validate: ancora in modalita' password, anche se l'admin e' l'unico utente.
    await env["set"](login_mode="password", clear_password_on_link=True)
    adm = await env["mkuser"]("root", roles=["admin"])
    await env["prov"].link_identity_to_user(
        "default", adm, _claims("s1", "a@x.io"), {}, PROVIDER
    )
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
    await env["prov"].link_identity_to_user(
        "default", a, _claims("sa", "a@x.io"), {}, PROVIDER, finalize_migration=True
    )
    assert await lm.is_migration_active("default")
    assert await lm.password_login_visible("default")
    await env["prov"].link_identity_to_user(
        "default", b, _claims("sb", "b@x.io"), {}, PROVIDER, finalize_migration=True
    )
    lm._invalidate_cache("default")
    assert not await lm.is_migration_active("default")
    assert not await lm.password_login_visible("default")


@with_env
async def test_cleared_password_users_not_pending(env, monkeypatch):
    lm = env["lm"]
    await env["set"](login_mode="google", sso_origin="migration")
    a = await env["mkuser"]("a")
    await env["mkuser"]("b")
    await env["prov"].link_identity_to_user(
        "default", a, _claims("sa", "a@x.io"), {}, PROVIDER, finalize_migration=True
    )
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
            "default",
            uid,
            _claims(sub, f"{sub}@x.io"),
            {},
            PROVIDER,
            finalize_migration=True,
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
    await prov.link_identity_to_user(
        "default", bob, _claims("old", "old@x.io"), {}, PROVIDER
    )
    # Nella stessa migrazione un subject diverso resta vietato.
    with pytest.raises(ValueError, match="sso_user_already_linked"):
        await prov.link_identity_to_user(
            "default", bob, _claims("new", "new@x.io"), {}, PROVIDER
        )

    await _new_migration(env)
    await _set_password(env, bob)
    await prov.link_identity_to_user(
        "default",
        bob,
        _claims("new", "new@x.io"),
        {},
        PROVIDER,
        finalize_migration=True,
    )
    from src.data.models import UserSsoIdentity

    async with env["sm"]() as s:
        rows = (
            (
                await s.execute(
                    select(UserSsoIdentity).where(UserSsoIdentity.user_id == bob)
                )
            )
            .scalars()
            .all()
        )
    assert [r.subject for r in rows] == ["new"]
    assert not await lm.user_needs_link("default", bob)


@with_env
async def test_sso_login_with_stale_identity_confirms(env, monkeypatch):
    lm, prov = env["lm"], env["prov"]
    await env["set"](login_mode="google", sso_origin="migration")
    bob = await env["mkuser"]("bob")
    await prov.link_identity_to_user(
        "default", bob, _claims("sb", "sb@x.io"), {}, PROVIDER
    )

    await _new_migration(env)
    await _set_password(env, bob)
    assert await lm.user_needs_link("default", bob)
    user = await prov.resolve_user(
        _claims("sb", "sb@x.io"), {}, PROVIDER, migration_active=True
    )
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


@with_env
async def test_email_follows_new_provider(env, monkeypatch):
    prov = env["prov"]
    ms = {"provider": "microsoft", "auto_provision": False}
    await env["set"](login_mode="microsoft", sso_origin="migration")
    bob = await env["mkuser"]("bob")
    ms_claims = {
        "tid": "t",
        "oid": "o",
        "preferred_username": "bob@corp.onmicrosoft.com",
        "name": "Bob",
    }
    await prov.link_identity_to_user(
        "default", bob, ms_claims, {}, ms, finalize_migration=True
    )
    assert (await env["get_user"](bob)).email == "bob@corp.onmicrosoft.com"

    # admin_validate su Google: email invariata finche' non si passa davvero.
    await _new_migration(env)
    await prov.link_identity_to_user(
        "default", bob, _claims("g1", "Bob@Gmail.com"), {}, PROVIDER
    )
    assert (await env["get_user"](bob)).email == "bob@corp.onmicrosoft.com"
    # Login SSO col nuovo provider: l'email segue Google.
    await prov.resolve_user(
        _claims("g1", "Bob@Gmail.com"), {}, PROVIDER, migration_active=True
    )
    assert (await env["get_user"](bob)).email == "bob@gmail.com"


# --- Policy nuovi account SSO ---------------------------------------------


@with_env
async def test_signup_closed_blocks_new_but_not_existing(env, monkeypatch):
    prov = env["prov"]
    await env["set"](login_mode="google", sso_origin="first_setup")
    existing = await prov.resolve_user(_claims("old", "old@x.io"), {}, PROVIDER)

    await env["set"](sso_signup_policy="closed")
    with pytest.raises(ValueError, match="sso_signup_closed"):
        await prov.resolve_user(_claims("new", "new@x.io"), {}, PROVIDER)
    # Chi ha gia' un'identita' collegata continua ad accedere.
    again = await prov.resolve_user(_claims("old", "old@x.io"), {}, PROVIDER)
    assert again["id"] == existing["id"]


@with_env
async def test_signup_allowlist_emails_and_domains(env, monkeypatch):
    import json

    prov = env["prov"]
    await env["set"](
        login_mode="google",
        sso_origin="first_setup",
        sso_signup_policy="allowlist",
        sso_signup_allowlist=json.dumps(["anna@x.io", "@pilot.x.io"]),
    )
    assert await prov.resolve_user(_claims("a", "Anna@X.io"), {}, PROVIDER)
    assert await prov.resolve_user(_claims("p", "piero@pilot.x.io"), {}, PROVIDER)
    with pytest.raises(ValueError, match="sso_signup_not_allowed"):
        await prov.resolve_user(_claims("o", "other@x.io"), {}, PROVIDER)
    # Il dominio non copre i sottodomini o i domini che lo contengono.
    with pytest.raises(ValueError, match="sso_signup_not_allowed"):
        await prov.resolve_user(_claims("s", "s@sub.pilot.x.io"), {}, PROVIDER)


@with_env
async def test_signup_policy_applies_during_migration(env, monkeypatch):
    import json

    prov = env["prov"]
    await env["set"](login_mode="google", sso_origin="migration")
    # Chi non potrebbe comunque avere un account vede il motivo vero,
    # non l'invito a collegarsi con una password che non ha.
    await env["set"](sso_signup_policy="closed")
    with pytest.raises(ValueError, match="sso_signup_closed"):
        await prov.resolve_user(
            _claims("n", "n@x.io"), {}, PROVIDER, migration_active=True
        )
    await env["set"](
        sso_signup_policy="allowlist", sso_signup_allowlist=json.dumps(["ok@x.io"])
    )
    with pytest.raises(ValueError, match="sso_signup_not_allowed"):
        await prov.resolve_user(
            _claims("n", "n@x.io"), {}, PROVIDER, migration_active=True
        )
    # Ammesso dalla policy: durante la migrazione deve comunque collegarsi.
    with pytest.raises(ValueError, match="sso_not_linked"):
        await prov.resolve_user(
            _claims("ok", "ok@x.io"), {}, PROVIDER, migration_active=True
        )


@with_env
async def test_signup_policy_ignored_without_auto_provision(env, monkeypatch):
    # Login dal pannello admin: non crea mai account, resta sso_not_linked.
    await env["set"](
        login_mode="google", sso_origin="first_setup", sso_signup_policy="closed"
    )
    with pytest.raises(ValueError, match="sso_not_linked"):
        await env["prov"].resolve_user(
            _claims("n", "n@x.io"), {}, {**PROVIDER, "auto_provision": False}
        )


@with_env
async def test_signup_open_is_default(env, monkeypatch):
    await env["set"](login_mode="google", sso_origin="first_setup")
    settings = await env["lm"].get_login_settings("default")
    assert settings["sso_signup_policy"] == "open"
    assert settings["sso_signup_allowlist"] == []
    assert await env["prov"].resolve_user(_claims("n", "n@x.io"), {}, PROVIDER)


def test_allowlist_entry_normalization():
    from src.auth.sso.login_mode import normalize_allowlist_entry, signup_denied_reason

    assert (
        normalize_allowlist_entry("  Mario.Rossi@Azienda.IT ")
        == "mario.rossi@azienda.it"
    )
    assert normalize_allowlist_entry("@Azienda.it") == "@azienda.it"
    for bad in ("azienda.it", "@", "@azienda", "mario@", "a b@x.it", "@-x.it"):
        assert normalize_allowlist_entry(bad) is None, bad
    assert normalize_allowlist_entry("a@" + "b" * 260 + ".it") is None  # > 254
    assert signup_denied_reason("a@x.it", "bogus", []) is None  # policy ignota -> open
    assert (
        signup_denied_reason(None, "allowlist", ["@x.it"]) == "sso_signup_not_allowed"
    )


def test_allowlist_email_regex_is_linear():
    """Niente backtracking quadratico (ReDoS) su ``a@a.a.a...`` non valido."""
    import time

    from src.auth.sso.login_mode import _EMAIL_RE

    evil = "!@!." + "!." * 50_000 + "@"
    t0 = time.perf_counter()
    assert _EMAIL_RE.match(evil) is None
    assert time.perf_counter() - t0 < 0.5


# --- Eliminazione utenti ----------------------------------------------------


@with_env
async def test_delete_user_completes_migration_and_drops_identities(env, monkeypatch):
    import src.api.admin as admin_api
    from src.data.models import UserSsoIdentity

    monkeypatch.setattr(admin_api, "get_async_session_maker", lambda: env["sm"])
    lm, prov = env["lm"], env["prov"]
    await env["set"](login_mode="google", sso_origin="migration")
    adm = await env["mkuser"]("root", roles=["admin"])
    bob = await env["mkuser"]("bob")
    await prov.link_identity_to_user(
        "default",
        adm,
        _claims("s-adm", "root@x.io"),
        {},
        PROVIDER,
        finalize_migration=True,
    )
    # Bob ha un'identita' di una migrazione precedente, non riconfermata.
    async with env["sm"]() as s:
        s.add(
            UserSsoIdentity(
                id="old-bob",
                tenant_id="default",
                user_id=bob,
                provider="google",
                subject="s-bob",
                email="bob@x.io",
            )
        )
        await s.commit()
    assert await lm.is_migration_active("default")

    await admin_api.delete_user(bob)

    # Bob era l'ultimo da migrare: la migrazione si chiude subito.
    assert not await lm.is_migration_active("default")
    async with env["sm"]() as s:
        left = (
            (
                await s.execute(
                    select(UserSsoIdentity).where(UserSsoIdentity.user_id == bob)
                )
            )
            .scalars()
            .all()
        )
    assert left == []
    # Senza identita' orfana la stessa persona puo' di nuovo ottenere un account.
    assert await prov.resolve_user(_claims("s-bob", "bob@x.io"), {}, PROVIDER)


async def _unlink(env, monkeypatch, uid):
    import src.api.admin_auth_mode as aam
    from src.data.models import UserSsoIdentity

    monkeypatch.setattr(aam, "get_async_session_maker", lambda: env["sm"])
    async with env["sm"]() as s:
        ident = (
            (
                await s.execute(
                    select(UserSsoIdentity).where(UserSsoIdentity.user_id == uid)
                )
            )
            .scalars()
            .first()
        )
    return await aam.unlink_sso_identity(uid, ident.id, request=None, auth=_admin())


def _admin():
    from src.api.auth_login import ChatAuthIdentity

    return ChatAuthIdentity(user_row_id=None, identifier="root", via="chat_token")


def _sent_to(out) -> list:
    return [t["user_id"] for t in out["setup_links"]["sent"]]


def _assert_no_secrets(out) -> None:
    import json

    dumped = json.dumps(out, default=str)
    assert '"password":' not in dumped and "set-password" not in dumped


async def _all_linked(env):
    """Migrazione google completata: admin e bob collegati, senza password."""
    await env["set"](login_mode="google", sso_origin="migration")
    adm = await env["mkuser"]("root", roles=["admin"])
    bob = await env["mkuser"]("bob@x.io")
    for uid, sub, mail in ((adm, "s-adm", "root@x.io"), (bob, "s-bob", "bob@x.io")):
        await env["prov"].link_identity_to_user(
            "default", uid, _claims(sub, mail), {}, PROVIDER, finalize_migration=True
        )
    env["lm"]._invalidate_cache("default")
    assert not await env["lm"].is_migration_active("default")
    return adm, bob


@with_env
async def test_unlink_without_password_restarts_standard_relink(env, monkeypatch):
    lm, prov = env["lm"], env["prov"]
    _, bob = await _all_linked(env)
    assert not (await env["get_user"](bob)).password_hash

    out = await _unlink(env, monkeypatch, bob)

    # Link per impostare la password inviato a bob (mai all'admin), migrazione
    # riaperta: col solo link attivo bob conta come "in attesa".
    assert _sent_to(out) == [bob]
    _assert_no_secrets(out)
    assert env["smtp"].sent[-1]["To"] == "bob@x.io"
    assert not (await env["get_user"](bob)).password_hash
    assert await lm.pending_users_count("default", "google") == 1
    assert await lm.is_migration_active("default")
    assert await lm.password_login_visible("default")
    assert await lm.user_needs_link("default", bob)
    # L'SSO diretto non crea un secondo account: va collegato dopo la password.
    await env["set"](sso_signup_policy="closed")
    with pytest.raises(ValueError, match="sso_not_linked"):
        await prov.resolve_user(
            _claims("s-bob-new", "bob@x.io"), {}, PROVIDER, migration_active=True
        )

    # Collegando di nuovo la migrazione si richiude.
    await prov.link_identity_to_user(
        "default",
        bob,
        _claims("s-bob", "bob@x.io"),
        {},
        PROVIDER,
        finalize_migration=True,
    )
    lm._invalidate_cache("default")
    assert not await lm.is_migration_active("default")
    assert not await lm.user_needs_link("default", bob)


@with_env
async def test_unlink_after_first_setup_opens_migration(env, monkeypatch):
    lm = env["lm"]
    await env["set"](login_mode="google", sso_origin="first_setup")
    bob = await env["mkuser"]("bob")
    await env["prov"].link_identity_to_user(
        "default",
        bob,
        _claims("s-bob", "bob@x.io"),
        {},
        PROVIDER,
        finalize_migration=True,
    )
    lm._invalidate_cache("default")
    assert not await lm.password_login_visible("default")

    out = await _unlink(env, monkeypatch, bob)

    assert _sent_to(out) == [bob]
    assert (await lm.get_login_settings("default"))["sso_origin"] == "migration"
    assert await lm.password_login_visible("default")
    assert await lm.user_needs_link("default", bob)


@with_env
async def test_unlink_other_provider_changes_nothing(env, monkeypatch):
    from src.data.models import UserSsoIdentity

    lm = env["lm"]
    _, bob = await _all_linked(env)
    async with env["sm"]() as s:
        for ident in (
            await s.execute(
                select(UserSsoIdentity).where(UserSsoIdentity.user_id == bob)
            )
        ).scalars():
            ident.provider = "microsoft"
        s.add(
            UserSsoIdentity(
                id="g-bob",
                tenant_id="default",
                user_id=bob,
                provider="google",
                subject="s-bob-g",
                email="bob@x.io",
            )
        )
        await s.commit()
    # Solo l'identita' microsoft (non attiva) viene scollegata.
    import src.api.admin_auth_mode as aam

    monkeypatch.setattr(aam, "get_async_session_maker", lambda: env["sm"])
    async with env["sm"]() as s:
        ms = (
            (
                await s.execute(
                    select(UserSsoIdentity).where(
                        UserSsoIdentity.user_id == bob,
                        UserSsoIdentity.provider == "microsoft",
                    )
                )
            )
            .scalars()
            .first()
        )
    out = await aam.unlink_sso_identity(bob, ms.id, request=None, auth=_admin())

    assert "setup_links" not in out
    lm._invalidate_cache("default")
    assert not await lm.is_migration_active("default")


@with_env
async def test_unlink_with_password_reopens_without_new_password(env, monkeypatch):
    lm = env["lm"]
    await env["set"](login_mode="google", sso_origin="migration")
    bob = await env["mkuser"]("bob")
    await env["prov"].link_identity_to_user(
        "default",
        bob,
        _claims("s-bob", "bob@x.io"),
        {},
        PROVIDER,
        finalize_migration=True,
    )
    # Es. password impostata dal link di "Senza accesso" e poi ricollegato.
    await _set_password(env, bob)
    env["lm"]._invalidate_cache("default")
    old_hash = (await env["get_user"](bob)).password_hash
    assert old_hash and not await lm.is_migration_active("default")

    out = await _unlink(env, monkeypatch, bob)

    assert "setup_links" not in out
    assert (await env["get_user"](bob)).password_hash == old_hash
    assert await lm.is_migration_active("default")
    assert await lm.user_needs_link("default", bob)


@with_env
async def test_setup_links_reopen_completed_migration(env, monkeypatch):
    lm = env["lm"]
    _, bob = await _all_linked(env)
    from src.data.models import UserSsoIdentity
    from sqlalchemy import delete

    async with env["sm"]() as s:
        await s.execute(delete(UserSsoIdentity).where(UserSsoIdentity.user_id == bob))
        await s.commit()
    lm._invalidate_cache("default")

    out = await lm.send_migration_links("default", [bob], "google", actor_user_id=None)

    assert out["delivery"] == "email"
    assert _sent_to(out) == [bob]
    assert await lm.is_migration_active("default")
    assert await lm.password_login_visible("default")


@with_env
async def test_setup_links_refused_for_linked_user(env, monkeypatch):
    _, bob = await _all_linked(env)
    with pytest.raises(ValueError, match="user_already_linked"):
        await env["lm"].send_migration_links(
            "default", [bob], "google", actor_user_id=None
        )


async def _disable_smtp(env) -> None:
    from src.data.models import SmtpSettings
    from src.notifications.smtp_settings import invalidate_cache

    async with env["sm"]() as s:
        (await s.get(SmtpSettings, "default")).enabled = False
        await s.commit()
    invalidate_cache("default")


@with_env
async def test_unlink_without_smtp_issues_temp_password(env, monkeypatch):
    from src.data.user_password import verify_password

    lm = env["lm"]
    _, bob = await _all_linked(env)
    await _disable_smtp(env)

    out = await _unlink(env, monkeypatch, bob)

    assert out["delivery"] == "temp_password"
    assert [t["user_id"] for t in out["temp_passwords"]] == [bob]
    assert env["smtp"].sent == []
    u = await env["get_user"](bob)
    assert verify_password(out["temp_passwords"][0]["password"], u.password_hash)
    assert u.temp_password_expires_at is not None
    # Con la password temporanea bob si ricollega col flusso standard.
    assert await lm.is_migration_active("default")
    assert await lm.user_needs_link("default", bob)
    await env["prov"].link_identity_to_user(
        "default",
        bob,
        _claims("s-bob", "bob@x.io"),
        {},
        PROVIDER,
        finalize_migration=True,
    )
    u = await env["get_user"](bob)
    assert u.temp_password_expires_at is None and not u.password_hash


@with_env
async def test_back_to_password_without_smtp_issues_temp_passwords(env, monkeypatch):
    from src.data.models import AuthSettings
    from src.data.user_password import verify_password

    lm = env["lm"]
    adm, bob = await _all_linked(env)
    await _disable_smtp(env)

    result = await lm.set_login_mode("default", "password", actor_user_id=adm)

    assert result["login_mode"] == "password"
    assert result["delivery"] == "temp_password"
    issued = {t["user_id"]: t["password"] for t in result["temp_passwords"]}
    assert sorted(issued) == sorted([adm, bob])
    assert env["smtp"].sent == []
    async with env["sm"]() as s:
        assert (await s.get(AuthSettings, "default")).login_mode == "password"
    for uid, plain in issued.items():
        u = await env["get_user"](uid)
        assert verify_password(plain, u.password_hash)
        assert u.temp_password_expires_at is not None and u.must_change_password


@with_env
async def test_back_to_password_sends_links_not_passwords(env, monkeypatch):
    lm = env["lm"]
    adm, bob = await _all_linked(env)

    result = await lm.set_login_mode("default", "password", actor_user_id=adm)

    assert result["login_mode"] == "password"
    assert result["delivery"] == "email" and "temp_passwords" not in result
    assert sorted(_sent_to(result)) == sorted([adm, bob])
    _assert_no_secrets(result)
    assert sorted(m["To"] for m in env["smtp"].sent) == ["bob@x.io", "root@x.io"]
    for uid in (adm, bob):
        assert (await env["get_user"](uid)).password_hash is None


# --- Local accounts (third parties without SSO) -----------------------------


async def _make_local(env, uid: str) -> None:
    """Mark ``uid`` as a local account (always exempt too, like the API does)."""
    from src.data.models import User

    async with env["sm"]() as s:
        u = await s.get(User, uid)
        u.local_account = True
        u.sso_migration_exempt = True
        await s.commit()
    env["lm"]._invalidate_cache("default")


async def _login(username: str, password: str):
    from src.api.auth_login import LoginBody, login

    return await login(LoginBody(username=username, password=password))


@with_env
async def test_local_account_logs_in_after_migration_completes(env, monkeypatch):
    """Scenario: SSO active, migration finished (password form hidden for
    everybody). A local account still signs in with its password and is not
    asked to link SSO; a plain exempt user is still refused."""
    from fastapi import HTTPException

    await env["set"](login_mode="google", sso_origin="first_setup")
    local = await env["mkuser"]("ext")
    await _make_local(env, local)
    plain_exempt = await env["mkuser"]("old")
    async with env["sm"]() as s:
        from src.data.models import User

        (await s.get(User, plain_exempt)).sso_migration_exempt = True
        await s.commit()
    env["lm"]._invalidate_cache("default")

    assert not await env["lm"].password_login_visible("default")
    res = await _login("ext", "pw-ext")
    assert res["access_token"]
    assert res["sso_link_required"] is False

    # No regression: an exempt user that is NOT local keeps being refused.
    with pytest.raises(HTTPException) as e:
        await _login("old", "pw-old")
    assert e.value.status_code == 403
    assert e.value.detail["code"] == "password_login_disabled"


@with_env
async def test_exempt_non_local_still_sso_required_during_migration(env, monkeypatch):
    """Scenario: migration in progress (form visible). An exempt non-local user
    gets sso_required, exactly as before this feature."""
    from fastapi import HTTPException

    await env["set"](login_mode="google", sso_origin="migration")
    await env["mkuser"]("pending")  # keeps the migration open
    uid = await env["mkuser"]("old")
    async with env["sm"]() as s:
        from src.data.models import User

        (await s.get(User, uid)).sso_migration_exempt = True
        await s.commit()
    env["lm"]._invalidate_cache("default")
    with pytest.raises(HTTPException) as e:
        await _login("old", "pw-old")
    assert e.value.detail["code"] == "sso_required"


@with_env
async def test_local_login_available_flag(env, monkeypatch):
    """Scenario: local_login_available is true only when an active local
    account exists (password or live setup link)."""
    lm = env["lm"]
    await env["set"](login_mode="google", sso_origin="first_setup")
    assert not await lm.local_login_available("default")
    uid = await env["mkuser"]("ext")
    assert not await lm.local_login_available("default")  # not local yet
    await _make_local(env, uid)
    assert await lm.local_login_available("default")


@with_env
async def test_local_account_never_pending_nor_linked(env, monkeypatch):
    """Scenario: local accounts are not counted as pending, never need to link,
    and keep their password even if an identity is attached by hand."""
    lm = env["lm"]
    await env["set"](login_mode="google", sso_origin="migration")
    uid = await env["mkuser"]("ext")
    await _make_local(env, uid)
    assert await lm.pending_users_count("default", "google") == 0
    assert not await lm.user_needs_link("default", uid)
    await env["prov"].link_identity_to_user(
        "default",
        uid,
        _claims("sx", "ext@x.io"),
        {},
        PROVIDER,
        finalize_migration=True,
    )
    await lm.finalize_linked_users("default", "google")
    assert (await env["get_user"](uid)).password_hash is not None


@with_env
async def test_setup_links_refused_for_local_account(env, monkeypatch):
    """Scenario: migration links are never sent to a local account (they would
    reopen the migration)."""
    await env["set"](login_mode="google", sso_origin="first_setup")
    uid = await env["mkuser"]("ext")
    await _make_local(env, uid)
    with pytest.raises(ValueError, match="local_account_no_sso"):
        await env["lm"].send_migration_links(
            "default", [uid], "google", actor_user_id=None
        )
    assert not await env["lm"].is_migration_active("default")


@with_env
async def test_exempt_endpoint_refuses_local_account(env, monkeypatch):
    """Scenario: the exempt toggle cannot un-exempt a local account."""
    from fastapi import HTTPException

    import src.api.admin_auth_mode as aam
    from src.api.admin_auth_mode import ExemptBody, set_user_exempt
    from src.api.auth_login import ChatAuthIdentity

    # admin_auth_mode binds the session maker at import time: point it at the
    # test DB too.
    monkeypatch.setattr(aam, "get_async_session_maker", lambda: env["sm"])
    await env["set"](login_mode="google", sso_origin="first_setup")
    uid = await env["mkuser"]("ext")
    await _make_local(env, uid)
    with pytest.raises(HTTPException) as e:
        await set_user_exempt(
            uid,
            ExemptBody(exempt=False),
            auth=ChatAuthIdentity(user_row_id="a", via="chat_token", roles=["admin"]),
        )
    assert e.value.detail == {"code": "local_account_always_exempt"}


@with_env
async def test_auth_status_exposes_local_login_available(env, monkeypatch):
    """Scenario: /auth/status tells chat-ui whether to offer the "local account"
    link: false in password mode and without locals, true only in SSO mode
    with at least one active local account."""
    from src.api.auth_login import auth_status

    uid = await env["mkuser"]("ext")
    await _make_local(env, uid)
    # Password mode: the main form is already visible, no extra link needed.
    assert (await auth_status())["local_login_available"] is False
    # SSO mode and a local account exists: the link must be offered.
    await env["set"](login_mode="google", sso_origin="first_setup")
    assert (await auth_status())["local_login_available"] is True
    # Break-glass restores the password form for everyone: no extra link.
    monkeypatch.setenv("AION_SSO_FORCE_PASSWORD", "1")
    env["lm"]._invalidate_cache("default")
    assert (await auth_status())["local_login_available"] is False


@with_env
async def test_sso_link_start_refused_for_local_account(env, monkeypatch):
    """Scenario: a local account cannot start the SSO link flow (it would clear
    its password and lock the third party out)."""
    from fastapi import HTTPException

    import src.api.auth_sso as asso
    from src.api.auth_login import ChatAuthIdentity

    monkeypatch.setattr(asso, "get_async_session_maker", lambda: env["sm"])
    await env["set"](login_mode="google", sso_origin="first_setup")
    uid = await env["mkuser"]("ext")
    await _make_local(env, uid)
    with pytest.raises(HTTPException) as e:
        await asso.sso_link_start(
            None,
            asso.LinkStartBody(return_to="/"),
            auth=ChatAuthIdentity(user_row_id=uid, via="chat_token"),
        )
    assert e.value.status_code == 409
    assert e.value.detail == {"code": "local_account_no_sso"}


@with_env
async def test_password_link_for_local_account_does_not_reopen_migration(
    env, monkeypatch
):
    """Scenario: an admin re-sends a password link to a local account while SSO
    is active. The link is an invite (not a migration link) and the completed
    migration stays closed, so new SSO sign-ups are not blocked."""
    import src.api.admin as admin_mod
    from src.api.admin import send_password_link
    from src.data.models import User

    # admin.py binds the session maker at import time: point it at the test DB.
    monkeypatch.setattr(admin_mod, "get_async_session_maker", lambda: env["sm"])
    lm = env["lm"]
    await env["set"](login_mode="google", sso_origin="first_setup")
    uid = await env["mkuser"]("ext")
    async with env["sm"]() as s:
        u = await s.get(User, uid)
        u.email = "ext@partner.io"
        u.password_hash = None  # invited but not yet activated
        await s.commit()
    await _make_local(env, uid)

    out = await send_password_link(uid, request=None, auth=_admin())

    assert out["purpose"] == "invite"
    assert not await lm.is_migration_active("default")


@with_env
async def test_forgot_password_available_for_local_account_under_sso(env, monkeypatch):
    """Scenario: after the migration the tenant-wide password form is hidden,
    but "forgot password" must stay available once a local account exists
    (it is the only way such an account can recover access)."""
    from src.api.auth_password_setup import password_reset_available

    await env["set"](login_mode="google", sso_origin="first_setup")
    assert await password_reset_available("default") is False
    uid = await env["mkuser"]("ext")
    await _make_local(env, uid)
    assert await password_reset_available("default") is True
