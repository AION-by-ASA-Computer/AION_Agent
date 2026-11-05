"""Admin configuration of the SMB file servers (``smb_files`` connector).

Covers ``/admin/smb`` (global settings) and ``/admin/smb/servers`` (CRUD +
per-server test), the write side of ``src/tools/smb_files/settings_store.py``
(persistence, cache, Hub sync), the ``f3a4b5c034`` migration from the
single-server row and the connection probe ``src/tools/smb_files/probe.py``
with smbprotocol faked, so no network is needed.  Pattern of
``test_smtp_settings.py``.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import List

import pytest
from fastapi import HTTPException

from src.tools.smb_files import probe, settings_store
from src.tools.smb_files.settings_store import SmbServer, SmbShare

SECRET = "Win-S3cret!"
_ROOT = Path(__file__).resolve().parents[2]


async def _setup(monkeypatch, tmp_path):
    """Fresh SQLite DB with the unified schema and one admin user."""
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.delenv("AION_DEFAULT_TENANT_ID", raising=False)

    from src.data import engine as engine_mod
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_async_session_maker, init_engine
    from src.data.models import User

    monkeypatch.setattr(engine_mod, "_engine", None)
    monkeypatch.setattr(engine_mod, "_session_factory", None)
    settings_store._CACHE.clear()
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
    return get_async_session_maker()


def _auth():
    from src.api.auth_login import ChatAuthIdentity

    return ChatAuthIdentity(
        user_row_id="a1", identifier="root", via="chat_token", roles=["admin"]
    )


def _server(**kw):
    """A valid server body (fs01, DEFAULT set); ``kw`` overrides fields."""
    from src.api.admin_smb import SmbServerBody

    base = {
        "alias": "fs01",
        "host": "fs01.corp.local",
        "port": 445,
        "default_domain": "CORP",
        "shares": [
            {"name": "Documenti", "read_only": False, "label": "Documenti"},
            {"name": "Archivio", "read_only": True},
        ],
    }
    base.update(kw)
    return SmbServerBody(**base)


def _global(**kw):
    from src.api.admin_smb import SmbGlobalBody

    base = {"enabled": True}
    base.update(kw)
    return SmbGlobalBody(**base)


async def _add(**kw) -> str:
    """Create a server through the API and return its id."""
    from src.api.admin_smb import create_server

    return (await create_server(_server(**kw), auth=_auth()))["server_id"]


async def _audit_ops(sm) -> List[tuple]:
    from sqlalchemy import select

    from src.data.models import AuditLog

    async with sm() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    return [(r.operation, r.payload) for r in rows]


async def _expect(code, coro, status=None):
    """Await ``coro`` and assert it fails with ``code`` (and ``status`` if given)."""
    with pytest.raises(HTTPException) as e:
        await coro
    assert e.value.detail == {"code": code}
    if status is not None:
        assert e.value.status_code == status


@pytest.mark.anyio
async def test_get_defaults_without_rows(monkeypatch, tmp_path):
    """No row yet: admin-ui gets a disabled, unconfigured view with no servers."""
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import get_smb

    res = await get_smb(auth=_auth())
    assert res["configured"] is False and res["enabled"] is False
    assert (res["servers"], res["max_read_mb"], res["lockout_minutes"]) == ([], 25, 30)


@pytest.mark.anyio
async def test_servers_feed_mcp_config(monkeypatch, tmp_path):
    """Servers + global switch are visible to the MCP read path (cache invalidated) and audited."""
    sm = await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import put_smb

    # Prime the cache with "not configured" to prove the saves invalidate it.
    assert await settings_store.get_smb_config("default") is None

    await _add(auth_protocol="Negotiate")
    await _add(alias="FS02", host="FS02.estero.local", credential_set="estero")
    res = await put_smb(_global(max_read_mb=10, lockout_minutes=45), auth=_auth())
    assert res["configured"] and res["enabled"]
    assert [s["alias"] for s in res["servers"]] == ["fs01", "fs02"]
    assert res["servers"][0]["shares"][1] == {
        "name": "Archivio",
        "read_only": True,
        "label": "",
    }

    cfg = await settings_store.get_smb_config("default")
    assert cfg is not None
    fs01, fs02 = cfg.server("fs01"), cfg.server("fs02")
    assert (fs01.host, fs01.default_domain, fs01.auth_protocol) == (
        "fs01.corp.local",
        "CORP",
        "negotiate",
    )
    # Alias/host are stored lowercase, the credential set uppercase.
    assert (fs02.host, fs02.credential_set) == ("fs02.estero.local", "ESTERO")
    assert (cfg.max_read_mb, cfg.lockout_minutes) == (10, 45)
    assert fs01.share("archivio").read_only is True

    ops = [op for op, _ in await _audit_ops(sm)]
    assert ops == ["smb.server.create", "smb.server.create", "smb.update"]


@pytest.mark.anyio
async def test_disabled_server_and_draft_connector(monkeypatch, tmp_path):
    """A disabled server may have no shares; a disabled connector never reaches MCP."""
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import put_smb

    await _add(enabled=False, shares=[])
    res = await put_smb(_global(enabled=False), auth=_auth())
    assert res["enabled"] is False and res["configured"] is False
    assert await settings_store.get_smb_config("default") is None


@pytest.mark.anyio
async def test_server_validation(monkeypatch, tmp_path):
    """Bad alias/host/set, admin shares, sub-paths and duplicates are rejected with a code
    (an empty credential set is not an error: it means DEFAULT)."""
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import create_server

    for kw, code in (
        ({"alias": "-fs"}, "invalid_alias"),
        ({"alias": "fs 01"}, "invalid_alias"),
        ({"alias": ""}, "invalid_alias"),
        ({"credential_set": "est-ero"}, "invalid_credential_set"),
        ({"host": "bad host"}, "invalid_host"),
        ({"host": r"\\fs01"}, "invalid_host"),
        ({"host": ""}, "invalid_host"),
        ({"default_domain": "CORP\\x"}, "invalid_domain"),
        ({"auth_protocol": "kerberos"}, "invalid_auth_protocol"),
        ({"shares": [{"name": "C$"}]}, "invalid_share_name"),
        ({"shares": [{"name": "ADMIN$"}]}, "invalid_share_name"),
        ({"shares": [{"name": ".."}]}, "invalid_share_name"),
        ({"shares": [{"name": "Docs\\sub"}]}, "invalid_share_name"),
        ({"shares": [{"name": "Do*cs"}]}, "invalid_share_name"),
        ({"shares": [{"name": "Docs"}, {"name": "DOCS"}]}, "duplicate_share"),
        ({"shares": []}, "shares_required"),
    ):
        await _expect(code, create_server(_server(**kw), auth=_auth()), 400)


@pytest.mark.anyio
async def test_alias_and_host_are_unique_per_tenant(monkeypatch, tmp_path):
    """smbclient caches sessions per host and paths start with the alias: both stay unique."""
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import create_server, update_server

    first = await _add()
    second = await _add(alias="fs02", host="fs02.corp.local")
    await _expect(
        "duplicate_alias",
        create_server(_server(alias="FS01", host="other"), auth=_auth()),
        409,
    )
    await _expect(
        "duplicate_host",
        create_server(_server(alias="fs03", host="FS01.corp.local"), auth=_auth()),
        409,
    )
    await _expect(
        "duplicate_host",
        update_server(second, _server(alias="fs02", host="fs01.corp.local"), auth=_auth()),
        409,
    )
    # Saving a server with its own alias/host is not a conflict.
    res = await update_server(first, _server(label="Sede"), auth=_auth())
    assert res["servers"][0]["label"] == "Sede"


@pytest.mark.anyio
async def test_server_cap(monkeypatch, tmp_path):
    """At most MAX_SERVERS servers per tenant."""
    await _setup(monkeypatch, tmp_path)
    from src.api import admin_smb

    monkeypatch.setattr(admin_smb, "MAX_SERVERS", 2)
    await _add()
    await _add(alias="fs02", host="fs02")
    await _expect(
        "too_many_servers",
        admin_smb.create_server(_server(alias="fs03", host="fs03"), auth=_auth()),
        400,
    )


@pytest.mark.anyio
async def test_enabled_connector_needs_a_default_set_server(monkeypatch, tmp_path):
    """Users' DEFAULT pair gates the connector: enabling needs a usable DEFAULT-set server,
    and changes that would break an enabled connector are refused (409)."""
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import delete_server, put_smb, update_server

    await _expect("servers_required", put_smb(_global(), auth=_auth()), 400)
    estero = await _add(alias="fs02", host="fs02", credential_set="ESTERO")
    await _expect(
        "default_credential_set_required", put_smb(_global(), auth=_auth()), 400
    )

    main = await _add()
    await put_smb(_global(), auth=_auth())

    # The only DEFAULT server cannot be removed, disabled or moved to another set.
    await _expect("default_credential_set_required", delete_server(main, auth=_auth()), 409)
    await _expect(
        "default_credential_set_required",
        update_server(main, _server(enabled=False), auth=_auth()),
        409,
    )
    await _expect(
        "default_credential_set_required",
        update_server(main, _server(credential_set="ALTRO"), auth=_auth()),
        409,
    )
    # Other servers can change freely.
    res = await delete_server(estero, auth=_auth())
    assert [s["alias"] for s in res["servers"]] == ["fs01"]

    # With the connector off the same changes are allowed (draft configuration).
    await put_smb(_global(enabled=False), auth=_auth())
    res = await delete_server(main, auth=_auth())
    assert res["servers"] == []


@pytest.mark.anyio
async def test_unknown_server_ids(monkeypatch, tmp_path):
    """Update/delete/test of an unknown id answer 404 server_not_found."""
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import SmbTestBody, delete_server, test_server, update_server

    await _expect("server_not_found", update_server("nope", _server(), auth=_auth()), 404)
    await _expect("server_not_found", delete_server("nope", auth=_auth()), 404)
    await _expect(
        "server_not_found", test_server("nope", SmbTestBody(), auth=_auth()), 404
    )


@pytest.mark.anyio
async def test_put_syncs_hub_entry(monkeypatch, tmp_path):
    """The enabled switch is mirrored on McpServerConfig(smb_files), if present."""
    sm = await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import put_smb
    from src.data.models import McpServerConfig

    await _add()
    # Without a Hub row the save still succeeds and reports it.
    res = await put_smb(_global(), auth=_auth())
    assert res["connector_synced"] is False

    async with sm() as session:
        session.add(
            McpServerConfig(
                id="m1",
                server_slug="smb_files",
                display_name="File server",
                is_enabled_for_users=False,
            )
        )
        await session.commit()

    res = await put_smb(_global(), auth=_auth())
    assert res["connector_synced"] is True
    async with sm() as session:
        assert (await session.get(McpServerConfig, "m1")).is_enabled_for_users is True

    await put_smb(_global(enabled=False), auth=_auth())
    async with sm() as session:
        assert (await session.get(McpServerConfig, "m1")).is_enabled_for_users is False


@pytest.mark.anyio
async def test_connection_test_endpoint(monkeypatch, tmp_path, caplog):
    """The per-server test uses that server, records its outcome and never leaks the password."""
    sm = await _setup(monkeypatch, tmp_path)
    from src.api import admin_smb
    from src.api.admin_smb import SmbTestBody, get_smb, test_server

    # Incomplete server (no share yet): nothing to test.
    draft = await _add(alias="fs09", host="fs09", enabled=False, shares=[])
    await _expect("smb_not_configured", test_server(draft, SmbTestBody(), auth=_auth()), 409)

    # Works on a disabled (but complete) server: the admin tests before enabling.
    other = await _add(alias="fs02", host="fs02.estero.local", credential_set="ESTERO")
    sid = await _add(enabled=False)

    calls = []

    def fake_test(server, username=None, password=None):
        calls.append((server.host, username, password))
        if password == SECRET:
            return {"ok": False, "error": "auth_failed", "shares": []}
        return {"ok": True, "error": None, "negotiated": True, "shares": []}

    monkeypatch.setattr(admin_smb.probe, "test_connection", fake_test)

    await _expect(
        "credentials_incomplete",
        test_server(sid, SmbTestBody(username="mario"), auth=_auth()),
        400,
    )

    res = await test_server(sid, SmbTestBody(), auth=_auth())
    assert res["ok"] is True and calls[-1] == ("fs01.corp.local", None, None)

    caplog.set_level(logging.DEBUG)
    res = await test_server(
        sid, SmbTestBody(username="CORP\\mario", password=SECRET), auth=_auth()
    )
    assert res == {"ok": False, "error": "auth_failed", "shares": []}

    # The result is recorded on the tested server only.
    state = await get_smb(auth=_auth())
    by_id = {s["id"]: s for s in state["servers"]}
    assert (by_id[sid]["last_test_ok"], by_id[sid]["last_test_error"]) == (
        False,
        "auth_failed",
    )
    assert by_id[other]["last_test_at"] is None

    ops = await _audit_ops(sm)
    tests = [p for op, p in ops if op == "smb.server.test"]
    assert len(tests) == 2
    assert all(SECRET not in (p or "") for _, p in ops)
    assert json.loads(tests[-1])["with_credentials"] is True
    assert SECRET not in caplog.text
    assert SECRET not in json.dumps(state)


# --------------------------------------------------------------------------- migration


def _run_migration(eng, filename, fn_name):
    """Run ``upgrade``/``downgrade`` of one revision file against ``eng``."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    path = _ROOT / "migrations/versions" / filename
    spec = importlib.util.spec_from_file_location(f"mig_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with eng.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, fn_name)()


def test_migration_moves_single_server_row(tmp_path):
    """f3a4b5c034: the old single-server row becomes server ``fs01`` (DEFAULT set),
    per-server columns leave smb_settings, a re-run is a no-op, downgrade restores them."""
    from sqlalchemy import create_engine, inspect, text

    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    # Minimal FK targets: the real tables come from earlier revisions.
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE tenants (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO tenants (id) VALUES ('default')"))
    _run_migration(eng, "e2f3a4b033_smb_settings.py", "upgrade")
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO smb_settings (tenant_id, enabled, host, port, default_domain, "
                "shares_json, auth_protocol) VALUES ('default', 1, 'FS01.corp.local', 445, "
                "'CORP', '[{\"name\": \"Docs\"}]', 'ntlm')"
            )
        )

    _run_migration(eng, "f3a4b5c034_smb_servers.py", "upgrade")
    _run_migration(eng, "f3a4b5c034_smb_servers.py", "upgrade")  # idempotent
    cols = {c["name"] for c in inspect(eng).get_columns("smb_settings")}
    assert "host" not in cols and "shares_json" not in cols and "enabled" in cols
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT alias, host, credential_set, shares_json FROM smb_servers")
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("fs01", "fs01.corp.local", "DEFAULT", '[{"name": "Docs"}]')
    ]

    _run_migration(eng, "f3a4b5c034_smb_servers.py", "downgrade")
    with eng.connect() as conn:
        host = conn.execute(text("SELECT host FROM smb_settings")).scalar()
    assert host == "fs01.corp.local"
    assert "smb_servers" not in inspect(eng).get_table_names()


