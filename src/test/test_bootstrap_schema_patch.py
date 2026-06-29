"""SQLite schema drift patches for legacy unified DBs."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.bootstrap import patch_sqlite_schema_drift
from src.data.engine import init_engine


@pytest.mark.anyio
async def test_patch_adds_trace_id_and_timeline_json_to_legacy_messages():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE messages (
                fts_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                id VARCHAR(64) NOT NULL,
                conversation_id VARCHAR(64) NOT NULL,
                tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
                seq INTEGER NOT NULL,
                role VARCHAR(32) NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                profile_name VARCHAR(256) DEFAULT 'default'
            )
            """
        )
        conn.commit()
        conn.close()

        os.environ["AION_DB_URL"] = f"sqlite+aiosqlite:///{db_path}"
        try:
            eng = init_engine()
            await patch_sqlite_schema_drift(eng)
        finally:
            os.environ.pop("AION_DB_URL", None)

        verify = sqlite3.connect(db_path)
        cols = {row[1] for row in verify.execute("PRAGMA table_info(messages)")}
        verify.close()

        assert "trace_id" in cols
        assert "timeline_json" in cols
