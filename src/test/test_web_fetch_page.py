"""Generic web_fetch_page extraction (no site-specific handlers)."""

from __future__ import annotations

import builtins
import json

import pytest

from src.runtime.native_tools import web_providers as wp


def test_web_fetch_max_chars_higher_when_offload_enabled(monkeypatch):
    monkeypatch.setenv("AION_WEB_FETCH_MAX_CHARS", "24000")
    monkeypatch.setenv("AION_WEB_FETCH_MAX_BYTES", "1500000")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    assert wp._web_fetch_max_chars() >= 24000
    assert wp._web_fetch_max_chars() > 24000


def test_web_fetch_max_chars_respects_explicit_offload_cap(monkeypatch):
    monkeypatch.setenv("AION_WEB_FETCH_MAX_CHARS", "24000")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    monkeypatch.setenv("AION_WEB_FETCH_OFFLOAD_MAX_CHARS", "180000")
    assert wp._web_fetch_max_chars() == 180000


def test_web_fetch_no_wikipedia_api_shortcut(monkeypatch):
    requested_urls: list[str] = []

    def fake_extract(html: str, *, url: str, max_chars: int):
        requested_urls.append(url)
        return (
            "Mexico 2 - 0 South Africa. Full match list from rendered HTML.",
            "trafilatura",
        )

    class _Resp:
        content = b"<html><body>ignored</body></html>"
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, **kwargs):
            requested_urls.append(url)
            return _Resp()

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "scrapling.fetchers" or (
            fromlist and "scrapling.fetchers" in str(fromlist)
        ):
            raise ImportError("scrapling unavailable in test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(wp, "_extract_main_text", fake_extract)
    monkeypatch.setattr(wp.httpx, "Client", _Client)
    monkeypatch.setenv("AION_TOOL_RESULT_FORMAT", "json")

    raw = wp.run_web_fetch_page(
        "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_Group_A"
    )
    data = json.loads(raw)
    assert data.get("error") is None
    assert "Mexico 2" in data.get("text", "")
    assert "wikipedia" not in str(data.get("mode", ""))
    assert not any("w/api.php" in u for u in requested_urls)
    assert any("wikipedia.org/wiki/" in u for u in requested_urls)


@pytest.mark.integration
def test_web_fetch_wikipedia_live_no_wiki_api_mode(monkeypatch):
    monkeypatch.setenv("AION_TOOL_RESULT_FORMAT", "json")
    raw = wp.run_web_fetch_page(
        "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_Group_A"
    )
    data = json.loads(raw)
    assert data.get("error") is None
    assert data["chars"] > 3000
    assert "wikipedia" not in str(data.get("mode", ""))
