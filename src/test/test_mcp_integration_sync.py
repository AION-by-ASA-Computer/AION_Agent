"""Tests for mcp_integration_sync (catalog → schema, mode inference)."""

from __future__ import annotations

from src.mcp_credential_discovery import discover_mcp_credentials, merge_schema_sources
from src.mcp_integration_sync import (
    credential_schema_from_connector,
    infer_credential_mode,
    restore_static_and_oauth_env,
    suggest_registry_env_for_per_user,
    validate_policy_vs_registry,
)


def test_credential_schema_from_connector_fields() -> None:
    row = {
        "credential_fields": [
            {
                "key": "CLICKUP_API_KEY",
                "label": "API Key",
                "secret": True,
                "required": True,
            },
        ],
    }
    schema = credential_schema_from_connector(row)
    assert len(schema) == 1
    assert schema[0]["key"] == "CLICKUP_API_KEY"
    assert schema[0]["type"] == "password"


def test_suggest_registry_env_per_user() -> None:
    schema = [{"key": "CLICKUP_API_KEY"}]
    env = suggest_registry_env_for_per_user("clickup", schema)
    assert env["CLICKUP_API_KEY"] == "${AION_USER_CLICKUP__CLICKUP_API_KEY}"


def test_discover_new_registry_env_key() -> None:
    cfg = {
        "env": {
            "MCP_EMAIL_SERVER_IMAP_HOST": "${AION_USER_MCP_EMAIL_SERVER__MCP_EMAIL_SERVER_IMAP_HOST}",
            "MCP_EMAIL_SERVER_SMTP_START_SSL": "${AION_USER_MCP_EMAIL_SERVER__MCP_EMAIL_SERVER_SMTP_START_SSL}",
        }
    }
    result = discover_mcp_credentials("mcp-email-server", cfg)
    keys = {f["key"] for f in result.schema}
    assert "MCP_EMAIL_SERVER_SMTP_START_SSL" in keys
    assert not any(k.startswith("AION_USER_") for k in keys)


def test_registry_env_does_not_duplicate_placeholder_slug() -> None:
    from src.mcp_credential_discovery import _keys_from_registry_env

    env = {
        "MCP_EMAIL_SERVER_PASSWORD": "${AION_USER_MCP_EMAIL_SERVER__MCP_EMAIL_SERVER_PASSWORD}",
    }
    keys = _keys_from_registry_env(env)
    assert keys == {"MCP_EMAIL_SERVER_PASSWORD"}


def test_merge_schema_adds_new_keys_without_dropping_existing() -> None:
    current = [
        {
            "key": "MCP_EMAIL_SERVER_IMAP_HOST",
            "label": "Custom IMAP",
            "type": "text",
            "required": True,
        }
    ]
    fresh = [
        {
            "key": "MCP_EMAIL_SERVER_IMAP_HOST",
            "label": "IMAP Host",
            "type": "text",
            "required": True,
        },
        {
            "key": "MCP_EMAIL_SERVER_SMTP_START_SSL",
            "label": "Smtp Start Ssl",
            "type": "text",
            "required": True,
        },
    ]
    merged = merge_schema_sources(catalog_schema=current, discovered_schema=fresh)
    by_key = {r["key"]: r for r in merged}
    assert by_key["MCP_EMAIL_SERVER_IMAP_HOST"]["label"] == "Custom IMAP"
    assert "MCP_EMAIL_SERVER_SMTP_START_SSL" in by_key


def test_infer_mode_per_user_from_env() -> None:
    cfg = {"env": {"TOKEN": "${AION_USER_CLICKUP__TOKEN}"}}
    assert infer_credential_mode(cfg, None) == "per_user"


def test_infer_mode_org_shared_literal() -> None:
    cfg = {"env": {"CLICKUP_API_KEY": "pk_live_abc"}}
    conn = {"credential_fields": [{"key": "CLICKUP_API_KEY"}]}
    assert infer_credential_mode(cfg, conn) == "org_shared"


