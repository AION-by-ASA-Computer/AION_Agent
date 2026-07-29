"""Deep research search bridge must parse TOON tool payloads."""

from __future__ import annotations

from src.research.search_bridge import (
    _parse_search_results,
    _parse_web_fetch_payload,
)
from src.runtime.toon_encode import format_web_fetch_toon, format_web_search_toon


def test_parse_search_results_toon_payload():
    raw = format_web_search_toon(
        {
            "query": "mondiali 2026",
            "provider_used": "tavily",
            "results": [
                {
                    "title": "FIFA World Cup",
                    "url": "https://example.com/a",
                    "snippet": "Group stage results",
                    "provider": "tavily",
                }
            ],
        }
    )
    rows = _parse_search_results(raw)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com/a"
    assert rows[0]["provider"] == "tavily"


def test_parse_search_results_json_payload():
    raw = (
        '{"query":"test","provider_used":"tavily","results":'
        '[{"title":"A","url":"https://a.org","snippet":"s","provider":"tavily"}]}'
    )
    rows = _parse_search_results(raw)
    assert len(rows) == 1
    assert rows[0]["title"] == "A"


def test_parse_web_fetch_payload_toon_multiline():
    raw = format_web_fetch_toon(
        {
            "url": "https://example.com/page",
            "mode": "trafilatura",
            "chars": 17,
            "text": "Line one\nLine two",
        }
    )
    data = _parse_web_fetch_payload(raw)
    assert data is not None
    assert data["url"] == "https://example.com/page"
    assert data["text"] == "Line one\nLine two"