# --------------------------------------------------------------------------- probe


class _Status(Exception):
    """Stand-in for smbprotocol response errors: only ``status`` matters."""

    def __init__(self, status: int):
        super().__init__(f"status {status:#x}")
        self.status = status


class _FakeSmb:
    """Fake Connection/Session/TreeConnect recording calls and disconnects."""

    def __init__(self, logon_status=None, denied=()):
        self.logon_status = logon_status
        self.denied = set(denied)
        self.disconnected: List[str] = []
        self.sessions: List[dict] = []
        fake = self

        class Connection:
            def __init__(self, guid, server, port=445, require_signing=True):
                self.dialect = 0x0311

            def connect(self, timeout=60, **_kw):
                pass

            def disconnect(self, close=True, timeout=None):
                fake.disconnected.append("connection")

        class Session:
            def __init__(self, conn, username=None, password=None, **kw):
                fake.sessions.append({"username": username, **kw})

            def connect(self):
                if fake.logon_status:
                    raise _Status(fake.logon_status)

            def disconnect(self, close=True, timeout=None):
                fake.disconnected.append("session")

        class TreeConnect:
            def __init__(self, session, share_name):
                self.share = share_name.rsplit("\\", 1)[-1]

            def connect(self):
                if self.share in fake.denied:
                    raise _Status(0xC0000022)

            def disconnect(self):
                fake.disconnected.append(f"tree:{self.share}")

        self.Connection, self.Session, self.TreeConnect = (
            Connection,
            Session,
            TreeConnect,
        )

    def install(self, monkeypatch):
        import smbprotocol.connection
        import smbprotocol.session
        import smbprotocol.tree

        monkeypatch.setattr(smbprotocol.connection, "Connection", self.Connection)
        monkeypatch.setattr(smbprotocol.session, "Session", self.Session)
        monkeypatch.setattr(smbprotocol.tree, "TreeConnect", self.TreeConnect)
        return self


