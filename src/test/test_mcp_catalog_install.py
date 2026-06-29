"""Catalog-based MCP install (no marketplace)."""
import pytest

from src.mcp_catalog_install import build_registry_config_for_connector
from src.mcp_connector_catalog import load_mcp_connector_catalog, _connector_by_id


def test_build_clickup_registry_config():
    catalog = load_mcp_connector_catalog()
    row = _connector_by_id(catalog, "clickup")
    if row is None:
        pytest.skip("clickup connector not in committed catalog")
    slug, cfg = build_registry_config_for_connector(row)
    assert slug == "clickup"
    assert cfg["command"] == "npx"
    assert "@hauptsache.net/clickup-mcp" in str(cfg.get("args"))
    assert cfg.get("aion_connector_id") == "clickup"
    assert "CLICKUP_API_KEY" in (cfg.get("env") or {})
