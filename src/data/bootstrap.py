"""Create tables + FTS5 for unified DB."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .models import Base

logger = logging.getLogger("aion.data.bootstrap")


async def _sqlite_table_exists(conn, table: str) -> bool:
    r = await conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:t LIMIT 1"),
        {"t": table},
    )
    return r.first() is not None


async def _sqlite_column_names(conn, table: str) -> set[str]:
    info = await conn.execute(text(f"PRAGMA table_info({table})"))
    return {row[1] for row in info.fetchall()}


async def _sqlite_add_column_if_missing(
    conn, table: str, column: str, col_ddl: str
) -> None:
    cols = await _sqlite_column_names(conn, table)
    if column in cols:
        return
    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_ddl}"))
    logger.info("SQLite schema patch: added %s.%s", table, column)


async def _sqlite_create_index_if_missing(conn, index_name: str, ddl: str) -> None:
    r = await conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='index' AND name=:n LIMIT 1"),
        {"n": index_name},
    )
    if r.first() is not None:
        return
    await conn.execute(text(ddl))
    logger.info("SQLite schema patch: created index %s", index_name)


async def _patch_sqlite_columns(engine: AsyncEngine, conn) -> None:
    """Aggiunge colonne mancanti su DB creati prima di un aggiornamento ORM (create_all non altera)."""
    if engine.dialect.name != "sqlite":
        return

    # feedbacks.step_id (storico)
    if await _sqlite_table_exists(conn, "feedbacks"):
        await _sqlite_add_column_if_missing(
            conn, "feedbacks", "step_id", "step_id VARCHAR(64)"
        )

    # users.roles + users.must_change_password (introdotti con la migration
    # d1a23b4f0001). Necessario quando alembic ha "stampato" un DB
    # pre-esistente senza eseguire la migration (vedi
    # src/data/migrations.py:_needs_stamp_baseline).
    if await _sqlite_table_exists(conn, "users"):
        cols = await _sqlite_column_names(conn, "users")
        if "roles" not in cols:
            await conn.execute(
                text("ALTER TABLE users ADD COLUMN roles TEXT NOT NULL DEFAULT '[]'")
            )
            logger.info("SQLite schema patch: added users.roles")
        if "must_change_password" not in cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            logger.info("SQLite schema patch: added users.must_change_password")

    # Observability + timeline columns (migrate_v3 / g3h4i5j6k007). Skipped when
    # alembic stamp head marks a legacy DB as up-to-date without running migrations.
    if await _sqlite_table_exists(conn, "messages"):
        await _sqlite_add_column_if_missing(
            conn, "messages", "trace_id", "trace_id VARCHAR(64)"
        )
        await _sqlite_add_column_if_missing(
            conn, "messages", "timeline_json", "timeline_json TEXT"
        )
        await _sqlite_add_column_if_missing(
            conn, "messages", "metadata_json", "metadata_json TEXT"
        )
        await _sqlite_create_index_if_missing(
            conn,
            "idx_messages_trace",
            "CREATE INDEX IF NOT EXISTS idx_messages_trace ON messages(trace_id)",
        )
    if await _sqlite_table_exists(conn, "steps"):
        await _sqlite_add_column_if_missing(
            conn, "steps", "trace_id", "trace_id VARCHAR(64)"
        )
        await _sqlite_create_index_if_missing(
            conn,
            "idx_steps_trace",
            "CREATE INDEX IF NOT EXISTS idx_steps_trace ON steps(trace_id)",
        )
    if await _sqlite_table_exists(conn, "audit_log"):
        await _sqlite_add_column_if_missing(
            conn, "audit_log", "trace_id", "trace_id VARCHAR(64)"
        )
        await _sqlite_create_index_if_missing(
            conn,
            "idx_audit_log_trace",
            "CREATE INDEX IF NOT EXISTS idx_audit_log_trace ON audit_log(trace_id)",
        )

    # scheduled_jobs.sql_query_project (m4n5o6p014). create_all() does not ALTER
    # existing tables; legacy DBs can have scheduled_jobs without this column while
    # alembic is blocked on k2l3m4n012 (llm_providers already from create_all).
    if await _sqlite_table_exists(conn, "scheduled_jobs"):
        await _sqlite_add_column_if_missing(
            conn,
            "scheduled_jobs",
            "sql_query_project",
            "sql_query_project VARCHAR(128)",
        )


async def patch_sqlite_schema_drift(engine: AsyncEngine) -> None:
    """Idempotent SQLite column/index patches (safe after alembic stamp head)."""
    if engine.dialect.name != "sqlite":
        return
    async with engine.begin() as conn:
        await _patch_sqlite_columns(engine, conn)


# Allineato a ``Message`` in ``models.py`` (fts_rowid = chiave FTS5, id = uuid string).
_MESSAGES_TABLE_SQL = """
CREATE TABLE messages (
    fts_rowid INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    id VARCHAR(64) NOT NULL,
    conversation_id VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    seq INTEGER NOT NULL,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    reasoning TEXT,
    tool_name VARCHAR(256),
    tool_call_id VARCHAR(128),
    tokens_in INTEGER,
    tokens_out INTEGER,
    finish_reason VARCHAR(64),
    promoted_to_ltm INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    profile_name VARCHAR(256) NOT NULL DEFAULT 'default',
    UNIQUE (id),
    UNIQUE (conversation_id, seq),
    FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);
