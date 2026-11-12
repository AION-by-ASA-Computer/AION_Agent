"""Tests for the ``smb_files`` MCP server (phase 2) and its registration.

The FastMCP server is loaded straight from ``mcp_servers_std/`` and driven with
an in-memory ``fastmcp.Client``: no stdio process, no DB, no SMB network.
"""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from fastmcp import Client

from src.mcp_manager import (
    _DEFAULT_SESSION_SCOPED_SERVERS,
    _server_needs_user_credentials,
)
from src.runtime.credential_store import generate_probe_mock_value
from src.tools.smb_files import client as smb_client
from src.tools.smb_files import credentials, ops
from src.tools.smb_files.settings_store import SmbConfig, SmbServer, SmbShare

_REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "smb_files_server_under_test",
    _REPO / "mcp_servers_std" / "smb_files" / "server.py",
)
assert _spec and _spec.loader
smb_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smb_server)

EXPECTED_TOOLS = {
    "smb_list_shares",
    "smb_list_dir",
    "smb_stat",
    "smb_search",
    "smb_read_file",
    "smb_copy_to_session",
    "smb_write_text",
    "smb_upload_from_session",
    "smb_mkdir",
    "smb_move",
}

CFG = SmbConfig(
    servers=(
        SmbServer(
            alias="fs01",
            host="fs01",
            shares=(
                SmbShare("Documenti", label="Docs"),
                SmbShare("Archivio", read_only=True),
            ),
        ),
        SmbServer(
            alias="fs02",
            host="fs02",
            credential_set="ESTERO",
            shares=(SmbShare("Documenti"),),
        ),
    ),
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if any test path tries to open an SMB session."""

    def _boom(*_a, **_k):
        raise AssertionError("SMB network access attempted")

    monkeypatch.setattr(smb_client, "open_session", _boom)
    monkeypatch.setattr(ops, "_smb", _boom)


def _use_config(monkeypatch, cfg):
    """Replace the tenant settings lookup used by the server with a fixed value."""

    async def _fake(_tenant):
        return cfg

    monkeypatch.setattr(smb_server, "get_smb_config", _fake)


def _call(name, args=None):
    """Call one tool through the in-memory client and decode its JSON payload."""

    async def _go():
        async with Client(smb_server.mcp) as c:
            res = await c.call_tool(name, args or {})
            return json.loads(res.content[0].text)

    return asyncio.run(_go())


def test_list_tools_exposes_read_write_tools_and_no_delete():
    """Tool listing works without credentials/network and offers no delete tool."""

    async def _go():
        async with Client(smb_server.mcp) as c:
            return {t.name for t in await c.list_tools()}

    names = asyncio.run(_go())
    assert names == EXPECTED_TOOLS
    assert not any("delete" in n or "remove" in n for n in names)


def test_tool_reports_not_configured_without_admin_settings(monkeypatch):
    """Missing/disabled admin config yields a clean not_configured tool error."""
    _use_config(monkeypatch, None)
    out = _call("smb_list_dir", {"path": "fs01/Documenti"})
    assert out == {
        "ok": False,
        "error": "not_configured",
        "message": out["message"],
    }


def test_settings_load_failure_is_reported_as_not_configured(monkeypatch):
    """A DB error while loading settings does not crash the tool."""

    async def _fail(_tenant):
        raise RuntimeError("db down")

    monkeypatch.setattr(smb_server, "get_smb_config", _fail)
    assert _call("smb_list_shares")["error"] == "not_configured"


def test_probe_mock_credentials_never_reach_the_server(monkeypatch):
    """Admin-probe mock values give credentials_missing without any SMB call."""
    _use_config(monkeypatch, CFG)
    monkeypatch.setenv("SMB_USERNAME", generate_probe_mock_value("SMB_USERNAME"))
    monkeypatch.setenv("SMB_PASSWORD", generate_probe_mock_value("SMB_PASSWORD"))
    out = _call("smb_list_dir", {"path": "fs01/Documenti"})
    assert out["ok"] is False
    assert out["error"] == "credentials_missing"


def test_probe_mock_wildcard_never_reaches_extra_set_servers(monkeypatch):
    """The probe mock of SMB_EXTRA_CREDENTIALS is not JSON: servers of another
    credential set report credentials_missing without any SMB call."""
    _use_config(monkeypatch, CFG)
    monkeypatch.setenv("SMB_USERNAME", "ACME\\mario")
    monkeypatch.setenv("SMB_PASSWORD", "pw")
    monkeypatch.setenv(
        credentials.EXTRA_ENV, generate_probe_mock_value(credentials.EXTRA_ENV)
    )
    out = _call("smb_list_dir", {"path": "fs02/Documenti"})
    assert out["error"] == "credentials_missing"


def test_list_shares_returns_admin_allowlist(monkeypatch):
    """smb_list_shares answers from the admin config: every server with the
    path prefix to use and the read-only flags."""
    _use_config(monkeypatch, CFG)
    out = _call("smb_list_shares")
    assert out["ok"] is True
    assert [s["server"] for s in out["servers"]] == ["fs01", "fs02"]
    assert out["servers"][0]["shares"] == [
        {"name": "Documenti", "path": "fs01/Documenti", "label": "Docs", "read_only": False},
        {"name": "Archivio", "path": "fs01/Archivio", "label": "", "read_only": True},
    ]
    assert out["servers"][1]["shares"][0]["path"] == "fs02/Documenti"


def test_probe_mock_values_are_recognised_as_fake():
    """Guard against AD lockout: the probe mock generator and the credential
    loader must agree on what a fake value is, or probes would try a logon."""
    for var in ("SMB_USERNAME", "SMB_PASSWORD"):
        assert generate_probe_mock_value(var) in credentials._MOCK_VALUES


def test_registry_entry_is_per_user_and_session_scoped():
    """Registry placeholders make the server per-user; workspace tools need a
    per-chat-session worker."""
    registry = yaml.safe_load(
        (_REPO / "config_std" / "mcp_registry.yaml").read_text(encoding="utf-8")
    )
    entry = registry["smb_files"]
    assert entry["args"] == ["-u", "smb_files/server.py"]
    assert entry["aion_connector_id"] == "smb_files"
    assert set(entry["env"]) == {"SMB_USERNAME", "SMB_PASSWORD", "SMB_EXTRA_CREDENTIALS"}
    # Extra credential sets travel as one JSON blob through the wildcard placeholder.
    assert entry["env"]["SMB_EXTRA_CREDENTIALS"] == "${AION_USER_SMB_FILES__*}"
    assert _server_needs_user_credentials(entry)
    assert "smb_files" in _DEFAULT_SESSION_SCOPED_SERVERS


def test_catalog_entry_declares_per_user_credentials():
    """The connector catalog asks each user for username + write-only password."""
    catalog = yaml.safe_load(
        (_REPO / "config_std" / "mcp_connector_catalog.yaml").read_text(
            encoding="utf-8"
        )
    )
    row = next(c for c in catalog["connectors"] if c["id"] == "smb_files")
    assert row["default_credential_mode"] == "per_user"
    fields = {f["key"]: f for f in row["credential_fields"]}
    assert set(fields) == {"SMB_USERNAME", "SMB_PASSWORD"}
    assert fields["SMB_PASSWORD"]["secret"] is True
    assert fields["SMB_PASSWORD"]["write_only"] is True
    assert "_" not in fields["SMB_USERNAME"]["label"]
