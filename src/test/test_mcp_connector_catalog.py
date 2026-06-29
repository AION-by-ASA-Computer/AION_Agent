"""Curated MCP connector catalog YAML."""

from src.mcp_connector_catalog import infer_connector_id_for_registry_name, load_mcp_connector_catalog


def test_load_connector_catalog_has_entries():
    data = load_mcp_connector_catalog()
    assert "connectors" in data
    con = data["connectors"]
    assert isinstance(con, list)
    assert len(con) >= 4
    ids = {c.get("id") for c in con if isinstance(c, dict)}
    assert "gmail" in ids
    assert "notion" in ids
    assert "clickup" in ids
    assert "email_imap" in ids


def test_infer_connector_from_registry_name():
    data = load_mcp_connector_catalog()
    assert infer_connector_id_for_registry_name("clickup-mcp-server", data) == "clickup"
    assert infer_connector_id_for_registry_name("notion_integration", data) == "notion"
    assert infer_connector_id_for_registry_name("my-imap-mcp-bridge", data) == "email_imap"
    assert infer_connector_id_for_registry_name("email-mcp-server", data) == "email_imap"
