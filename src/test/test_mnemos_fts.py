"""FTS5 query sanitization for Mnemos recall."""

from src.memory.mnemos.fts import _escape_fts_query


def test_escape_lme_style_question():
    q = (
        'I am working with our ServiceNow portal. On the Incidents list page, when I open the '
        '"Filters" dropdown, excluding "Edit personal filters" — which filter option labels '
        'contain the substring "Incident"? Mark your final answer in \\boxed{}.'
    )
    escaped = _escape_fts_query(q)
    assert "." not in escaped or '"' in escaped
    assert "OR" in escaped or escaped.startswith('"')
    assert "Filters" in escaped or "filters" in escaped.lower()
    assert "\\" not in escaped


def test_escape_empty():
    assert _escape_fts_query("") == '""'
    assert _escape_fts_query("...") == '""'


def test_escape_limits_terms():
    q = " ".join(f"word{i}" for i in range(50))
    escaped = _escape_fts_query(q, max_terms=5)
    assert escaped.count("OR") <= 4
