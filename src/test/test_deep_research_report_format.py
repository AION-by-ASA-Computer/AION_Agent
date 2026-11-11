"""Deep Research report format: category detection and the "Search" statistic.

Regressions from a real run on a Michael Jordan biography:
- the classifier answer was matched by substring against the category list, so
  the report was forced into the ``product`` layout (price table and "Prezzo
  indicativo" under every section);
- a mis-parsed search row put page text into ``provider``, and the report
  header printed ~10k characters of English text as the "Search" statistic.
"""

from __future__ import annotations

import pytest

from src.research import deep_research as dr


@pytest.mark.parametrize(
    "reply, expected",
    [
        ("product", "product"),
        ("Comparison.", "comparison"),
        ("**howto**", "howto"),
        ("general", None),
        ("General — this is a biography", None),
        ("not product, general", None),
        ("The category is factcheck", "factcheck"),
        ("product or comparison", None),
        ("", None),
        (None, None),
        ("productivity", None),
    ],
)
def test_parse_category_label(reply, expected):
    """Only a clear single category selects a special layout; anything else is generic."""
    assert dr._parse_category_label(reply) == expected


@pytest.mark.anyio
async def test_search_stat_keeps_only_provider_ids(monkeypatch):
    """A provider value that is not a short id is recorded as 'aion', never as page text."""
    rows = [
        {
            "url": "https://a.org",
            "title": "A",
            "snippet": "s",
            "provider": "Jordan admitted he was initially reluctant, tavily",
        }
    ]

    async def _fake_search(_query, max_results=10):
        return rows

    monkeypatch.setattr(dr, "search_web", _fake_search)
    researcher = dr.DeepResearcher(llm_endpoint="", llm_model="m")
    await researcher._search("q")
    rows[0]["provider"] = "Tavily"
    await researcher._search("q2")
    assert researcher.providers_used == ["aion", "tavily"]
    assert researcher.get_stats()["Search"] == "aion, tavily"
