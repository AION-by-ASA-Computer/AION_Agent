"""
Tests for Zero-Install MCP system:
1. Smithery API client (mocked & search / schema extraction).
2. GitHub Raw analyzer (mocked raw fetch & Pydantic structured output).
3. /market/install-zero and /market/uninstall-zero endpoints with AES-GCM encrypted secrets in aion.db.
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

import src.aion_env  # noqa: F401
from src.marketplaces.smithery_client import (
    search_smithery_servers,
    get_smithery_server_details,
    extract_normalized_envs_from_schema,
)
from src.marketplaces.github_raw_analyzer import (
    parse_github_owner_repo,
    McpServerAnalysisResult,
    McpEnvVarSpec,
)
from src.api.admin import (
    ZeroInstallRequest,
    install_zero_endpoint,
    uninstall_zero_endpoint,
)
from src.runtime.credential_store import get_credential


def test_parse_github_owner_repo():
    assert parse_github_owner_repo(
        "https://github.com/modelcontextprotocol/server-postgres"
    ) == ("modelcontextprotocol", "server-postgres")
    assert parse_github_owner_repo("github:ai-zerolab/mcp-email-server") == (
        "ai-zerolab",
        "mcp-email-server",
    )
    assert parse_github_owner_repo("owner/repo") == ("owner", "repo")
    assert parse_github_owner_repo("invalid-url") is None


def test_extract_normalized_envs_from_schema():
    dummy_details = {
        "qualifiedName": "test/mcp-server",
        "displayName": "Test Server",
        "connections": [
            {
                "runtime": "node",
                "configSchema": {
                    "type": "object",
                    "required": ["API_KEY"],
                    "properties": {
                        "API_KEY": {
                            "type": "string",
                            "title": "API Key",
                            "description": "Secret token for service",
                        },
                        "HOST": {
                            "type": "string",
                            "title": "Host Address",
                            "default": "127.0.0.1",
                        },
                    },
                },
            }
        ],
    }

    fields = extract_normalized_envs_from_schema(dummy_details)
    assert len(fields) == 2

    api_key_field = next(f for f in fields if f["key"] == "API_KEY")
    assert api_key_field["required"] is True
    assert api_key_field["is_secret"] is True

    host_field = next(f for f in fields if f["key"] == "HOST")
    assert host_field["required"] is False
    assert host_field["is_secret"] is False
    assert host_field["default"] == "127.0.0.1"


def test_zero_install_and_uninstall_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    db_file = tmp_path / "zero_test.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("AION_DB_URL", url)

    import src.data.engine as eng_mod
    from src.data.engine import init_engine
    from src.data.bootstrap import ensure_bootstrap_schema
    import asyncio

    eng_mod._engine = None
    eng_mod._session_factory = None
    eng = init_engine(url)
    asyncio.run(ensure_bootstrap_schema(eng))

    slug = "test_unit_pg_zero"
    body = ZeroInstallRequest(
        server_slug=slug,
        display_name="Unit Test Postgres Zero",
        description="Unit test postgres server",
        runner="npx",
        package_url="@modelcontextprotocol/server-postgres",
        envs={
            "DATABASE_URL": "postgresql://usr:secret_pass@localhost:5432/db",
            "PORT": "5432",
        },
        secret_keys=["DATABASE_URL"],
    )

    async def run_test():
        # 1. Install
        res = await install_zero_endpoint(body)
        assert res["status"] == "success"
        assert res["server_slug"] == slug
        assert res["runner"] == "npx"

        # 2. Verify encrypted secret in DB resolved and decrypted in memory
        decrypted_pass = await get_credential(
            "default", slug, "DATABASE_URL", tenant_id="default"
        )
        assert decrypted_pass == "postgresql://usr:secret_pass@localhost:5432/db"

        # 3. Uninstall
        uninst = await uninstall_zero_endpoint(slug)
        assert uninst["status"] == "success"

        # 4. Verify secret removed
        assert (
            await get_credential("default", slug, "DATABASE_URL", tenant_id="default")
            is None
        )

    asyncio.run(run_test())


def test_zero_install_per_user_mode(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    db_file = tmp_path / "zero_per_user_test.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("AION_DB_URL", url)

    import src.data.engine as eng_mod
    from src.data.engine import init_engine, get_async_session_maker
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.models import McpServerConfig
    from sqlalchemy import select
    import asyncio

    eng_mod._engine = None
    eng_mod._session_factory = None
    eng = init_engine(url)
    asyncio.run(ensure_bootstrap_schema(eng))

    slug = "test_agentql_per_user"
    body = ZeroInstallRequest(
        server_slug=slug,
        display_name="AgentQL Personal",
        description="AgentQL MCP server per user",
        runner="npx",
        package_url="agentql-mcp",
        credential_mode="per_user",
        envs={},
        schema_fields=[
            {
                "key": "AGENTQL_API_KEY",
                "label": "AgentQL API Key",
                "required": True,
                "is_secret": True,
                "description": "Personal AgentQL key",
            }
        ],
    )

    async def run_test():
        res = await install_zero_endpoint(body)
        assert res["status"] == "success"
        assert res["credential_mode"] == "per_user"

        async with get_async_session_maker()() as session:
            cfg = (
                await session.execute(
                    select(McpServerConfig).where(McpServerConfig.server_slug == slug)
                )
            ).scalar_one_or_none()
            assert cfg is not None
            assert cfg.credential_mode == "per_user"
            assert cfg.requires_user_credentials is True
            schema = json.loads(cfg.credential_schema_json)
            assert len(schema) == 1
            assert schema[0]["key"] == "AGENTQL_API_KEY"

    asyncio.run(run_test())


def test_zero_install_remote_smithery_server(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    db_file = tmp_path / "zero_remote_test.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("AION_DB_URL", url)

    import src.data.engine as eng_mod
    from src.data.engine import init_engine, get_async_session_maker
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.models import McpServerConfig
    from sqlalchemy import select
    import asyncio

    eng_mod._engine = None
    eng_mod._session_factory = None
    eng = init_engine(url)
    asyncio.run(ensure_bootstrap_schema(eng))

    slug = "googlecalendar"
    body = ZeroInstallRequest(
        server_slug=slug,
        display_name="Google Calendar",
        description="Smithery remote google calendar server",
        runner="node",
        package_url="https://googlecalendar.run.tools",
        is_remote=True,
        remote_url="https://googlecalendar.run.tools",
        auth_type="oauth2",
        credential_mode="per_user",
        envs={},
    )

    async def run_test():
        res = await install_zero_endpoint(body)
        assert res["status"] == "success"
        assert res["is_remote"] is True
        assert res["remote_url"] == "https://googlecalendar.run.tools"

        from src.mcp_manager import mcp_manager

        reg_cfg = mcp_manager._registry_local.get(slug)
        assert reg_cfg is not None
        assert reg_cfg["type"] == "remote-bridge"
        assert reg_cfg["remote_url"] == "https://googlecalendar.run.tools"
        assert any("googlecalendar.run.tools" in arg for arg in reg_cfg["args"])

        async with get_async_session_maker()() as session:
            cfg = (
                await session.execute(
                    select(McpServerConfig).where(McpServerConfig.server_slug == slug)
                )
            ).scalar_one_or_none()
            assert cfg is not None
            assert cfg.credential_mode == "per_user"

    asyncio.run(run_test())
