"""Tests for mcp_integration_sync (catalog → schema, mode inference)."""

from __future__ import annotations

from src.mcp_credential_discovery import discover_mcp_credentials, merge_schema_sources
from src.mcp_integration_sync import (
    credential_schema_from_connector,
    infer_credential_mode,
    suggest_registry_env_for_per_user,
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


def test_clickup_catalog_per_user_env_e2e() -> None:
    from src.mcp_connector_catalog import load_mcp_connector_catalog

    catalog = load_mcp_connector_catalog()
    clickup = next(
        (
            c
            for c in (catalog.get("connectors") or [])
            if isinstance(c, dict) and c.get("id") == "clickup"
        ),
        None,
    )
    assert clickup is not None
    schema = credential_schema_from_connector(clickup)
    assert any(f.get("key") == "CLICKUP_API_KEY" for f in schema)
    env = suggest_registry_env_for_per_user("clickup", schema)
    assert env["CLICKUP_API_KEY"] == "${AION_USER_CLICKUP__CLICKUP_API_KEY}"
    mode = infer_credential_mode({"env": env}, clickup)
    assert mode == "per_user"
