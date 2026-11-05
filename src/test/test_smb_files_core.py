"""Unit tests for the smb_files core (paths, credentials, auth guard, settings).

No network: smbclient is never contacted; the auth guard uses a tmp HOME.
"""

import asyncio
import os
import time

import pytest

from src.tools.smb_files import auth_guard, settings_store
from src.tools.smb_files.credentials import (
    CredentialsMissing,
    load_credentials,
    normalize_username,
)
from src.tools.smb_files.paths import PathError, resolve_path
from src.tools.smb_files.settings_store import SmbConfig, SmbShare

CFG = SmbConfig(
    host="fs01",
    default_domain="ACME",
    shares=(SmbShare("Documenti"), SmbShare("Archivio", read_only=True)),
)


class TestPaths:
    """Scenario: the allowlist gate accepts valid paths and rejects abuse."""

    def test_relative_and_unc_forms_are_equivalent(self):
        a = resolve_path("Documenti/sub/a.txt", CFG)
        b = resolve_path("\\\\FS01\\documenti\\sub\\a.txt", CFG)
        assert a.unc == b.unc == "\\\\fs01\\Documenti\\sub\\a.txt"

    def test_read_only_flag_comes_from_share(self):
        assert resolve_path("Archivio/x", CFG).read_only
        assert not resolve_path("Documenti/x", CFG).read_only

    @pytest.mark.parametrize("bad", ["Documenti/../Archivio/x", "Documenti/a/..", ""])
    def test_traversal_and_empty_rejected(self, bad):
        with pytest.raises(PathError) as e:
            resolve_path(bad, CFG)
        assert e.value.code == "invalid_path"

    @pytest.mark.parametrize("share", ["C$", "ADMIN$", "IPC$", "Altra"])
    def test_admin_and_unknown_shares_rejected(self, share):
        with pytest.raises(PathError) as e:
            resolve_path(f"{share}/x", CFG)
        assert e.value.code == "share_not_allowed"

    def test_foreign_host_rejected(self):
        with pytest.raises(PathError) as e:
            resolve_path("\\\\evil\\Documenti\\x", CFG)
        assert e.value.code == "host_not_allowed"


class TestCredentials:
    """Scenario: usernames are normalised; empty/mock creds never reach the net."""

    def test_normalization_forms(self):
        assert normalize_username("DOM\\mario") == "DOM\\mario"
        assert normalize_username("mario@corp.example.com") == "CORP\\mario"
        assert normalize_username("mario", "ACME") == "ACME\\mario"
        assert normalize_username("mario") == "mario"

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
            load_credentials(CFG, env)

    def test_valid_credentials_use_default_domain(self):
        c = load_credentials(CFG, {"SMB_USERNAME": "mario", "SMB_PASSWORD": "pw"})
        assert (c.username, c.password) == ("ACME\\mario", "pw")


class TestAuthGuard:
    """Scenario: after one logon failure the same credentials are not retried."""

    @pytest.fixture(autouse=True)
    def _home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))

    def test_block_then_unblock_with_new_password(self):
        assert auth_guard.check("A\\u", "old", 30) is None
        auth_guard.record_failure("auth_failed", "A\\u", "old")
        assert auth_guard.check("A\\u", "old", 30)[0] == "auth_failed"
        assert auth_guard.check("A\\u", "new", 30) is None

    def test_marker_never_contains_password(self, tmp_path):
        auth_guard.record_failure("auth_failed", "A\\u", "s3cret-pw")
        raw = (tmp_path / auth_guard.MARKER_NAME).read_text()
        assert "s3cret-pw" not in raw
        assert (
            oct((tmp_path / auth_guard.MARKER_NAME).stat().st_mode & 0o777) == "0o600"
        )

    def test_account_lockout_expires(self, tmp_path):
        auth_guard.record_failure("account_locked", "A\\u", "pw")
        assert auth_guard.check("A\\u", "pw", 30)[0] == "account_locked"
        p = tmp_path / auth_guard.MARKER_NAME
        import json

        d = json.loads(p.read_text())
        d["at"] = time.time() - 31 * 60
        p.write_text(json.dumps(d))
        assert auth_guard.check("A\\u", "pw", 30) is None

    def test_clear(self):
        auth_guard.record_failure("auth_failed", "A\\u", "pw")
        auth_guard.clear()
        assert auth_guard.check("A\\u", "pw", 30) is None


class TestSettingsStore:
    """Scenario: config is built from a row, cached, and invalidated on demand."""

    class Row:
        enabled = True
        host = "fs01"
        port = 445
        default_domain = "ACME"
        shares_json = '[{"name": "Docs", "read_only": true}]'
        auth_protocol = "bogus"
        require_encryption = False
        max_read_mb = 5
        max_write_mb = None

    def test_cache_and_invalidate(self, monkeypatch):
        calls = []

        async def fake_load(tid):
            calls.append(tid)
            return self.Row()

        monkeypatch.setattr(settings_store, "_load_row", fake_load)
        settings_store._CACHE.clear()
        cfg = asyncio.run(settings_store.get_smb_config("t1"))
        asyncio.run(settings_store.get_smb_config("t1"))
        assert len(calls) == 1
        assert cfg.shares[0].read_only and cfg.auth_protocol == "ntlm"
        assert cfg.max_read_mb == 5 and cfg.max_write_mb == 25
        settings_store.invalidate_cache("t1")
        asyncio.run(settings_store.get_smb_config("t1"))
        assert len(calls) == 2

    def test_missing_or_disabled_row_gives_none(self, monkeypatch):
        async def none_row(tid):
            return None

        monkeypatch.setattr(settings_store, "_load_row", none_row)
        settings_store._CACHE.clear()
        assert asyncio.run(settings_store.get_smb_config("t2")) is None
