"""Tests for LME-V2 benchmark recall query boosting."""

from __future__ import annotations

from src.benchmarks.longmemeval_v2.query import build_benchmark_recall_query


def test_recall_query_extracts_quoted_and_product_terms():
    q = (
        'On the Incidents list page, when I open the "Filters" dropdown, '
        "which filter option labels contain the substring \"Incident\"?"
    )
    boosted = build_benchmark_recall_query(q)
    assert "Filters" in boosted
    assert "dropdown" in boosted
    assert "Incident" in boosted


def test_recall_query_includes_dell_xps_ssd():
    q = (
        "When we order a Dell XPS as the developer laptop, "
        "what is the extra dollar amount if we choose the largest SSD option?"
    )
    boosted = build_benchmark_recall_query(q)
    assert "Dell" in boosted
    assert "XPS" in boosted
    assert "SSD" in boosted
    assert "laptop" in boosted.lower()
