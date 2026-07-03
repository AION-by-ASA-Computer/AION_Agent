# mcp_servers/agent_db/schema_registry.py
import sqlite3
from typing import List, Dict, Any, Optional


class SchemaRegistry:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def register_table(
        self, schema_name: str, table_name: str, physical_name: str, description: str
    ):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO _aion_schema_registry (schema_name, table_name, physical_name, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(schema_name, table_name) DO UPDATE SET
                physical_name = excluded.physical_name,
                description = excluded.description,
                updated_at = datetime('now'),
                archived_at = NULL
        """,
            (schema_name, table_name, physical_name, description),
        )
        self.conn.commit()

    def register_columns(
        self, schema_name: str, table_name: str, columns: List[Dict[str, Any]]
    ):
        cursor = self.conn.cursor()
        # Clean existing columns for this table to avoid duplicates or stale data
        cursor.execute(
            "DELETE FROM _aion_schema_columns WHERE schema_name = ? AND table_name = ?",
            (schema_name, table_name),
        )

        for i, col in enumerate(columns):
            cursor.execute(
                """
                INSERT INTO _aion_schema_columns 
                (schema_name, table_name, column_name, physical_name, column_type, nullable, default_value, description, ordinal_pos, is_system)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    schema_name,
                    table_name,
                    col["name"],
                    col.get("physical_name", col["name"]),
                    col["type"],
                    1 if col.get("nullable", True) else 0,
                    col.get("default"),
                    col.get("description"),
                    i,
                    1 if col.get("is_system", False) else 0,
                ),
            )
        self.conn.commit()

    def log_history(
        self,
        operation: str,
        schema_name: str,
        table_name: str,
        payload: str,
        conversation_id: str = None,
        rows_affected: int = 0,
        rollback_sql: str = None,
    ):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO _aion_schema_history (schema_name, table_name, operation, payload, conversation_id, rows_affected, rollback_sql)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                schema_name,
                table_name,
                operation,
                payload,
                conversation_id,
                rows_affected,
                rollback_sql,
            ),
        )
        self.conn.commit()

    def list_schemas(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT schema_name, table_name, physical_name, description, row_count, updated_at
            FROM _aion_schema_registry
            WHERE archived_at IS NULL
        """)
        rows = cursor.fetchall()

        schemas = {}
        for r in rows:
            s_name = r["schema_name"]
            if s_name not in schemas:
                schemas[s_name] = {"schema_name": s_name, "tables": []}
            schemas[s_name]["tables"].append(
                {
                    "table_name": r["table_name"],
                    "description": r["description"],
                    "row_count": r["row_count"],
                    "last_updated": r["updated_at"],
                }
            )
        return list(schemas.values())

    def describe_table(
        self, schema_name: str, table_name: str
    ) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT physical_name, description, row_count
            FROM _aion_schema_registry
            WHERE schema_name = ? AND table_name = ? AND archived_at IS NULL
        """,
            (schema_name, table_name),
        )
        reg = cursor.fetchone()
        if not reg:
            return None

        cursor.execute(
            """
            SELECT column_name, column_type, nullable, description
            FROM _aion_schema_columns
            WHERE schema_name = ? AND table_name = ? AND is_system = 0
            ORDER BY ordinal_pos
        """,
            (schema_name, table_name),
        )
        cols = cursor.fetchall()

        return {
            "schema_name": schema_name,
            "table_name": table_name,
            "physical_name": reg["physical_name"],
            "description": reg["description"],
            "row_count": reg["row_count"],
            "columns": [dict(c) for c in cols],
        }
