"""Write-only credential fields (phase 4 of the smb_files connector).

The Windows domain password of ``smb_files`` must never be readable back through
``GET /v1/integrations/credentials/{slug}/{key}`` nor leak through the stored
``display_hint``; other connectors keep their previous behaviour.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi import HTTPException

PASSWORD = "Dom@in-S3cret!"


async def _setup(monkeypatch, tmp_path, *, smb_schema):
    """Create a throwaway unified DB with smb_files / mssql integration rows."""
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
        for slug, schema in (
            ("smb_files", smb_schema),
            (
                "mssql",
                [{"key": "MSSQL_PASSWORD", "label": "Pwd", "type": "password"}],
            ),
        ):
            session.add(
                McpServerConfig(
                    id=f"id-{slug}",
                    server_slug=slug,
                    display_name=slug,
                    is_enabled_for_users=True,
                    requires_user_credentials=True,
                    credential_mode="per_user",
                    credential_schema_json=json.dumps(schema),
                )
            )
        await session.commit()


def _auth():
    from src.api.auth_login import ChatAuthIdentity

    return ChatAuthIdentity(
        user_row_id="u1", identifier="mario", via="chat_token", roles=[]
    )


_FLAGGED = [
    {"key": "SMB_USERNAME", "label": "User", "type": "text"},
    {"key": "SMB_PASSWORD", "label": "Pwd", "type": "password", "write_only": True},
]
# Same schema after an admin Hub save stripped the flag.
_STRIPPED = [
    {"key": "SMB_USERNAME", "label": "User", "type": "text"},
    {"key": "SMB_PASSWORD", "label": "Pwd", "type": "password"},
]


async def _save(slug, creds, hints=None):
    from src.api.v1.mcp_integrations import CredentialSetBody, save_credentials

    return await save_credentials(
        CredentialSetBody(server_slug=slug, credentials=creds, display_hints=hints),
        auth=_auth(),
    )


async def _get(slug, key):
    from src.api.v1.mcp_integrations import get_user_credential_value

    return await get_user_credential_value(slug, key, auth=_auth())


@pytest.mark.anyio
async def test_write_only_password_is_not_readable(monkeypatch, tmp_path):
    """GET of a write_only key -> 403 secret_write_only, also via slug variant."""
    await _setup(monkeypatch, tmp_path, smb_schema=_FLAGGED)
    await _save("smb_files", {"SMB_USERNAME": "DOM\\mario", "SMB_PASSWORD": PASSWORD})
    for slug in ("smb_files", "smb-files"):
        with pytest.raises(HTTPException) as exc:
            await _get(slug, "SMB_PASSWORD")
        assert exc.value.status_code == 403
        assert exc.value.detail == "secret_write_only"


@pytest.mark.anyio
async def test_catalog_flag_survives_stripped_db_schema(monkeypatch, tmp_path):
    """The DB schema lost write_only (Hub save): the catalog still protects it."""
    await _setup(monkeypatch, tmp_path, smb_schema=_STRIPPED)
    await _save("smb_files", {"SMB_PASSWORD": PASSWORD})
    with pytest.raises(HTTPException) as exc:
        await _get("smb_files", "SMB_PASSWORD")
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_username_and_other_connectors_stay_readable(monkeypatch, tmp_path):
    """Non write-only fields (username, other connectors) are unchanged."""
    await _setup(monkeypatch, tmp_path, smb_schema=_FLAGGED)
    await _save("smb_files", {"SMB_USERNAME": "DOM\\mario"})
    await _save("mssql", {"MSSQL_PASSWORD": "plain"})
    assert (await _get("smb_files", "SMB_USERNAME"))["value"] == "DOM\\mario"
    assert (await _get("mssql", "MSSQL_PASSWORD"))["value"] == "plain"


@pytest.mark.anyio
async def test_client_supplied_hint_is_masked(monkeypatch, tmp_path):
    """A client sending the password as display_hint gets '****' stored instead."""
    await _setup(monkeypatch, tmp_path, smb_schema=_FLAGGED)
    await _save(
        "smb_files",
        {"SMB_USERNAME": "DOM\\mario", "SMB_PASSWORD": PASSWORD},
        hints={"SMB_USERNAME": "DOM\\mario", "SMB_PASSWORD": PASSWORD},
    )
    from src.runtime.credential_store import list_credentials_hints

    hints = {
        h["key"]: h["display_hint"]
        for h in await list_credentials_hints("mario", "smb_files")
    }
    assert hints["SMB_PASSWORD"] == "****"
    assert hints["SMB_USERNAME"] == "DOM\\mario"


@pytest.mark.anyio
async def test_public_dict_exposes_flag_and_masks_hint(monkeypatch, tmp_path):
    """The integrations list carries write_only (even if the DB lost it) and no value."""
    await _setup(monkeypatch, tmp_path, smb_schema=_STRIPPED)
    await _save("smb_files", {"SMB_USERNAME": "DOM\\mario", "SMB_PASSWORD": PASSWORD})
    from sqlalchemy import select

    from src.data.engine import get_async_session_maker
    from src.data.models import McpServerConfig, UserMcpCredential
    from src.runtime.mcp_integration_helpers import integration_row_to_public_dict

    async with get_async_session_maker()() as session:
        row = (
            await session.execute(
                select(McpServerConfig).where(
                    McpServerConfig.server_slug == "smb_files"
                )
            )
        ).scalars().one()
        # Simulate a legacy row saved with an unmasked hint.
        cred = (
            await session.execute(
                select(UserMcpCredential).where(
                    UserMcpCredential.credential_key == "SMB_PASSWORD"
                )
            )
        ).scalars().one()
        cred.display_hint = PASSWORD
        await session.commit()

    pub = await integration_row_to_public_dict(
        row, user_id="mario", tenant_id="default", anonymous=False
    )
    fields = {f["key"]: f for f in pub["credential_schema"]}
    assert fields["SMB_PASSWORD"]["write_only"] is True
    assert not fields["SMB_USERNAME"].get("write_only")
    hints = {h["key"]: h["display_hint"] for h in pub["credentials_hints"]}
    assert hints["SMB_PASSWORD"] == "****"
    assert PASSWORD not in json.dumps(pub)
