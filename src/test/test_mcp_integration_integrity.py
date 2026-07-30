"""Tests for MCP integration integrity checks."""

from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

import pytest

from src.data.bootstrap import ensure_bootstrap_schema
from src.data.engine import init_engine
from src.data.ids import new_uuid7_str
from src.data.models import UserMcpCredential
from src.runtime.credential_store import encrypt_value
from src.runtime.mcp_integration_integrity import (
    build_suggested_env_yaml_block,
    enrich_credential_schema_with_env_placeholders,
    migrate_credentials_to_slug,
)


@pytest.fixture()
def integrity_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'integrity.db'}"
    monkeypatch.setenv("AION_DB_URL", url)
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", secrets.token_hex(32))
    import src.data.engine as eng_mod

    eng_mod._engine = None  # type: ignore[attr-defined]
    eng_mod._session_factory = None  # type: ignore[attr-defined]
    eng = init_engine(url)
    asyncio.run(ensure_bootstrap_schema(eng))
    return url


def test_enrich_credential_schema_per_user_placeholder():
    schema = [
        {"key": "API_TOKEN", "label": "Token", "type": "password", "required": True}
    ]
    out = enrich_credential_schema_with_env_placeholders(
        schema, "my-mcp-server", credential_mode="per_user"
    )
    assert out[0]["env_placeholder"] == "${AION_USER_MY_MCP_SERVER__API_TOKEN}"
    assert out[0]["registry_env_key"] == "API_TOKEN"


def test_build_suggested_env_yaml_block():
    schema = [
        {"key": "API_TOKEN", "label": "Token", "type": "password", "required": True}
    ]
    enriched = enrich_credential_schema_with_env_placeholders(
        schema, "clickup", credential_mode="per_user"
    )
    yaml = build_suggested_env_yaml_block(
        "clickup", enriched, credential_mode="per_user"
    )
    assert 'API_TOKEN: "${AION_USER_CLICKUP__API_TOKEN}"' in yaml
    assert yaml.startswith("env:")


@pytest.mark.asyncio
async def test_migrate_credentials_merges_duplicate_keys(integrity_db: str) -> None:
    from sqlalchemy import func, select

    from src.data.engine import get_async_session_maker

    async with get_async_session_maker()() as session:
        session.add(
            UserMcpCredential(
                id=new_uuid7_str(),
                user_id="demo",
                tenant_id="default",
                server_slug="clickup",
                credential_key="CLICKUP_API_KEY",
                value_encrypted=encrypt_value("newer-key"),
            )
        )
        session.add(
            UserMcpCredential(
                id=new_uuid7_str(),
                user_id="demo",
                tenant_id="default",
                server_slug="clickup-mcp-server",
                credential_key="CLICKUP_API_KEY",
                value_encrypted=encrypt_value("older-key"),
            )
        )
        session.add(
            UserMcpCredential(
                id=new_uuid7_str(),
                user_id="admin",
                tenant_id="default",
                server_slug="clickup-mcp-server",
                credential_key="OAUTH_TOKEN",
                value_encrypted=encrypt_value("oauth"),
            )
        )
        await session.commit()

    result = await migrate_credentials_to_slug("clickup-mcp-server", "clickup")
    assert result["deleted_duplicates"] == 1
    assert result["migrated"] == 1
    assert result["total"] == 2

    async with get_async_session_maker()() as session:
        rows = (
            await session.execute(
                select(
                    UserMcpCredential.server_slug, UserMcpCredential.credential_key
                ).where(UserMcpCredential.user_id.in_(["demo", "admin"]))
            )
        ).all()
        orphan_count = (
            await session.execute(
                select(func.count())
                .select_from(UserMcpCredential)
                .where(UserMcpCredential.server_slug == "clickup-mcp-server")
            )
        ).scalar_one()
    assert orphan_count == 0
    assert ("clickup", "CLICKUP_API_KEY") in rows
    assert ("clickup", "OAUTH_TOKEN") in rows
    assert ("clickup-mcp-server", "CLICKUP_API_KEY") not in rows
