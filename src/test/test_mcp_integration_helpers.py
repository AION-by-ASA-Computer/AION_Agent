"""Public integration dict helpers (OAuth remote MCP)."""

from src.mcp_connector_catalog import (
    _connector_by_id,
    load_mcp_connector_catalog,
    merge_oauth_config,
    oauth_config_from_connector,
    oauth_ui_metadata_from_connector,
)
from src.runtime.mcp_integration_helpers import (
    oauth_alias_dest_keys,
    strip_oauth_token_fields_from_schema,
    strip_oauth_user_fields_for_server,
)


def test_oauth_ui_metadata_from_catalog_row():
    meta = oauth_ui_metadata_from_connector(
        {
            "id": "clickup",
            "title": "ClickUp",
            "auth_type": "oauth2",
        }
    )
    assert meta == {"provider": "clickup", "oauth_display_name": "ClickUp"}


def test_oauth_ui_metadata_custom_provider():
    meta = oauth_ui_metadata_from_connector(
        {
            "id": "acme",
            "title": "Acme Corp",
            "auth_type": "oauth2",
            "oauth_provider": "acme_sso",
        }
    )
    assert meta == {"provider": "acme_sso", "oauth_display_name": "Acme Corp"}


def test_oauth_ui_metadata_non_oauth_connector():
    meta = oauth_ui_metadata_from_connector(
        {"id": "email_imap", "title": "Email (IMAP / SMTP)", "auth_type": "none"},
        fallback_provider="legacy",
        fallback_display_name="Legacy",
    )
    assert meta == {"provider": "legacy", "oauth_display_name": "Legacy"}


def test_strip_oauth_token_fields():
    schema = [
        {"key": "OAUTH_TOKEN", "type": "oauth", "required": True},
        {"key": "API_KEY", "type": "password", "required": True},
    ]
    cleaned = strip_oauth_token_fields_from_schema(schema)
    assert [f["key"] for f in cleaned] == ["API_KEY"]


def test_ms365_hides_manual_oauth_token_field():
    row = _connector_by_id(load_mcp_connector_catalog(), "ms365")
    assert row is not None
    extra = oauth_alias_dest_keys(row)
    assert "MS365_MCP_OAUTH_TOKEN" in extra
    schema = [
        {"key": "OAUTH_TOKEN", "type": "oauth"},
        {"key": "MS365_MCP_OAUTH_TOKEN", "type": "password"},
        {"key": "MS365_MCP_TENANT_ID", "type": "text"},
    ]
    cleaned = strip_oauth_token_fields_from_schema(schema, extra_keys=extra)
    assert [f["key"] for f in cleaned] == ["MS365_MCP_TENANT_ID"]


def test_ms365_admin_schema_drops_manual_token_fields():
    schema = [
        {"key": "MS365_MCP_OAUTH_TOKEN", "type": "password", "required": True},
        {"key": "OAUTH_TOKEN", "type": "password", "required": True},
    ]
    cleaned = strip_oauth_user_fields_for_server(
        schema, "ms365", {}, connector_id="ms365"
    )
    assert cleaned == []


def test_merge_oauth_config_catalog_overrides_bad_discovery():
    catalog = oauth_config_from_connector(
        {
            "id": "github",
            "auth_type": "oauth2",
            "oauth": {
                "authorization_server": "https://github.com/login/oauth",
                "authorization_endpoint": "https://github.com/login/oauth/authorize",
                "token_url": "https://github.com/login/oauth/access_token",
            },
        }
    )
    merged = merge_oauth_config(
        {
            "authorization_server": "https://api.githubcopilot.com",
            "token_url": "https://api.githubcopilot.com/token",
            "client_id": "admin-client",
        },
        catalog,
        catalog_overrides=True,
    )
    assert merged["authorization_server"] == "https://github.com/login/oauth"
    assert merged["token_url"] == "https://github.com/login/oauth/access_token"
    assert merged["client_id"] == "admin-client"
