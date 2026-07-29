"""web_search query normalization (site: operator)."""

from __future__ import annotations

from src.runtime.native_tools.web_providers import _normalize_web_search_query


def test_site_operator_parsed():
    q, domains, err = _normalize_web_search_query(
        "site:it.wikipedia.org campionato mondiale 2026 girone A"
    )
    assert err is None
    assert domains == ["it.wikipedia.org"]
    assert q == "campionato mondiale 2026 girone A"


def test_site_operator_missing_terms():
    _q, domains, err = _normalize_web_search_query("site:it.wikipedia.org \\")
    assert err == "site_operator_missing_terms"
    assert domains == ["it.wikipedia.org"]


def test_plain_query_unchanged():
    q, domains, err = _normalize_web_search_query("Mondiale 2026 Wikipedia")
    assert err is None
    assert domains == []
    assert q == "Mondiale 2026 Wikipedia"
