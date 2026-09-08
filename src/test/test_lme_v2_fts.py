"""Tests for Mnemos FTS phrase-aware query building."""

from __future__ import annotations


from src.memory.mnemos.fts import (
    build_discriminative_query,
    build_fts_queries,
    _escape_fts_query_v2,
)


def test_discriminative_query_keeps_quoted_phrase_and_short_tokens():
    q = (
        'On the Incidents list page, when I open the "Filters" dropdown, '
        'which labels contain "Incident"? Mark your final answer in \\boxed{}.'
    )
    boosted = build_discriminative_query(q)
    assert "Filters" in boosted
    assert "Incident" in boosted
    assert "working" not in boosted.lower()
    assert "portal" not in boosted.lower()


def test_fts_v2_primary_uses_phrase_and_terms(monkeypatch):
    monkeypatch.setenv("AION_MNEMOS_FTS_PHRASE_QUERY", "1")
    primary, fallback = _escape_fts_query_v2('"Incident Mobile" Dell XPS 300')
    assert '"Incident Mobile"' in primary
    assert "AND" in primary
    assert '"300"' in primary or "300" in primary
    assert " OR " in fallback


def test_build_fts_queries_legacy_default(monkeypatch):
    monkeypatch.delenv("AION_MNEMOS_FTS_PHRASE_QUERY", raising=False)
    queries = build_fts_queries("ServiceNow Incident Mobile")
    assert len(queries) == 1
    assert "OR" in queries[0]


def test_build_fts_queries_phrase_mode(monkeypatch):
    monkeypatch.setenv("AION_MNEMOS_FTS_PHRASE_QUERY", "1")
    queries = build_fts_queries('"Incident Mobile" ServiceNow portal working')
    assert len(queries) >= 1
    assert '"Incident Mobile"' in queries[0]