def test_ms365_suggest_keeps_tenant_literals() -> None:
    from src.mcp_connector_catalog import _connector_by_id, load_mcp_connector_catalog

    row = _connector_by_id(load_mcp_connector_catalog(), "ms365")
    assert row is not None
    env = suggest_registry_env_for_per_user(
        "ms365",
        [{"key": "MS365_MCP_TENANT_ID"}, {"key": "MS365_MCP_OAUTH_TOKEN"}],
        current_env={
            "MS365_MCP_OAUTH_TOKEN": "${AION_USER_MS365__OAUTH_TOKEN}",
            "MS365_MCP_TENANT_ID": "common",
            "MS365_MCP_ORG_MODE": "true",
        },
        connector_row=row,
    )
    assert env["MS365_MCP_OAUTH_TOKEN"] == "${AION_USER_MS365__OAUTH_TOKEN}"
    assert env["MS365_MCP_TENANT_ID"] == "common"
    assert env["MS365_MCP_ORG_MODE"] == "true"
    assert "AION_USER_MS365__MS365_MCP_TENANT_ID" not in env
    assert "AION_USER_MS365__MS365_MCP_OAUTH_TOKEN" not in env


def test_ms365_restore_rewrites_double_prefixed_placeholders() -> None:
    from src.mcp_connector_catalog import _connector_by_id, load_mcp_connector_catalog

    row = _connector_by_id(load_mcp_connector_catalog(), "ms365")
    assert row is not None
    repaired = restore_static_and_oauth_env(
        "ms365",
        {
            "MS365_MCP_OAUTH_TOKEN": "${AION_USER_MS365__MS365_MCP_OAUTH_TOKEN}",
            "MS365_MCP_TENANT_ID": "${AION_USER_MS365__MS365_MCP_TENANT_ID}",
            "MS365_MCP_ORG_MODE": "${AION_USER_MS365__MS365_MCP_ORG_MODE}",
            "AION_USER_MS365__MS365_MCP_TENANT_ID": "${AION_USER_MS365__MS365_MCP_TENANT_ID}",
            "AION_USER_MS365__MS365_MCP_ORG_MODE": "${AION_USER_MS365__MS365_MCP_ORG_MODE}",
            "OAUTH_TOKEN": "${AION_USER_MS365__OAUTH_TOKEN}",
        },
        connector_row=row,
    )
    assert repaired["MS365_MCP_OAUTH_TOKEN"] == "${AION_USER_MS365__OAUTH_TOKEN}"
    assert repaired["MS365_MCP_TENANT_ID"] == "common"
    assert repaired["MS365_MCP_ORG_MODE"] == "true"
    assert "AION_USER_MS365__MS365_MCP_TENANT_ID" not in repaired
    assert "AION_USER_MS365__MS365_MCP_ORG_MODE" not in repaired


def test_ms365_literals_do_not_fail_policy_validation() -> None:
    warnings = validate_policy_vs_registry(
        "ms365",
        {
            "env": {
                "MS365_MCP_OAUTH_TOKEN": "${AION_USER_MS365__OAUTH_TOKEN}",
                "MS365_MCP_TENANT_ID": "common",
                "MS365_MCP_ORG_MODE": "true",
            }
        },
        "per_user",
        credential_schema=[],
    )
    assert warnings == []


def test_clickup_catalog_per_user_env_e2e() -> None:
    clickup = {
        "id": "clickup",
        "credential_fields": [
            {"key": "CLICKUP_API_KEY", "secret": True, "required": True}
        ],
    }
    schema = credential_schema_from_connector(clickup)
    assert any(f.get("key") == "CLICKUP_API_KEY" for f in schema)
    env = suggest_registry_env_for_per_user("clickup", schema)
    assert env["CLICKUP_API_KEY"] == "${AION_USER_CLICKUP__CLICKUP_API_KEY}"
    mode = infer_credential_mode({"env": env}, clickup)
    assert mode == "per_user"
