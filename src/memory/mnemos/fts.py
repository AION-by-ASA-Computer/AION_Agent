"""FTS5 helpers for ltm_notes."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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


def _escape_fts_query(q: str) -> str:
    """Basic FTS5 query sanitization: quote tokens with special chars."""
    parts = []
    for tok in (q or "").split():
        tok = tok.strip()
        if not tok:
            continue
        if any(c in tok for c in ('"', "'", ":", "*", "(", ")", "-", "^")):
            tok = tok.replace('"', '""')
            parts.append(f'"{tok}"')
        else:
            parts.append(tok)
    return " ".join(parts) or '""'
