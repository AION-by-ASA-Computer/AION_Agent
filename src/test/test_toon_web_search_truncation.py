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
