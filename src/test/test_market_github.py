"""Tests for manual GitHub marketplace install helpers."""

from src.marketplaces.market_adapters import build_github_market_item, parse_github_url


def test_parse_github_url_https() -> None:
    pair = parse_github_url("https://github.com/ai-zerolab/mcp-email-server")
    assert pair == ("ai-zerolab", "mcp-email-server")


def test_build_github_market_item() -> None:
    item = build_github_market_item("https://github.com/ai-zerolab/mcp-email-server.git")
    assert item is not None
    assert item["id"] == "github:ai-zerolab/mcp-email-server"
    assert item["install_type"] == "git"
    assert "github.com/ai-zerolab/mcp-email-server" in item["url"]
