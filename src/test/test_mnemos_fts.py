"""FTS5 query building and term scoring for Mnemos recall."""

from src.memory.mnemos.fts import build_discriminative_query, build_fts_queries


def test_build_fts_queries_lme_style_question():
    q = (
        "I am working with our ServiceNow portal. On the Incidents list page, when I open the "
        '"Filters" dropdown, excluding "Edit personal filters" — which filter option labels '
        'contain the substring "Incident"? Mark your final answer in \\boxed{}.'
    )
    queries = build_fts_queries(q)
    assert len(queries) >= 1
    assert any("Incident" in q_str for q_str in queries)
    assert any("Filters" in q_str for q_str in queries)


def test_build_fts_queries_empty():
    assert build_fts_queries("") == []
    assert build_fts_queries("...") == []


def test_build_discriminative_query_limits_terms():
    q = " ".join(f"word{i}" for i in range(50))
    disc = build_discriminative_query(q, max_terms=5)
    terms = disc.split()
    assert len(terms) <= 5
