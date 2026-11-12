"""Unit tests for the smb_files core (paths, credentials, auth guard, settings).

Covers the multi-server model: paths are ``server/Share/path`` (alias, or the
host in UNC form), each server belongs to a credential set and the auth guard
blocks per set.  No network: smbclient is never contacted; the auth guard uses
a tmp HOME.
"""

import asyncio
import json
import time

import pytest

from src.tools.smb_files import auth_guard, settings_store
from src.tools.smb_files.credentials import (
    EXTRA_ENV,
    CredentialsMissing,
    credential_keys,
    load_credentials,
    normalize_username,
)
from src.tools.smb_files.paths import PathError, resolve_path
from src.tools.smb_files.settings_store import SmbConfig, SmbServer, SmbShare

FS01 = SmbServer(
    alias="fs01",
    host="fs01.acme.local",
    default_domain="ACME",
    shares=(SmbShare("Documenti"), SmbShare("Archivio", read_only=True)),
)
# Second server in another domain, with a share named like one on fs01.
FS02 = SmbServer(
    alias="fs02",
    host="fs02.estero.local",
    default_domain="ESTERO",
    credential_set="ESTERO",
    shares=(SmbShare("Documenti", read_only=True),),
)
CFG = SmbConfig(servers=(FS01, FS02))


class TestPaths:
    """Scenario: the allowlist gate resolves the server, then the share, and rejects abuse."""

    def test_alias_and_unc_forms_are_equivalent(self):
        a = resolve_path("fs01/Documenti/sub/a.txt", CFG)
        b = resolve_path("\\\\FS01.acme.local\\documenti\\sub\\a.txt", CFG)
        assert a.unc == b.unc == "\\\\fs01.acme.local\\Documenti\\sub\\a.txt"
        assert a.display == "fs01/Documenti/sub/a.txt"

    def test_same_share_name_on_two_servers(self):
        a = resolve_path("fs01/Documenti/x", CFG)
        b = resolve_path("FS02/Documenti/x", CFG)
        assert a.server.alias == "fs01" and not a.read_only
        assert b.server.alias == "fs02" and b.read_only
        assert b.unc == "\\\\fs02.estero.local\\Documenti\\x"

    def test_unc_with_host_of_another_configured_server(self):
        t = resolve_path("\\\\fs02.estero.local\\Documenti", CFG)
        assert t.server is FS02 and t.rel == ""

    def test_read_only_flag_comes_from_share(self):
        assert resolve_path("fs01/Archivio/x", CFG).read_only
        assert not resolve_path("fs01/Documenti/x", CFG).read_only

    @pytest.mark.parametrize(
        "bad", ["fs01/Documenti/../Archivio/x", "fs01/Documenti/a/..", "", "fs01"]
    )
    def test_traversal_empty_and_missing_share_rejected(self, bad):
        with pytest.raises(PathError) as e:
            resolve_path(bad, CFG)
        assert e.value.code == "invalid_path"

    @pytest.mark.parametrize("share", ["C$", "ADMIN$", "IPC$", "Altra"])
    def test_admin_and_unknown_shares_rejected(self, share):
        with pytest.raises(PathError) as e:
            resolve_path(f"fs01/{share}/x", CFG)
        assert e.value.code == "share_not_allowed"

    def test_share_of_another_server_rejected(self):
        with pytest.raises(PathError) as e:
            resolve_path("fs02/Archivio/x", CFG)
        assert e.value.code == "share_not_allowed"

    @pytest.mark.parametrize(
        "bad", ["fs03/Documenti/x", "\\\\evil\\Documenti\\x", "\\\\fs01\\Documenti"]
    )
    def test_unknown_alias_or_foreign_host_rejected(self, bad):
        """A bare share name, an unknown alias or a host not configured never resolves."""
        with pytest.raises(PathError) as e:
            resolve_path(bad, CFG)
        assert e.value.code == "server_not_allowed"
        assert "fs01, fs02" in e.value.message

    def test_legacy_share_first_path_rejected(self):
        with pytest.raises(PathError) as e:
            resolve_path("Documenti/a.txt", CFG)
        assert e.value.code == "server_not_allowed"


