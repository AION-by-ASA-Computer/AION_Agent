"""FTS5 helpers for ltm_notes."""

from __future__ import annotations

import logging
import os
import re
from typing import List, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("aion.memory.mnemos.fts")

_FTS_TOKEN_RE = re.compile(r"[a-zA-Z0-9_\u00c0-\u024f]{2,}")
_QUOTED_PHRASE_RE = re.compile(r'"([^"]{2,80})"')
_BACKTICK_PHRASE_RE = re.compile(r"`([^`]{2,80})`")

_FTS_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "also",
        "answer",
        "being",
        "between",
        "boxed",
        "contain",
        "containing",
        "could",
        "does",
        "each",
        "excluding",
        "final",
        "from",
        "have",
        "into",
        "mark",
        "more",
        "only",
        "order",
        "other",
        "our",
        "phrase",
        "phrases",
        "portal",
        "question",
        "reply",
        "separated",
        "servicenow",
        "short",
        "should",
        "substring",
        "tell",
        "than",
        "that",
        "their",
        "them",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "using",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "within",
        "working",
        "would",
        "your",
    }
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


def _escape_fts_query_v2(q: str, *, max_terms: int = 12) -> Tuple[str, str]:
    """Return (primary_query, fallback_or_query)."""
    if not (q or "").strip():
        return '""', '""'

    phrases = _extract_phrases(q)
    terms = _tokenize_terms(q, phrases=phrases)
    terms.sort(key=_term_score, reverse=True)
    terms = terms[:max_terms]

    phrase_part = " AND ".join(_quote_fts_term(p) for p in phrases[:4])
    term_part = " OR ".join(_quote_fts_term(t) for t in terms)

    if phrase_part and term_part:
        primary = f"({phrase_part}) AND ({term_part})"
    elif phrase_part:
        primary = phrase_part
    elif term_part:
        primary = f"({term_part})"
    else:
        primary = '""'

    or_bits: List[str] = []
    for p in phrases[:4]:
        or_bits.append(_quote_fts_term(p))
    for t in terms:
        or_bits.append(_quote_fts_term(t))
    if not or_bits:
        fallback = '""'
    elif len(or_bits) == 1:
        fallback = or_bits[0]
    else:
        fallback = "(" + " OR ".join(or_bits) + ")"
    return primary, fallback


def _escape_fts_query_legacy(q: str, *, max_terms: int = 12) -> str:
    if not (q or "").strip():
        return '""'
    tokens = _FTS_TOKEN_RE.findall(q)
    if not tokens:
        return '""'
    seen: set[str] = set()
    ordered: list[str] = []
    for tok in sorted(tokens, key=len, reverse=True):
        low = tok.lower()
        if low in seen:
            continue
        seen.add(low)
        ordered.append(tok)
        if len(ordered) >= max_terms:
            break
    quoted = [_quote_fts_term(t) for t in ordered]
    if len(quoted) == 1:
        return quoted[0]
    return "(" + " OR ".join(quoted) + ")"


def _escape_fts_query(q: str, *, max_terms: int = 12) -> str:
    """Build a safe FTS5 query from free text (legacy entry — OR tokens by length)."""
    return _escape_fts_query_legacy(q, max_terms=max_terms)


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
    """Return ordered FTS queries to try (primary then OR fallback)."""
    if os.getenv("AION_MNEMOS_FTS_PHRASE_QUERY", "0") == "1":
        primary, fallback = _escape_fts_query_v2(q, max_terms=max_terms)
        if primary == fallback:
            return [primary] if primary != '""' else []
        return [item for item in (primary, fallback) if item and item != '""']
    legacy = _escape_fts_query_legacy(q, max_terms=max_terms)
    return [legacy] if legacy != '""' else []
