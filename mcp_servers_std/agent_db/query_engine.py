# mcp_servers/agent_db/query_engine.py
import re
import sqlite3
from typing import Any, Dict, List, Optional

from .safety import is_readonly_query


def _sqlite_quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def logical_table_map(conn: sqlite3.Connection, schema_name: str) -> Dict[str, str]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT table_name, physical_name FROM _aion_schema_registry
        WHERE schema_name = ? AND archived_at IS NULL
        """,
        (schema_name,),
    )
    return {row["table_name"]: row["physical_name"] for row in cursor.fetchall()}


def apply_schema_table_prefix(sql: str, mapping: Dict[str, str]) -> str:
    """
    Replace logical table identifiers with quoted physical SQLite names.
    Longest logical names first to avoid partial substring collisions.
    """
    if not mapping:
        return sql
    out = sql
    for logical, physical in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        # Skip empty logical names
        if not logical.strip():
            continue
        phys_q = _sqlite_quote_ident(physical)
        pat = re.compile(rf"\b{re.escape(logical)}\b", re.IGNORECASE)
        out = pat.sub(phys_q, out)
    return out


class QueryEngine:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def execute_query(
        self,
        query: str,
        schema_name: Optional[str] = None,
        params: Optional[List[Any]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Executes a read-only SELECT query."""
        if not is_readonly_query(query):
            raise ValueError("Only SELECT or WITH queries are allowed via this tool.")

        final_query = query.strip()
        if schema_name:
            mapping = logical_table_map(self.conn, schema_name)
            final_query = apply_schema_table_prefix(final_query, mapping)

        if "LIMIT" not in final_query.upper():
            final_query += f" LIMIT {int(limit)} OFFSET {int(offset)}"

        cursor = self.conn.cursor()
        if params:
            cursor.execute(final_query, params)
        else:
            cursor.execute(final_query)

        rows = cursor.fetchall()
        columns = [description[0] for description in cursor.description or []]

        return {
            "columns": columns,
            "rows": [list(row) for row in rows],
            "row_count": len(rows),
        }
