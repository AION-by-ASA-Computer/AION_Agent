"""SQLite schema drift patches for legacy unified DBs."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.bootstrap import patch_sqlite_schema_drift
from src.data import engine as engine_mod
from src.data.engine import init_engine


@pytest.fixture(autouse=True)
def _isolated_engine(monkeypatch):
    # init_engine e' un singleton di modulo: ogni test usa il proprio DB.
    monkeypatch.setattr(engine_mod, "_engine", None)
    monkeypatch.setattr(engine_mod, "_session_factory", None)


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


@pytest.mark.anyio
async def test_patch_adds_api_key_ownership_and_revokes_legacy_keys():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE users (
                id VARCHAR(64) PRIMARY KEY,
                tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
                identifier VARCHAR(256) NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE api_keys (
                id VARCHAR(64) PRIMARY KEY,
                tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
                name VARCHAR(256) NOT NULL,
                prefix VARCHAR(16) NOT NULL,
                hash VARCHAR(256) NOT NULL,
                scopes TEXT NOT NULL DEFAULT '[]',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME,
                last_used_at DATETIME,
                revoked_at DATETIME
            )
            """
        )
        conn.execute(
            "INSERT INTO api_keys (id, name, prefix, hash) VALUES ('k1', 'old', 'abcdefgh', 'x')"
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
        user_cols = {row[1] for row in verify.execute("PRAGMA table_info(users)")}
        key_cols = {row[1] for row in verify.execute("PRAGMA table_info(api_keys)")}
        indexes = {row[1] for row in verify.execute("PRAGMA index_list(api_keys)")}
        revoked = verify.execute("SELECT revoked_at FROM api_keys WHERE id='k1'").fetchone()[0]
        verify.close()

        assert {"can_create_api_keys", "max_api_keys", "api_key_max_ttl_days"} <= user_cols
        assert "user_id" in key_cols
        assert {"ix_api_keys_user_id", "ux_api_keys_hash"} <= indexes
        assert revoked is not None