"""

# Prefisso deterministico per id messaggio migrati da INTEGER legacy (evita collisioni con uuid7).
_MSG_LEGACY_SQL_PREFIX = "aionm-"


async def _migrate_sqlite_messages_legacy_to_fts_rowid(
    engine: AsyncEngine, conn
) -> bool:
    """DB unificato vecchio: ``messages.id`` INTEGER PK + FTS ``content_rowid=id`` → schema ORM attuale.

    Returns True se è stata eseguita una migrazione (serve rebuild FTS5).
    """
    if engine.dialect.name != "sqlite":
        return False
    r = await conn.execute(
        text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages' LIMIT 1"
        )
    )
    if r.first() is None:
        return False
    info = await conn.execute(text("PRAGMA table_info(messages)"))
    rows = info.fetchall()
    col_names = {row[1] for row in rows}
    if "fts_rowid" in col_names:
        return False
    id_row = next((row for row in rows if row[1] == "id"), None)
    if id_row is None:
        return False
    id_type = (id_row[2] or "").upper()
    if "INT" not in id_type:
        logger.warning(
            "SQLite messages migration: tipo colonna id inatteso (%s), skip", id_type
        )
        return False

    logger.info(
        "SQLite messages migration: INTEGER id → fts_rowid + id stringa (%s…), rebuild FTS5",
        _MSG_LEGACY_SQL_PREFIX,
    )
    await conn.execute(text("PRAGMA foreign_keys=OFF"))
    for trig in ("messages_ai", "messages_ad", "messages_au"):
        await conn.execute(text(f"DROP TRIGGER IF EXISTS {trig}"))
    await conn.execute(text("DROP TABLE IF EXISTS messages_fts"))
    await conn.execute(text("ALTER TABLE messages RENAME TO messages_legacy"))
    await conn.execute(text(_MESSAGES_TABLE_SQL))
    await conn.execute(
        text(
            """
            INSERT INTO messages (
                id, conversation_id, tenant_id, seq, role, content, reasoning,
                tool_name, tool_call_id, tokens_in, tokens_out, finish_reason,
                promoted_to_ltm, profile_name, created_at
            )
            SELECT
                :pfx || CAST(id AS TEXT),
                conversation_id, tenant_id, seq, role, content, reasoning,
                tool_name, tool_call_id, tokens_in, tokens_out, finish_reason,
                promoted_to_ltm, profile_name, created_at
            FROM messages_legacy
            """
        ),
        {"pfx": _MSG_LEGACY_SQL_PREFIX},
    )
    await conn.execute(
        text(
            "UPDATE attachments SET message_id = :pfx || CAST(message_id AS TEXT) "
            "WHERE message_id IS NOT NULL"
        ),
        {"pfx": _MSG_LEGACY_SQL_PREFIX},
    )
    await conn.execute(
        text(
            "UPDATE steps SET message_id = :pfx || CAST(message_id AS TEXT) "
            "WHERE message_id IS NOT NULL"
        ),
        {"pfx": _MSG_LEGACY_SQL_PREFIX},
    )
    await conn.execute(
        text(
            "UPDATE feedbacks SET message_id = :pfx || CAST(message_id AS TEXT) "
            "WHERE message_id IS NOT NULL"
        ),
        {"pfx": _MSG_LEGACY_SQL_PREFIX},
    )
    await conn.execute(text("DROP TABLE messages_legacy"))
    await conn.execute(text("PRAGMA foreign_keys=ON"))
    return True


_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    conversation_id UNINDEXED,
    tenant_id UNINDEXED,
    role UNINDEXED,
    seq UNINDEXED,
    created_at UNINDEXED,
    content='messages',
    content_rowid='fts_rowid',
    tokenize='unicode61 remove_diacritics 2'
);
"""


async def ensure_bootstrap_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        migrated_messages = await _migrate_sqlite_messages_legacy_to_fts_rowid(
            engine, conn
        )
        await _patch_sqlite_columns(engine, conn)
        try:
            await conn.execute(text(_FTS_DDL))
            for stmt in (
                """CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, conversation_id, tenant_id, role, seq, created_at)
    VALUES (new.fts_rowid, new.content, new.conversation_id, new.tenant_id, new.role, new.seq, new.created_at);
END""",
                """CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.fts_rowid, old.content);
END""",
                """CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.fts_rowid, old.content);
    INSERT INTO messages_fts(rowid, content, conversation_id, tenant_id, role, seq, created_at)
    VALUES (new.fts_rowid, new.content, new.conversation_id, new.tenant_id, new.role, new.seq, new.created_at);
END""",
            ):
                await conn.execute(text(stmt))
            if migrated_messages:
                await conn.execute(
                    text("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
                )
                logger.info("FTS5: rebuild dopo migrazione messages")
        except Exception as e:
            logger.warning("FTS5 bootstrap skipped: %s", e)
        try:
            await conn.execute(
                text(
                    "INSERT OR IGNORE INTO tenants (id, name, metadata) "
                    "VALUES ('default', 'Default Tenant', '{}')"
                )
            )
        except Exception as e:
            logger.debug("tenant seed: %s", e)
