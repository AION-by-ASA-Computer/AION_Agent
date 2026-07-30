"""Curated MCP connector catalog YAML."""

from src.mcp_connector_catalog import (
    connector_catalog_std_path,
    extract_entra_tenant_id_from_remote_url,
    infer_connector_id_for_registry_name,
    load_mcp_connector_catalog,
    oauth_admin_credentials_configured,
    oauth_admin_client_credentials_required,
    oauth_config_from_connector,
    resolve_oauth_url_templates,
)
from src.mcp_catalog_install import build_registry_config_for_connector
from src.mcp_connector_catalog import _connector_by_id


def test_connector_catalog_std_path_exists():
    assert connector_catalog_std_path().exists()


def test_load_connector_catalog_has_entries():
    data = load_mcp_connector_catalog()
    assert "connectors" in data
    con = data["connectors"]
    assert isinstance(con, list)
    assert len(con) >= 10
    ids = {c.get("id") for c in con if isinstance(c, dict)}
    assert "gmail" in ids
    assert "notion" in ids
    assert "clickup" in ids
    assert "email_imap" in ids
    assert "linear" in ids
    assert "slack" in ids


def test_infer_connector_from_registry_name():
    data = load_mcp_connector_catalog()
    assert infer_connector_id_for_registry_name("clickup-mcp-server", data) == "clickup"
    assert infer_connector_id_for_registry_name("notion_integration", data) == "notion"
    assert (
        infer_connector_id_for_registry_name("my-imap-mcp-bridge", data) == "email_imap"
    )
    assert (
        infer_connector_id_for_registry_name("email-mcp-server", data) == "email_imap"
    )


def test_remote_oauth_connectors_use_remote_bridge():
    catalog = load_mcp_connector_catalog()
    for cid in ("clickup", "notion", "linear"):
        row = _connector_by_id(catalog, cid)
        assert row is not None, cid
        slug, cfg = build_registry_config_for_connector(row)
        assert cfg["type"] == "remote-bridge"
        assert cfg.get("remote_url", "").startswith("https://")
        assert cfg.get("aion_connector_id") == cid
        assert slug == cid


def test_google_gmail_oauth_config_from_catalog():
    catalog = load_mcp_connector_catalog()
    row = _connector_by_id(catalog, "gmail")
    assert row is not None
    oauth = oauth_config_from_connector(row)
    assert oauth["authorization_endpoint"] == "https://accounts.google.com/o/oauth2/v2/auth"
    assert oauth["token_url"] == "https://oauth2.googleapis.com/token"
    assert oauth.get("client_credentials_required") is True
    assert "gmail.readonly" in oauth["scopes"][0]


def test_github_oauth_config_from_catalog():
    catalog = load_mcp_connector_catalog()
    row = _connector_by_id(catalog, "github")
    assert row is not None
    oauth = oauth_config_from_connector(row)
    assert oauth["authorization_endpoint"] == "https://github.com/login/oauth/authorize"
    assert oauth.get("resource") == "https://api.githubcopilot.com/mcp"
    assert oauth.get("client_credentials_required") is True


def test_sharepoint_oauth_resolves_tenant_from_remote_url():
    catalog = load_mcp_connector_catalog()
    row = _connector_by_id(catalog, "microsoft_sharepoint")
    assert row is not None
    oauth = oauth_config_from_connector(row)
    assert "{tenant_id}" in oauth["authorization_endpoint"]
    assert oauth.get("client_credentials_required") is True

    tenant = "11111111-2222-3333-4444-555555555555"
    remote = (
        f"https://agent365.svc.cloud.microsoft/agents/tenants/{tenant}"
        "/servers/mcp_SharePointRemoteServer"
    )
    assert extract_entra_tenant_id_from_remote_url(remote) == tenant
    resolved = resolve_oauth_url_templates(oauth, remote_url=remote)
    assert tenant in resolved["authorization_endpoint"]
    assert tenant in resolved["token_url"]
    assert tenant in resolved["resource"]
    assert "{tenant_id}" not in resolved["authorization_endpoint"]


def test_oauth_admin_credentials_required_for_github_catalog():
    catalog = load_mcp_connector_catalog()
    row = _connector_by_id(catalog, "github")
    oauth = oauth_config_from_connector(row)
    assert oauth_admin_client_credentials_required(oauth) is True
    assert oauth_admin_credentials_configured(oauth) is False
    assert oauth_admin_credentials_configured({**oauth, "client_id": "id", "client_secret": "sec"}) is True


def test_oauth_admin_credentials_not_required_without_flag():
    assert oauth_admin_client_credentials_required({}) is False
    assert oauth_admin_credentials_configured({}) is True