_CFG = SmbServer(
    alias="fs01",
    host="fs01",
    default_domain="CORP",
    shares=(SmbShare("Documenti"), SmbShare("Archivio", read_only=True)),
    auth_protocol="ntlm",
)


def test_probe_negotiate_only(monkeypatch):
    """Without credentials only the negotiate runs and no session is opened."""
    fake = _FakeSmb().install(monkeypatch)
    res = probe.test_connection(_CFG)
    assert res["ok"] and res["negotiated"] and res["dialect"] == "3.1.1"
    assert res["authenticated"] is None and fake.sessions == []
    assert fake.disconnected == ["connection"]


def test_probe_with_credentials_reports_per_share(monkeypatch):
    """Logon + tree connect per share; a denied share fails the test with its code."""
    fake = _FakeSmb(denied={"Archivio"}).install(monkeypatch)
    res = probe.test_connection(_CFG, "mario", SECRET)
    assert res["authenticated"] is True
    assert res["shares"] == [
        {"name": "Documenti", "ok": True, "error": None},
        {"name": "Archivio", "ok": False, "error": "access_denied"},
    ]
    assert (res["ok"], res["error"]) == (False, "access_denied")
    # Bare user gets the default domain; protocol/encryption come from settings.
    assert fake.sessions[0]["username"] == "CORP\\mario"
    assert fake.sessions[0]["auth_protocol"] == "ntlm"
    assert fake.sessions[0]["require_encryption"] is False
    assert {"tree:Documenti", "session", "connection"} <= set(fake.disconnected)


def test_probe_logon_failure(monkeypatch, caplog):
    """A rejected logon maps to auth_failed, stops there and logs no secret."""
    caplog.set_level(logging.DEBUG)
    _FakeSmb(logon_status=0xC000006D).install(monkeypatch)
    res = probe.test_connection(_CFG, "CORP\\mario", SECRET)
    assert (res["ok"], res["error"], res["authenticated"]) == (
        False,
        "auth_failed",
        False,
    )
    assert res["shares"] == []
    assert SECRET not in caplog.text and "mario" not in caplog.text


def test_probe_unreachable(monkeypatch):
    """A connection error is reported as unreachable without trying to log in."""
    fake = _FakeSmb().install(monkeypatch)

    def boom(self, timeout=60, **_kw):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(fake.Connection, "connect", boom)
    res = probe.test_connection(_CFG, "mario", SECRET)
    assert (res["ok"], res["error"], res["negotiated"]) == (False, "unreachable", False)
    assert fake.sessions == []
