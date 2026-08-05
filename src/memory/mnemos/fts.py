"""FTS5 helpers for ltm_notes."""

from __future__ import annotations

import logging
import re
from typing import List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("aion.memory.mnemos.fts")

_FTS_TOKEN_RE = re.compile(r"[a-zA-Z0-9_\u00c0-\u024f]{2,}")
_QUOTED_PHRASE_RE = re.compile(r'"([^"]{2,80})"')
_BACKTICK_PHRASE_RE = re.compile(r"`([^`]{2,80})`")

_FTS_STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are aren't as at be because
    been before being below between both but by can cannot could couldn't did didn't
    do does doesn't doing don't down during each few for from further had hadn't has
    hasn't have haven't having he he'd he'll he's her here here's hers herself him
    himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself
    let's me more most mustn't my myself no nor not of off on once only or other ought
    our ours ourselves out over own same she she'd she'll she's should shouldn't so some
    such than that that's the their theirs them themselves then there there's these
    they they'd they'll they're they've this those through to too under until up very was
    wasn't we we'd we'll we're we've were weren't what what's when when's where where's
    which while who who's whom why why's with won't would wouldn't you you'd you'll you're
    you've your yours yourself yourselves
    about dopo anche essere stato stata stati state tra fra come dove quando perche perché
    quale quali quello quella quelli quelle questo questa questi queste sono era erano
    sono stato stata stati state con senza sopra sotto tutti tutte tutto tutta molto
    poco piu più meno gia già ancora solo sola soli sole loro nostro nostra nostri nostre
    vostro vostra vostri vostre loro esso essa essi esse lui lei noi voi
    """.split()
)


async def ensure_fts_table(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS ltm_notes_fts USING fts5(
                content,
                tenant_id UNINDEXED,
                scope_type UNINDEXED,
                scope_key UNINDEXED,
                note_id UNINDEXED,
                tokenize='unicode61'
            )
            """
        )
    )


async def fts_insert(
    session: AsyncSession,
    *,
    note_id: int,
    tenant_id: str,
    scope_type: str,
    scope_key: str,
    content: str,
) -> None:
    await ensure_fts_table(session)
    await session.execute(
        text(
            """
            INSERT INTO ltm_notes_fts(rowid, content, tenant_id, scope_type, scope_key, note_id)
            VALUES (:rowid, :content, :tenant_id, :scope_type, :scope_key, :note_id)
            """
        ),
        {
            "rowid": note_id,
            "content": content,
            "tenant_id": tenant_id,
            "scope_type": scope_type,
            "scope_key": scope_key,
            "note_id": str(note_id),
        },
    )


async def fts_delete(session: AsyncSession, note_id: int) -> None:
    await session.execute(
        text("DELETE FROM ltm_notes_fts WHERE rowid = :rowid"),
        {"rowid": note_id},
    )


def _quote_fts_term(term: str) -> str:
    return f'"{term.replace(chr(34), chr(34) * 2)}"'


def _extract_phrases(q: str) -> List[str]:
    phrases: List[str] = []
    seen: set[str] = set()
    for pattern in (_QUOTED_PHRASE_RE, _BACKTICK_PHRASE_RE):
        for match in pattern.finditer(q or ""):
            phrase = match.group(1).strip()
            key = phrase.lower()
            if len(phrase) < 2 or key in seen:
                continue
            seen.add(key)
            phrases.append(phrase)
    return phrases


def _tokenize_terms(q: str, *, phrases: List[str]) -> List[str]:
    phrase_low = {p.lower() for p in phrases}
    stripped = q or ""
    for phrase in phrases:
        stripped = stripped.replace(f'"{phrase}"', " ")
        stripped = stripped.replace(f"`{phrase}`", " ")
    tokens = _FTS_TOKEN_RE.findall(stripped)
    seen: set[str] = set()
    ordered: List[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in _FTS_STOPWORDS or low in phrase_low or low in seen:
            continue
        seen.add(low)
        ordered.append(tok)
    return ordered


def _term_score(term: str) -> float:
    """Higher = more discriminative (prefer short tokens, numbers, caps)."""
    score = 1.0
    if term.isdigit() or any(ch.isdigit() for ch in term):
        score += 4.0
    if len(term) <= 4:
        score += 3.0
    elif len(term) <= 6:
        score += 1.5
    if term[0].isupper() and term.lower() != term:
        score += 2.0
    score -= len(term) * 0.05
    return score


def build_discriminative_query(q: str, *, max_terms: int = 12) -> str:
    """Strip boilerplate and return space-separated discriminative terms for recall."""
    if not (q or "").strip():
        return ""
    phrases = _extract_phrases(q)
    terms = _tokenize_terms(q, phrases=phrases)
    terms.sort(key=_term_score, reverse=True)
    parts: List[str] = []
    seen: set[str] = set()
    for item in phrases + terms[:max_terms]:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(item)
    return " ".join(parts) if parts else (q or "").strip()


def build_fts_queries(q: str, *, max_terms: int = 12) -> List[str]:
    """Return ordered FTS queries: phrase AND, top-term AND, then OR fallback."""
    if not (q or "").strip():
        return []

    phrases = _extract_phrases(q)
    terms = _tokenize_terms(q, phrases=phrases)
    terms.sort(key=_term_score, reverse=True)
    terms = terms[:max_terms]

    queries: List[str] = []

    if phrases:
        phrase_part = " AND ".join(_quote_fts_term(p) for p in phrases[:4])
        if phrase_part:
            queries.append(phrase_part)

    if len(terms) >= 2:
        top_and = " AND ".join(_quote_fts_term(t) for t in terms[:3])
        if top_and not in queries:
            queries.append(top_and)

    or_bits: List[str] = []
    for p in phrases[:4]:
        or_bits.append(_quote_fts_term(p))
    for t in terms:
        or_bits.append(_quote_fts_term(t))
    if or_bits:
        if len(or_bits) == 1:
            or_query = or_bits[0]
        else:
            or_query = "(" + " OR ".join(or_bits) + ")"
        if or_query not in queries:
            queries.append(or_query)

    return queries
