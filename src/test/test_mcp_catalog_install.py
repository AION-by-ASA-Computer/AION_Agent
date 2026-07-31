"""Catalog-based MCP install (no marketplace)."""

import pytest

from src.mcp_catalog_install import build_registry_config_for_connector
from src.mcp_connector_catalog import load_mcp_connector_catalog, _connector_by_id


def test_build_clickup_registry_config_remote():
    catalog = load_mcp_connector_catalog()
    row = _connector_by_id(catalog, "clickup")
    if row is None:
        pytest.skip("clickup connector not in catalog")
    slug, cfg = build_registry_config_for_connector(row)
    assert slug == "clickup"
    assert cfg["type"] == "remote-bridge"
    assert cfg.get("remote_url") == "https://mcp.clickup.com/mcp"
    assert cfg.get("aion_connector_id") == "clickup"
    assert cfg.get("auth_env_var", "").endswith("__OAUTH_TOKEN")


def test_build_email_imap_stdio_config():
    catalog = load_mcp_connector_catalog()
    row = _connector_by_id(catalog, "email_imap")
    assert row is not None
    slug, cfg = build_registry_config_for_connector(row)
    assert slug == "email_imap"
    assert cfg.get("command")
    assert cfg.get("aion_connector_id") == "email_imap"
