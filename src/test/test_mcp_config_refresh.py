"""MCP Hub configuration changes reach the MCP process.

Covers the three causes of "the variables I set are not picked up":
- install-zero (org_shared) wrote a ``${KEY}`` placeholder for every field left
  empty, which showed up in Configura and resolved to "" at spawn;
- secrets are stored encrypted, templates like ``Bearer ${TOKEN}`` are not;
- pooled stdio workers kept the env they were spawned with until a restart.
Also covers the admin endpoint that lets Configura show a stored shared secret.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import src.aion_env  # noqa: F401
from src.api.admin import (
    ZeroInstallRequest,
    _store_org_shared_secrets,
    get_mcp_shared_secret,
    install_zero_endpoint,
)
from src.mcp_manager import mcp_manager
from src.runtime.credential_store import get_credential


def _fake_worker():
    """Pool worker stand-in exposing what restart_workers_for_server touches."""
    worker = MagicMock()
    worker._task = None
    worker.shutdown = AsyncMock()
    return worker


def test_restart_workers_for_server_stops_only_that_server():
    """Workers of the changed server stop in every session; other servers keep running."""
    db2_a, db2_b, other = _fake_worker(), _fake_worker(), _fake_worker()
    pool = {("s1", "db2"): db2_a, ("s2", "db2"): db2_b, ("s1", "grafana"): other}

    async def run():
        with (
            patch.object(mcp_manager, "_pool", pool),
            patch.object(mcp_manager, "_pool_lock", asyncio.Lock()),
        ):
            stopped = await mcp_manager.restart_workers_for_server("db2")
            return stopped, dict(mcp_manager._pool)

    stopped, remaining = asyncio.run(run())
    assert stopped == 2
    assert remaining == {("s1", "grafana"): other}
    db2_a.shutdown.assert_awaited_once()
    db2_b.shutdown.assert_awaited_once()
    other.shutdown.assert_not_awaited()


def test_store_org_shared_secrets_keeps_templates_and_plain_values():
    """Only literal secrets are moved; templates, placeholders and plain values stay."""
    set_cred = AsyncMock()
    env = {
        "API_KEY": "abc",
        "AUTH_HEADER": "Bearer ${API_KEY}",
        "DB2I_PASSWORD": "${DB2I_PASSWORD}",
        "DB2I_HOSTNAME": "10.0.0.1",
    }
    with patch("src.runtime.credential_store.set_credential", set_cred):
        out = asyncio.run(_store_org_shared_secrets("srv", env))
    assert out == {
        "API_KEY": "${API_KEY}",
        "AUTH_HEADER": "Bearer ${API_KEY}",
        "DB2I_PASSWORD": "${DB2I_PASSWORD}",
        "DB2I_HOSTNAME": "10.0.0.1",
    }
    assert set_cred.await_count == 2  # API_KEY for "default" and "org_shared"


def test_zero_install_org_shared_writes_only_filled_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """Empty wizard fields are omitted; filled secrets are encrypted behind a placeholder."""
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    url = f"sqlite+aiosqlite:///{tmp_path / 'refresh_test.db'}"
    monkeypatch.setenv("AION_DB_URL", url)

    import src.data.engine as eng_mod
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import init_engine

    eng_mod._engine = None
    eng_mod._session_factory = None
    asyncio.run(ensure_bootstrap_schema(init_engine(url)))

    slug = "test_unit_db2_refresh"
    body = ZeroInstallRequest(
        server_slug=slug,
        package_url="mcp-server-db2i",
        credential_mode="org_shared",
        envs={"DB2I_HOSTNAME": "192.168.10.241", "DB2I_PASSWORD": "pw"},
        secret_keys=["DB2I_PASSWORD"],
        schema_fields=[
            {"key": "DB2I_HOSTNAME", "required": True, "is_secret": False},
            {"key": "DB2I_PASSWORD", "required": True, "is_secret": True},
            {"key": "DB2I_SCHEMA", "required": False, "is_secret": False},
            {"key": "MCP_AUTH_MODE", "required": False, "is_secret": True},
        ],
    )

    async def run():
        # Keep the real config/mcp_registry.local.yaml untouched.
        with patch.object(mcp_manager, "save_registry"):
            try:
                await install_zero_endpoint(body)
                env = dict(mcp_manager._registry_local[slug]["env"])
                secret = await get_credential(
                    "default", slug, "DB2I_PASSWORD", tenant_id="default"
                )
                return env, secret
            finally:
                mcp_manager._registry_local.pop(slug, None)
                mcp_manager._rebuild_merged()

    env, secret = asyncio.run(run())
    assert env == {
        "DB2I_HOSTNAME": "192.168.10.241",
        "DB2I_PASSWORD": "${DB2I_PASSWORD}",
    }
    assert secret == "pw"


_SECRET_REGISTRY = {
    "db2": {"env": {"DB2I_USERNAME": "AION", "DB2I_PASSWORD": "${DB2I_PASSWORD}"}},
    "other": {"env": {"API_KEY": "${API_KEY}"}},
}


def _read_secret(name, key, stored):
    """Call the secret endpoint with the registry and credential store mocked."""
    with (
        patch.object(mcp_manager, "_registry", _SECRET_REGISTRY),
        patch(
            "src.runtime.credential_store.get_credential",
            AsyncMock(return_value=stored),
        ),
    ):
        return asyncio.run(get_mcp_shared_secret(name, key))


def test_shared_secret_endpoint_returns_stored_value():
    """Configura can pre-fill a secret referenced by the server's own registry env."""
    assert _read_secret("db2", "DB2I_PASSWORD", "pw") == {
        "key": "DB2I_PASSWORD",
        "value": "pw",
    }


def test_shared_secret_endpoint_refuses_unreferenced_keys():
    """A key the server does not reference (e.g. another server's token) is not readable."""
    with pytest.raises(HTTPException) as err:
        _read_secret("db2", "API_KEY", "leaked")
    assert err.value.status_code == 404
