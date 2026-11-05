"""Per-user credential sets of the ``smb_files`` connector (multi-server, phase 4b).

Servers in other AD domains use ``SMB_USERNAME__<SET>`` / ``SMB_PASSWORD__<SET>``,
keys that depend on the admin configuration and so appear in no static schema.
Covers the plumbing that makes them work end to end:

* the ``${AION_USER_<SLUG>__*}`` wildcard placeholder (``credential_store``):
  JSON of all the user's keys, mock value for probes, never gating a spawn;
* credential discovery never turning the wildcard carrier into a form field;
* ``dynamic_credential_fields``: extra pairs in the "My integrations" form,
  write-only passwords, allowed key format;
* ``/v1/integrations/credentials``: unknown keys rejected (400), extra
  passwords not readable back (403).
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi import HTTPException

from src.runtime import dynamic_credential_fields as dyn
from src.tools.smb_files.settings_store import SmbConfig, SmbServer, SmbShare

SECRET = "Est3ro-S3cret!"
WILDCARD = "${AION_USER_SMB_FILES__*}"
REGISTRY_ENV = {
    "SMB_USERNAME": "${AION_USER_SMB_FILES__SMB_USERNAME}",
    "SMB_PASSWORD": "${AION_USER_SMB_FILES__SMB_PASSWORD}",
    "SMB_EXTRA_CREDENTIALS": WILDCARD,
}
_SCHEMA = [
    {"key": "SMB_USERNAME", "label": "Utente Windows", "type": "text", "required": True},
    {
        "key": "SMB_PASSWORD",
        "label": "Password Windows",
        "type": "password",
        "write_only": True,
        "required": True,
    },
]
CFG = SmbConfig(
    servers=(
        SmbServer(alias="fs01", host="fs01", shares=(SmbShare("Docs"),)),
        SmbServer(
            alias="fs02", host="fs02", credential_set="ESTERO", shares=(SmbShare("Docs"),)
        ),
        SmbServer(
            alias="fs03", host="fs03", credential_set="ESTERO", shares=(SmbShare("Docs"),)
        ),
    )
)


async def _setup(monkeypatch, tmp_path):
    """Throwaway unified DB with an enabled, per-user smb_files integration row."""
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_MCP_USER_CREDENTIALS", "1")
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    monkeypatch.delenv("AION_ENV", raising=False)
    monkeypatch.delenv("AION_DEFAULT_TENANT_ID", raising=False)

    from src.data import engine as engine_mod
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import get_async_session_maker, init_engine
    from src.data.models import McpServerConfig

    monkeypatch.setattr(engine_mod, "_engine", None)
    monkeypatch.setattr(engine_mod, "_session_factory", None)
    eng = init_engine()
    await ensure_bootstrap_schema(eng)
    async with get_async_session_maker()() as session:
        session.add(
            McpServerConfig(
                id="id-smb",
                server_slug="smb_files",
                display_name="File server",
                is_enabled_for_users=True,
                requires_user_credentials=True,
                credential_mode="per_user",
                credential_schema_json=json.dumps(_SCHEMA),
            )
        )
        await session.commit()


def _use_config(monkeypatch, cfg):
    """Serve a fixed admin configuration to the dynamic-field provider."""

    async def _fake(_tenant):
        return cfg

    monkeypatch.setattr("src.tools.smb_files.settings_store.get_smb_config", _fake)


def _auth():
    from src.api.auth_login import ChatAuthIdentity

    return ChatAuthIdentity(
        user_row_id="u1", identifier="mario", via="chat_token", roles=[]
    )


async def _save(creds):
    from src.api.v1.mcp_integrations import CredentialSetBody, save_credentials

    return await save_credentials(
        CredentialSetBody(server_slug="smb_files", credentials=creds), auth=_auth()
    )


# --------------------------------------------------------------------------- wildcard


@pytest.mark.anyio
async def test_wildcard_resolves_to_json_of_all_user_keys(monkeypatch, tmp_path):
    """The wildcard carries every key of the user for the slug; single keys still work."""
    await _setup(monkeypatch, tmp_path)
    from src.runtime.credential_store import resolve_mcp_env_for_user, set_credential

    env = await resolve_mcp_env_for_user(
        REGISTRY_ENV, user_id="u1", tenant_id="default", server_slug="smb_files"
    )
    # Nothing saved yet: empty, like an unset single key.
    assert env["SMB_EXTRA_CREDENTIALS"] == ""

    for key, val in (
        ("SMB_USERNAME", "mario"),
        ("SMB_PASSWORD", "pw"),
        ("SMB_USERNAME__ESTERO", "m.rossi"),
        ("SMB_PASSWORD__ESTERO", SECRET),
    ):
        await set_credential("u1", "smb_files", key, val)
    # Another user's credentials never end up in u1's bundle.
    await set_credential("u2", "smb_files", "SMB_PASSWORD__ESTERO", "other")

    env = await resolve_mcp_env_for_user(
        REGISTRY_ENV, user_id="u1", tenant_id="default", server_slug="smb_files"
    )
    assert env["SMB_USERNAME"] == "mario"
    assert json.loads(env["SMB_EXTRA_CREDENTIALS"]) == {
        "SMB_USERNAME": "mario",
        "SMB_PASSWORD": "pw",
        "SMB_USERNAME__ESTERO": "m.rossi",
        "SMB_PASSWORD__ESTERO": SECRET,
    }


@pytest.mark.anyio
async def test_probe_gets_a_non_json_mock(monkeypatch, tmp_path):
    """An admin probe never receives the credential bundle: the mock is not JSON."""
    await _setup(monkeypatch, tmp_path)
    from src.runtime.credential_store import resolve_mcp_env_for_user, set_credential

    await set_credential("admin-probe", "smb_files", "SMB_PASSWORD__ESTERO", SECRET)
    env = await resolve_mcp_env_for_user(
        REGISTRY_ENV, user_id="admin-probe", tenant_id="default", server_slug="smb_files"
    )
    extra = env["SMB_EXTRA_CREDENTIALS"]
    assert extra and SECRET not in extra
    with pytest.raises(ValueError):
        json.loads(extra)


@pytest.mark.anyio
async def test_empty_wildcard_does_not_block_spawn(monkeypatch, tmp_path):
    """Only the DEFAULT pair gates the MCP worker; an empty wildcard never does."""
    await _setup(monkeypatch, tmp_path)
    from src.mcp_manager import MCPManager
    from src.runtime.credential_store import set_credential

    mgr = object.__new__(MCPManager)
    mgr._session_ctx = {"s1": ("p", "u1", "default")}
    mgr.get_server_config = lambda _name: {"env": dict(REGISTRY_ENV)}

    missing = await mgr._warm_credentials_missing("s1", "smb_files")
    assert missing and "SMB_USERNAME" in missing

    await set_credential("u1", "smb_files", "SMB_USERNAME", "mario")
    await set_credential("u1", "smb_files", "SMB_PASSWORD", "pw")
    assert await mgr._warm_credentials_missing("s1", "smb_files") is None


def test_discovery_ignores_wildcard_carrier(tmp_path, monkeypatch):
    """The env var carrying the wildcard is plumbing, never a credential form field."""
    from src.mcp_credential_discovery import discover_mcp_credentials

    monkeypatch.setattr("src.mcp_server_files._repo_root", lambda: tmp_path)
    result = discover_mcp_credentials("smb_files", {"env": dict(REGISTRY_ENV)})
    keys = {s["key"] for s in result.schema}
    # Discovery keeps only credential-looking keys; the password is one of them.
    assert "SMB_PASSWORD" in keys
    assert "SMB_EXTRA_CREDENTIALS" not in keys
    assert not any("*" in k for k in keys)


# --------------------------------------------------------------------------- dynamic fields


def test_key_format_and_write_only_rules():
    """smb_files accepts only DEFAULT/per-set pairs; every SMB password is write-only."""
    for key in ("SMB_USERNAME", "SMB_PASSWORD", "SMB_USERNAME__ESTERO", "SMB_PASSWORD__X1"):
        assert dyn.credential_key_allowed("smb_files", key)
        assert dyn.credential_key_allowed("smb-files", key)
    for key in (
        "SMB_PASSWORD__DEFAULT",  # DEFAULT lives in the plain keys
        "SMB_PASSWORD__estero",
        "SMB_TOKEN",
        "OTHER",
        "SMB_PASSWORD__" + "A" * 25,
    ):
        assert not dyn.credential_key_allowed("smb_files", key)
    # Other connectors are not restricted.
    assert dyn.credential_key_allowed("mssql", "ANYTHING")

    assert dyn.dynamic_key_is_write_only("smb_files", "SMB_PASSWORD__ESTERO")
    assert dyn.dynamic_key_is_write_only("smb_files", "SMB_PASSWORD")
    assert not dyn.dynamic_key_is_write_only("smb_files", "SMB_USERNAME__ESTERO")
    assert not dyn.dynamic_key_is_write_only("mssql", "SMB_PASSWORD__ESTERO")


@pytest.mark.anyio
async def test_form_gets_one_optional_pair_per_extra_set(monkeypatch):
    """One pair per non-DEFAULT set (not per server), labelled with its servers."""
    _use_config(monkeypatch, CFG)
    out = await dyn.apply_dynamic_credential_fields(_SCHEMA, "smb_files", "default")
    by_key = {f["key"]: f for f in out}
    assert list(by_key) == [
        "SMB_USERNAME",
        "SMB_PASSWORD",
        "SMB_USERNAME__ESTERO",
        "SMB_PASSWORD__ESTERO",
    ]
    assert by_key["SMB_USERNAME"]["description"] == "Server: fs01"
    extra_pwd = by_key["SMB_PASSWORD__ESTERO"]
    assert extra_pwd["write_only"] is True and extra_pwd["required"] is False
    assert extra_pwd["description"] == "Server: fs02, fs03"
    assert by_key["SMB_USERNAME__ESTERO"]["category"] == "basic"
    # The static schema is not mutated.
    assert "description" not in _SCHEMA[0]


@pytest.mark.anyio
async def test_form_unchanged_without_config_or_on_error(monkeypatch):
    """No admin config, a provider error or another connector: static schema as is."""
    _use_config(monkeypatch, None)
    assert await dyn.apply_dynamic_credential_fields(_SCHEMA, "smb_files", "t") == _SCHEMA

    async def _boom(_tenant):
        raise RuntimeError("db down")

    monkeypatch.setattr("src.tools.smb_files.settings_store.get_smb_config", _boom)
    assert await dyn.apply_dynamic_credential_fields(_SCHEMA, "smb_files", "t") == _SCHEMA
    assert await dyn.apply_dynamic_credential_fields(_SCHEMA, "mssql", "t") is _SCHEMA


# --------------------------------------------------------------------------- integrations API


@pytest.mark.anyio
async def test_save_rejects_keys_outside_the_smb_format(monkeypatch, tmp_path):
    """The wildcard JSON cannot be stuffed with arbitrary keys; nothing is saved on 400."""
    await _setup(monkeypatch, tmp_path)
    from src.runtime.credential_store import get_all_credentials_for_server

    with pytest.raises(HTTPException) as exc:
        await _save({"SMB_USERNAME": "mario", "EVIL_KEY": "x"})
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "credential_key_not_allowed"
    assert await get_all_credentials_for_server("u1", "smb_files") == {}


@pytest.mark.anyio
async def test_extra_set_password_is_write_only(monkeypatch, tmp_path):
    """An extra-set password is saved but never readable back; its username is."""
    await _setup(monkeypatch, tmp_path)
    from src.api.v1.mcp_integrations import get_user_credential_value

    await _save({"SMB_USERNAME__ESTERO": "m.rossi", "SMB_PASSWORD__ESTERO": SECRET})
    with pytest.raises(HTTPException) as exc:
        await get_user_credential_value("smb_files", "SMB_PASSWORD__ESTERO", auth=_auth())
    assert exc.value.status_code == 403
    assert exc.value.detail == "secret_write_only"

    res = await get_user_credential_value("smb_files", "SMB_USERNAME__ESTERO", auth=_auth())
    assert SECRET not in json.dumps(res)
    assert "m.rossi" in json.dumps(res)
