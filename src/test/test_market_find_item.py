"""Regression: install by npx:/github: id without marketplace re-search."""

from src.api.admin import (
    _find_marketplace_item,
    _synthetic_github_market_item,
    _synthetic_npx_market_item,
)


def test_synthetic_npx_clickup():
    item = _synthetic_npx_market_item("npx:@hauptsache.net/clickup-mcp")
    assert item is not None
    assert item["install_type"] == "npx"
    assert item["npx_package"] == "@hauptsache.net/clickup-mcp"


def test_find_marketplace_item_npx_without_network():
    """Must resolve npx id locally (no HTTP to GitHub/Glama)."""
    item = _find_marketplace_item("npx:@hauptsache.net/clickup-mcp")
    assert item is not None
    assert item["install_type"] == "npx"
    assert "@hauptsache.net/clickup-mcp" in (
        item.get("npx_package") or item.get("id", "")
    )


def test_synthetic_github_clickup_case_insensitive():
    item = _synthetic_github_market_item("github:hauptsacheNet/clickup-mcp")
    assert item is not None
    assert item["install_type"] == "git"
    assert item["id"] == "github:hauptsachenet/clickup-mcp"
    assert item["url"] == "https://github.com/hauptsachenet/clickup-mcp"


def test_find_marketplace_item_github_without_network():
    """Wizard passes github: id from search cards — must not require live marketplace."""
    item = _find_marketplace_item("github:hauptsacheNet/clickup-mcp")
    assert item is not None
    assert item["install_type"] == "git"
    assert "clickup-mcp" in item.get("url", "")
