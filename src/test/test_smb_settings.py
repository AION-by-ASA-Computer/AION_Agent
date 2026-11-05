"""Admin configuration of the SMB file server (phase 3 of the ``smb_files`` connector).

Covers ``/admin/smb`` (GET/PUT/test), the write side of
``src/tools/smb_files/settings_store.py`` (persistence, cache, Hub sync) and the
connection probe ``src/tools/smb_files/probe.py`` with smbprotocol faked, so no
network is needed.  Pattern of ``test_smtp_settings.py``.
"""

from __future__ import annotations

import json
import logging
from typing import List

import pytest
from fastapi import HTTPException

from src.tools.smb_files import probe, settings_store
from src.tools.smb_files.settings_store import SmbConfig, SmbShare

SECRET = "Win-S3cret!"


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


def _body(**kw):
    from src.api.admin_smb import SmbSettingsBody

    base = {
        "enabled": True,
        "host": "fs01.corp.local",
        "port": 445,
        "default_domain": "CORP",
        "shares": [
            {"name": "Documenti", "read_only": False, "label": "Documenti"},
            {"name": "Archivio", "read_only": True},
        ],
    }
    base.update(kw)
    return SmbSettingsBody(**base)


async def _audit_ops(sm) -> List[tuple]:
    from sqlalchemy import select

    from src.data.models import AuditLog

    async with sm() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    return [(r.operation, r.payload) for r in rows]


@pytest.mark.anyio
async def test_get_defaults_without_row(monkeypatch, tmp_path):
    """No row yet: admin-ui gets a disabled, unconfigured default view."""
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import get_smb

    res = await get_smb(auth=_auth())
    assert res["configured"] is False and res["enabled"] is False
    assert (res["port"], res["shares"], res["auth_protocol"]) == (445, [], "ntlm")


@pytest.mark.anyio
async def test_put_persists_and_feeds_mcp_config(monkeypatch, tmp_path):
    """A valid PUT is visible to the MCP read path (cache invalidated) and audited."""
    sm = await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import put_smb

    # Prime the cache with "not configured" to prove the save invalidates it.
    assert await settings_store.get_smb_config("default") is None

    res = await put_smb(
        _body(max_read_mb=10, lockout_minutes=45, auth_protocol="Negotiate"),
        auth=_auth(),
    )
    assert res["configured"] and res["enabled"]
    assert res["shares"][1] == {"name": "Archivio", "read_only": True, "label": ""}

    cfg = await settings_store.get_smb_config("default")
    assert cfg is not None
    assert (cfg.host, cfg.default_domain, cfg.auth_protocol) == (
        "fs01.corp.local",
        "CORP",
        "negotiate",
    )
    assert (cfg.max_read_mb, cfg.lockout_minutes) == (10, 45)
    assert cfg.share("archivio").read_only is True

    ops = await _audit_ops(sm)
    assert ops and ops[-1][0] == "smb.update"


@pytest.mark.anyio
async def test_disabled_row_is_draft(monkeypatch, tmp_path):
    """Disabled settings may be incomplete and never reach the MCP connector."""
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import put_smb

    res = await put_smb(_body(enabled=False, shares=[]), auth=_auth())
    assert res["enabled"] is False and res["configured"] is False
    assert await settings_store.get_smb_config("default") is None


@pytest.mark.anyio
async def test_put_validation(monkeypatch, tmp_path):
    """Admin shares, sub-paths, duplicates and bad hosts are rejected with a code."""
    await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import put_smb

    for kw, code in (
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
        with pytest.raises(HTTPException) as e:
            await put_smb(_body(**kw), auth=_auth())
        assert e.value.detail == {"code": code}, kw


@pytest.mark.anyio
async def test_put_syncs_hub_entry(monkeypatch, tmp_path):
    """The enabled switch is mirrored on McpServerConfig(smb_files), if present."""
    sm = await _setup(monkeypatch, tmp_path)
    from src.api.admin_smb import put_smb
    from src.data.models import McpServerConfig

    # Without a Hub row the save still succeeds and reports it.
    res = await put_smb(_body(), auth=_auth())
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

    res = await put_smb(_body(), auth=_auth())
    assert res["connector_synced"] is True
    async with sm() as session:
        assert (await session.get(McpServerConfig, "m1")).is_enabled_for_users is True

    await put_smb(_body(enabled=False), auth=_auth())
    async with sm() as session:
        assert (await session.get(McpServerConfig, "m1")).is_enabled_for_users is False


@pytest.mark.anyio
async def test_connection_test_endpoint(monkeypatch, tmp_path, caplog):
    """/test uses the saved config, records the outcome and never leaks the password."""
    sm = await _setup(monkeypatch, tmp_path)
    from src.api import admin_smb
    from src.api.admin_smb import SmbTestBody, get_smb, put_smb, test_smb

    with pytest.raises(HTTPException) as e:
        await test_smb(SmbTestBody(), auth=_auth())
    assert e.value.detail == {"code": "smb_not_configured"}

    # Works on a disabled (but complete) row: the admin tests before enabling.
    await put_smb(_body(enabled=False), auth=_auth())

    calls = []

    def fake_test(cfg, username=None, password=None):
        calls.append((cfg.host, username, password))
        if password == SECRET:
            return {"ok": False, "error": "auth_failed", "shares": []}
        return {"ok": True, "error": None, "negotiated": True, "shares": []}

    monkeypatch.setattr(admin_smb.probe, "test_connection", fake_test)

    with pytest.raises(HTTPException) as e:
        await test_smb(SmbTestBody(username="mario"), auth=_auth())
    assert e.value.detail == {"code": "credentials_incomplete"}

    res = await test_smb(SmbTestBody(), auth=_auth())
    assert res["ok"] is True and calls[-1] == ("fs01.corp.local", None, None)
    assert (await get_smb(auth=_auth()))["last_test_ok"] is True

    caplog.set_level(logging.DEBUG)
    res = await test_smb(
        SmbTestBody(username="CORP\\mario", password=SECRET), auth=_auth()
    )
    assert res == {"ok": False, "error": "auth_failed", "shares": []}
    state = await get_smb(auth=_auth())
    assert (state["last_test_ok"], state["last_test_error"]) == (False, "auth_failed")

    ops = await _audit_ops(sm)
    tests = [p for op, p in ops if op == "smb.test"]
    assert len(tests) == 2
    assert all(SECRET not in (p or "") for _, p in ops)
    assert json.loads(tests[-1])["with_credentials"] is True
    assert SECRET not in caplog.text
    assert SECRET not in json.dumps(state)


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


_CFG = SmbConfig(
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
