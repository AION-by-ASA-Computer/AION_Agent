"""TOON parse + web_search truncation."""

from __future__ import annotations

from src.runtime.toon_encode import format_web_search_toon, parse_web_search_toon
from src.runtime.turn_compaction import truncate_tool_result


def test_parse_web_search_toon_multiple_rows():
    raw = """```toon
query: "mondiali 2026"
provider_used: tavily
results[3]{title,url,snippet,provider}:
  A,https://a.org,snippet a,tavily
  B,https://b.org,snippet b,tavily
  C,https://c.org,snippet c,tavily
```"""
    data = parse_web_search_toon(raw)
    assert data is not None
    assert data["query"] == "mondiali 2026"
    assert len(data["results"]) == 3


def test_truncate_web_search_toon_keeps_multiple_results():
    rows = [
        {
            "title": f"Title {i}",
            "url": f"https://example{i}.org/path",
            "snippet": "x" * 400,
            "provider": "tavily",
        }
        for i in range(8)
    ]
    raw = format_web_search_toon(
        {"query": "q", "provider_used": "tavily", "results": rows}
    )
    out = truncate_tool_result(raw, tool_name="web_search")
    parsed = parse_web_search_toon(out)
    assert parsed is not None
    assert len(parsed["results"]) >= 2


def test_format_web_search_toon_collapses_multiline_snippets():
    raw = format_web_search_toon(
        {
            "query": "q",
            "provider_used": "tavily",
            "results": [
                {
                    "title": "Group A",
                    "url": "https://en.wikipedia.org/wiki/Group_A",
                    "snippet": "| W | D |\n --- \n| 1 | 2 |",
                    "provider": "tavily",
                }
            ],
        }
    )
    assert "\n ---" not in raw
    parsed = parse_web_search_toon(raw)
    assert parsed is not None
    assert len(parsed["results"]) == 1
    assert "| W | D |" in parsed["results"][0]["snippet"]


def test_parse_web_search_toon_multiline_quoted_snippets():
    raw = """```toon
query: group a
provider_used: tavily
results[2]{title,url,snippet,provider}:
  A,https://a.org,"line1
line2",tavily
  B,https://b.org,snippet b,tavily
```"""
    data = parse_web_search_toon(raw)
    assert data is not None
    assert len(data["results"]) == 2
    assert data["results"][0]["url"] == "https://a.org"


def test_web_search_toon_round_trip_with_escaped_quotes():
    """Snippets with quotes/backslashes keep every column in place after a round trip.

    Regression: the encoder writes \\" inside quoted cells but the row parser only
    understood "", so the columns shifted and page text ended up in ``provider``
    (shown as the Deep Research report's "Search" statistic).
    """
    rows = [
        {
            "title": 'Rust (programming language) - "Wikipedia"',
            "url": "https://en.wikipedia.org/wiki/Rust",
            "snippet": 'History [edit "Edit section"] path C:\rust, then "quotes", commas',
            "provider": "tavily",
        },
        {
            "title": "Second",
            "url": "https://b.org",
            "snippet": "plain snippet",
            "provider": "tavily",
        },
    ]
    raw = format_web_search_toon(
        {"query": "rust", "provider_used": "tavily", "results": rows}
    )
    data = parse_web_search_toon(raw)
    assert data is not None
    assert [r["provider"] for r in data["results"]] == ["tavily", "tavily"]
    assert [r["url"] for r in data["results"]] == [r["url"] for r in rows]
    assert data["results"][0]["title"] == rows[0]["title"]
    assert '"Edit section"' in data["results"][0]["snippet"]
