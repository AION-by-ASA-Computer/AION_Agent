"""TOON encoding for web tool results."""

from __future__ import annotations

import json

from src.runtime.toon_encode import encode_toon, format_web_fetch_toon, format_web_search_toon, parse_web_tool_payload


def test_web_search_toon_tabular_results():
    data = {
        "query": "mondiale 2026",
        "provider_used": "tavily",
        "results": [
            {
                "title": "FIFA World Cup",
                "url": "https://example.com/a",
                "snippet": "Group stage results",
                "provider": "tavily",
            },
            {
                "title": "Schedule",
                "url": "https://example.com/b",
                "snippet": "Match list",
                "provider": "tavily",
            },
        ],
    }
    out = format_web_search_toon(data)
    assert out.startswith("```toon")
    assert "results[2]" in out
    assert "FIFA World Cup" in out
    assert '"query"' not in out  # leaner than JSON


def test_web_fetch_toon_multiline_text():
    data = {
        "url": "https://en.wikipedia.org/wiki/2022_FIFA_World_Cup",
        "mode": "trafilatura",
        "chars": 42,
        "text": "Line one\nLine two",
    }
    out = format_web_fetch_toon(data)
    assert "trafilatura" in out
    assert "Line one" in out


def test_encode_toon_roundtrip_shape():
    payload = {"items": [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Linus"}]}
    text = encode_toon(payload)
    assert "items[2]{id,name}" in text
    assert "1,Ada" in text


def test_parse_web_tool_payload_search_toon():
    raw = format_web_search_toon(
        {
            "query": "test",
            "provider_used": "tavily",
            "results": [
                {
                    "title": "A",
                    "url": "https://a.org",
                    "snippet": "snippet",
                    "provider": "tavily",
                }
            ],
        }
    )
    data = parse_web_tool_payload(raw, "web_search")
    assert data is not None
    assert data["query"] == "test"
    assert len(data["results"]) == 1


def test_parse_web_tool_payload_fetch_toon():
    raw = format_web_fetch_toon(
        {
            "url": "https://example.com",
            "mode": "httpx_raw",
            "text": "hello",
        }
    )
    data = parse_web_tool_payload(raw, "web_fetch_page")
    assert data is not None
    assert data["url"] == "https://example.com"
    assert data["text"] == "hello"