class TestCredentials:
    """Scenario: DEFAULT set from the plain keys, other sets from the wildcard JSON."""

    def test_normalization_forms(self):
        assert normalize_username("DOM\\mario") == "DOM\\mario"
        assert normalize_username("mario@corp.example.com") == "CORP\\mario"
        assert normalize_username("mario", "ACME") == "ACME\\mario"
        assert normalize_username("mario") == "mario"

    def test_credential_keys(self):
        assert credential_keys("DEFAULT") == ("SMB_USERNAME", "SMB_PASSWORD")
        assert credential_keys("ESTERO") == (
            "SMB_USERNAME__ESTERO",
            "SMB_PASSWORD__ESTERO",
        )

    @pytest.mark.parametrize(
        "env",
        [
            {},
            {"SMB_USERNAME": "mario"},
            {"SMB_USERNAME": "probe_user", "SMB_PASSWORD": "probe_secret_key"},
        ],
    )
    def test_missing_or_mock_raises(self, env):
        with pytest.raises(CredentialsMissing):
            load_credentials(FS01, env)

    def test_default_set_uses_server_default_domain(self):
        c = load_credentials(FS01, {"SMB_USERNAME": "mario", "SMB_PASSWORD": "pw"})
        assert (c.username, c.password, c.credential_set) == (
            "ACME\\mario",
            "pw",
            "DEFAULT",
        )

    def test_extra_set_reads_wildcard_json(self):
        env = {
            "SMB_USERNAME": "mario",
            "SMB_PASSWORD": "pw",
            EXTRA_ENV: json.dumps(
                {"SMB_USERNAME__ESTERO": "m.rossi", "SMB_PASSWORD__ESTERO": "pw2"}
            ),
        }
        c = load_credentials(FS02, env)
        assert (c.username, c.password, c.credential_set) == (
            "ESTERO\\m.rossi",
            "pw2",
            "ESTERO",
        )

    @pytest.mark.parametrize(
        "extra",
        [
            None,
            "probe_test_val",  # probe mock: not JSON
            "[1, 2]",
            json.dumps({"SMB_USERNAME__ESTERO": "m.rossi"}),
            json.dumps({"SMB_USERNAME": "mario", "SMB_PASSWORD": "pw"}),
        ],
    )
    def test_extra_set_missing_names_server_and_set(self, extra):
        """The DEFAULT pair never stands in for another set."""
        env = {"SMB_USERNAME": "mario", "SMB_PASSWORD": "pw"}
        if extra is not None:
            env[EXTRA_ENV] = extra
        with pytest.raises(CredentialsMissing) as e:
            load_credentials(FS02, env)
        assert "fs02" in str(e.value) and "ESTERO" in str(e.value)


class TestAuthGuard:
    """Scenario: after one logon failure the same credentials of that set are not retried."""

    @pytest.fixture(autouse=True)
    def _home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))

    def _marker(self, tmp_path, cred_set="DEFAULT"):
        return tmp_path / f"{auth_guard.MARKER_PREFIX}.{cred_set.lower()}.json"

    def test_block_then_unblock_with_new_password(self):
        assert auth_guard.check("A\\u", "old", 30, "DEFAULT") is None
        auth_guard.record_failure("auth_failed", "A\\u", "old", "DEFAULT")
        assert auth_guard.check("A\\u", "old", 30, "DEFAULT")[0] == "auth_failed"
        assert auth_guard.check("A\\u", "new", 30, "DEFAULT") is None

    def test_block_on_one_set_does_not_block_another(self):
        auth_guard.record_failure("auth_failed", "A\\u", "pw", "ESTERO")
        assert auth_guard.check("A\\u", "pw", 30, "ESTERO")[0] == "auth_failed"
        assert auth_guard.check("A\\u", "pw", 30, "DEFAULT") is None

    def test_marker_never_contains_password(self, tmp_path):
        auth_guard.record_failure("auth_failed", "A\\u", "s3cret-pw", "DEFAULT")
        p = self._marker(tmp_path)
        assert "s3cret-pw" not in p.read_text()
        assert oct(p.stat().st_mode & 0o777) == "0o600"

    def test_account_lockout_expires(self, tmp_path):
        auth_guard.record_failure("account_locked", "A\\u", "pw", "DEFAULT")
        assert auth_guard.check("A\\u", "pw", 30, "DEFAULT")[0] == "account_locked"
        p = self._marker(tmp_path)
        d = json.loads(p.read_text())
        d["at"] = time.time() - 31 * 60
        p.write_text(json.dumps(d))
        assert auth_guard.check("A\\u", "pw", 30, "DEFAULT") is None

    def test_clear_only_touches_its_set(self):
        auth_guard.record_failure("auth_failed", "A\\u", "pw", "DEFAULT")
        auth_guard.record_failure("auth_failed", "A\\u", "pw", "ESTERO")
        auth_guard.clear("DEFAULT")
        assert auth_guard.check("A\\u", "pw", 30, "DEFAULT") is None
        assert auth_guard.check("A\\u", "pw", 30, "ESTERO") is not None


