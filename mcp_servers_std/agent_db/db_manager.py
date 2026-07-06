# mcp_servers/agent_db/db_manager.py
import sqlite3
import os
from typing import Optional, List, Dict, Any
from .safety import validate_name
from .type_mapper import map_aion_to_sqlite


class AgentDBManager:
    def __init__(self, root_dir: str = "data/agent_dbs"):
        self.root_dir = os.path.abspath(root_dir)
        if not os.path.exists(root_dir):
            os.makedirs(self.root_dir, exist_ok=True)

    def get_db_path(self, tenant_id: str, user_id: str) -> str:
        tenant_dir = os.path.join(self.root_dir, tenant_id)
        if not os.path.exists(tenant_dir):
            os.makedirs(tenant_dir, exist_ok=True)
        return os.path.join(tenant_dir, f"{user_id}.db")

    def get_connection(
        self, tenant_id: str, user_id: str, readonly: bool = False
    ) -> sqlite3.Connection:
        db_path = self.get_db_path(tenant_id, user_id)
        if readonly:
            if not os.path.exists(db_path):
                raise FileNotFoundError(
                    f"No Agent DB file for tenant={tenant_id!r} user={user_id!r}. "
                    "Create tables first or use write tools."
                )
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(db_path)

        conn.row_factory = sqlite3.Row
        return conn

    def initialize_system_tables(self, conn: sqlite3.Connection):
        """Initializes AION system tables in the user DB."""
        cursor = conn.cursor()

        # Registry
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS _aion_schema_registry (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_name     TEXT NOT NULL,
            table_name      TEXT NOT NULL,
            physical_name   TEXT NOT NULL,
            description     TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            row_count       INTEGER NOT NULL DEFAULT 0,
            archived_at     TEXT,
            UNIQUE(schema_name, table_name)
        );
        """)

        # Columns
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS _aion_schema_columns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_name     TEXT NOT NULL,
            table_name      TEXT NOT NULL,
            column_name     TEXT NOT NULL,
            physical_name   TEXT NOT NULL,
            column_type     TEXT NOT NULL,
            nullable        INTEGER NOT NULL DEFAULT 1,
            default_value   TEXT,
            description     TEXT,
            ordinal_pos     INTEGER NOT NULL,
            is_system       INTEGER NOT NULL DEFAULT 0,
            UNIQUE(schema_name, table_name, column_name)
        );
        """)

        # History
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS _aion_schema_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_name     TEXT,
            table_name      TEXT,
            operation       TEXT NOT NULL,
            payload         TEXT,
            conversation_id TEXT,
            rows_affected   INTEGER,
            performed_at    TEXT NOT NULL DEFAULT (datetime('now')),
            rollback_sql    TEXT
        );
        """)

        # Views
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS _aion_views_registry (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_name     TEXT NOT NULL,
            view_name       TEXT NOT NULL,
            physical_name   TEXT NOT NULL,
            description     TEXT,
            select_sql      TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(schema_name, view_name)
        );
        """)

        conn.commit()

    def get_physical_table_name(self, schema_name: str, table_name: str) -> str:
        return f"{schema_name}__{table_name}"
