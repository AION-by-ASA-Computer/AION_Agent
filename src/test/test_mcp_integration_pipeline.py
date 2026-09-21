"""Pipeline unificato MCP: env per_user/org_shared e contratto email."""

from src.mcp_connector_catalog import _connector_by_id, load_mcp_connector_catalog
from src.mcp_integration_sync import (
    merge_suggested_env_into_registry,
    suggest_registry_env_for_per_user,
)


def test_email_env_contract_catalog_matches_server():
    catalog = load_mcp_connector_catalog()
    row = _connector_by_id(catalog, "email_imap")
    assert row is not None
    keys = {f["key"] for f in row.get("credential_fields") or []}
    assert keys == {
        "EMAIL_USER",
        "EMAIL_PASSWORD",
        "IMAP_HOST",
        "IMAP_PORT",
        "SMTP_HOST",
        "SMTP_PORT",
    }


def test_suggest_registry_env_email_slug():
    catalog = load_mcp_connector_catalog()
    row = _connector_by_id(catalog, "email_imap")
    from src.mcp_integration_sync import credential_schema_from_connector

    schema = credential_schema_from_connector(row)
    env = suggest_registry_env_for_per_user("email-mcp-server", schema)
    assert env["EMAIL_USER"] == "${AION_USER_EMAIL_MCP_SERVER__EMAIL_USER}"
    assert env["IMAP_PORT"] == "${AION_USER_EMAIL_MCP_SERVER__IMAP_PORT}"


def test_merge_suggested_env_with_custom_schema(monkeypatch):
    """schema_override path: merge uses provided schema keys."""
    fake_registry = {
        "test_email_srv": {
            "command": "bun",
            "args": ["run", "x"],
            "aion_connector_id": "email_imap",
            "env": {},
        }
    }

    def _get_cfg(name):
        return fake_registry.get(name)

    monkeypatch.setattr(
        "src.mcp_integration_sync.mcp_manager.get_server_config",
        _get_cfg,
    )
    monkeypatch.setattr(
        "src.mcp_integration_sync.mcp_manager._registry",
        fake_registry,
    )
    monkeypatch.setattr(
        "src.mcp_integration_sync.mcp_manager.update_server_config",
        lambda slug, patch: fake_registry[slug].update(patch),
    )
    monkeypatch.setattr(
        "src.mcp_integration_sync.build_integration_preview",
        lambda slug, credential_mode=None: {
            "ok": True,
            "credential_schema": [],
            "warnings": [],
        },
    )

    schema = [{"key": "EMAIL_USER", "required": True}]
    result = merge_suggested_env_into_registry(
        "test_email_srv",
        "per_user",
        credential_schema=schema,
    )
    assert result["ok"]
    assert "EMAIL_USER" in result["env"]
    assert "${AION_USER_TEST_EMAIL_SRV__EMAIL_USER}" in result["env"]["EMAIL_USER"]


def test_merge_suggested_env_org_to_per_user_transition(monkeypatch):
    """When switching from org_shared literal/placeholder to per_user, force_replace_schema_env updates env properly."""
    fake_registry = {
        "custom_tool": {
            "command": "node",
            "args": ["index.js"],
            "env": {
                "API_KEY": "${API_KEY}",
                "ANOTHER_SECRET": "literal_val_123",
            },
        }
    }

    monkeypatch.setattr(
        "src.mcp_integration_sync.mcp_manager.get_server_config",
        lambda name: fake_registry.get(name),
    )
    monkeypatch.setattr(
        "src.mcp_integration_sync.mcp_manager._registry",
        fake_registry,
    )
    monkeypatch.setattr(
        "src.mcp_integration_sync.mcp_manager.update_server_config",
        lambda slug, patch: fake_registry[slug].update(patch),
    )
    monkeypatch.setattr(
        "src.mcp_integration_sync.build_integration_preview",
        lambda slug, credential_mode=None: {
            "ok": True,
            "credential_schema": [],
            "warnings": [],
        },
    )

    result = merge_suggested_env_into_registry(
        "custom_tool",
        "per_user",
        force_replace_schema_env=True,
    )
    assert result["ok"]
    assert result["env"]["API_KEY"] == "${AION_USER_CUSTOM_TOOL__API_KEY}"
    assert (
        result["env"]["AION_USER_CUSTOM_TOOL__API_KEY"]
        == "${AION_USER_CUSTOM_TOOL__API_KEY}"
    )
    assert result["env"]["ANOTHER_SECRET"] == "${AION_USER_CUSTOM_TOOL__ANOTHER_SECRET}"
    assert len(result["warnings"]) == 0
