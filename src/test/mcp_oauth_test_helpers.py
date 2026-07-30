"""Shared fixtures for MCP OAuth tests."""

from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path
from typing import Any, Dict

import pytest

from src.data.bootstrap import ensure_bootstrap_schema
from src.data.engine import init_engine
from src.data.ids import new_uuid7_str


@pytest.fixture()
def oauth_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'oauth.db'}"
    monkeypatch.setenv("AION_DB_URL", url)
    monkeypatch.setenv("AION_MCP_USER_CREDENTIALS", "1")
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", secrets.token_hex(32))
    monkeypatch.setenv("AION_MCP_OAUTH_DYNAMIC_REGISTRATION", "1")
    import src.data.engine as eng_mod

    eng_mod._engine = None  # type: ignore[attr-defined]
    eng_mod._session_factory = None  # type: ignore[attr-defined]
    eng = init_engine(url)
    asyncio.run(ensure_bootstrap_schema(eng))
    return url


async def _insert_mcp_server_config(
    server_slug: str,
    *,
    oauth_config: Dict[str, Any] | None = None,
) -> None:
    from sqlalchemy import select

    from src.data.engine import get_async_session_maker
    from src.data.models import McpServerConfig

    async with get_async_session_maker()() as session:
        existing = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug == server_slug
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing:
            existing.oauth_config_json = json.dumps(oauth_config or {})
            await session.commit()
            return

        session.add(
            McpServerConfig(
                id=new_uuid7_str(),
                server_slug=server_slug,
                display_name=server_slug.replace("-", " ").title(),
                is_enabled_for_users=True,
                requires_user_credentials=True,
                credential_schema_json="[]",
                oauth_config_json=json.dumps(oauth_config or {}),
            )
        )
        await session.commit()

async def insert_mcp_server_config(
    server_slug: str,
    *,
    oauth_config: Dict[str, Any] | None = None,
) -> None:
    await _insert_mcp_server_config(server_slug, oauth_config=oauth_config)