class TestSettingsStore:
    """Scenario: config is built from settings + server rows, cached, and invalidated."""

    class Settings:
        enabled = True
        max_read_mb = 5
        max_write_mb = None
        lockout_minutes = 15

    class Row:
        def __init__(self, alias, host, enabled=True, shares='[{"name": "Docs", "read_only": true}]', cred="DEFAULT"):
            self.alias, self.host, self.enabled = alias, host, enabled
            self.shares_json, self.credential_set = shares, cred
            self.port, self.default_domain, self.label = 445, "ACME", ""
            self.auth_protocol, self.require_encryption = "bogus", False

    def _patch(self, monkeypatch, settings, rows):
        calls = []

        async def fake_load(tid):
            calls.append(tid)
            return settings, rows

        monkeypatch.setattr(settings_store, "_load_rows", fake_load)
        settings_store._CACHE.clear()
        return calls

    def test_cache_and_invalidate(self, monkeypatch):
        calls = self._patch(
            monkeypatch,
            self.Settings(),
            [self.Row("FS01", "FS01.acme.local"), self.Row("fs02", "fs02", cred="estero")],
        )
        cfg = asyncio.run(settings_store.get_smb_config("t1"))
        asyncio.run(settings_store.get_smb_config("t1"))
        assert len(calls) == 1
        assert [s.alias for s in cfg.servers] == ["fs01", "fs02"]
        fs01 = cfg.server("FS01")
        assert fs01.host == "fs01.acme.local" and fs01.shares[0].read_only
        assert fs01.auth_protocol == "ntlm"  # unknown protocol falls back
        assert cfg.server_by_host("FS02").credential_set == "ESTERO"
        assert cfg.credential_sets() == {"DEFAULT": ("fs01",), "ESTERO": ("fs02",)}
        assert (cfg.max_read_mb, cfg.max_write_mb, cfg.lockout_minutes) == (5, 25, 15)
        settings_store.invalidate_cache("t1")
        asyncio.run(settings_store.get_smb_config("t1"))
        assert len(calls) == 2

    def test_disabled_or_incomplete_servers_are_skipped(self, monkeypatch):
        self._patch(
            monkeypatch,
            self.Settings(),
            [
                self.Row("off", "off", enabled=False),
                self.Row("noshares", "noshares", shares="[]"),
                self.Row("ok", "ok"),
            ],
        )
        cfg = asyncio.run(settings_store.get_smb_config("t1"))
        assert [s.alias for s in cfg.servers] == ["ok"]

    def test_missing_disabled_or_empty_gives_none(self, monkeypatch):
        disabled = self.Settings()
        disabled.enabled = False
        for settings, rows in (
            (None, [self.Row("a", "a")]),
            (disabled, [self.Row("a", "a")]),
            (self.Settings(), []),
            (self.Settings(), [self.Row("a", "a", enabled=False)]),
        ):
            self._patch(monkeypatch, settings, rows)
            assert asyncio.run(settings_store.get_smb_config("t2")) is None
