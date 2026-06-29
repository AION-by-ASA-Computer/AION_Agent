#!/usr/bin/env python3
"""Lightweight Agent DB checks (no MCP package). Run from repo root."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp_servers.agent_db.db_manager import AgentDBManager  # noqa: E402
from mcp_servers.agent_db.query_engine import (  # noqa: E402
    QueryEngine,
    apply_schema_table_prefix,
    logical_table_map,
)
from mcp_servers.agent_db.safety import is_readonly_query, validate_name  # noqa: E402


def _fail(msg: str) -> None:
    print("FAIL:", msg)
    raise SystemExit(1)


def main() -> None:
    # --- shorthand ---
    sql = "SELECT * FROM fatture WHERE stato = 1"
    mapped = apply_schema_table_prefix(sql, {"fatture": "contabilità__fatture"})
    if '"contabilità__fatture"' not in mapped:
        _fail(f"shorthand missing quoted physical table: {mapped}")

    # --- readonly gate ---
    if is_readonly_query("UPDATE t SET x=1"):
        _fail("readonly gate accepted UPDATE")

    # --- validate_name reserved ---
    try:
        validate_name("SELECT", "t")
        _fail("reserved keyword accepted")
    except ValueError:
        pass

    # --- registry map + query ---
    with tempfile.TemporaryDirectory() as td:
        mgr = AgentDBManager(root_dir=td)
        conn = mgr.get_connection("default", "u1")
        mgr.initialize_system_tables(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO _aion_schema_registry
            (schema_name, table_name, physical_name, description)
            VALUES ('contabilità', 'fatture', 'contabilità__fatture', 'test')
            """
        )
        conn.commit()
        m = logical_table_map(conn, "contabilità")
        if m.get("fatture") != "contabilità__fatture":
            _fail(f"logical map wrong: {m}")

        cur.execute(
            'CREATE TABLE "contabilità__fatture" ('
            "_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "stato INTEGER,"
            "_created_at TEXT,_updated_at TEXT,_conversation_id TEXT,_source TEXT,_archived_at TEXT)"
        )
        cur.execute(
            'INSERT INTO "contabilità__fatture" (stato) VALUES (1)'
        )
        conn.commit()

        eng = QueryEngine(conn)
        res = eng.execute_query(
            "SELECT stato FROM fatture WHERE stato = 1",
            schema_name="contabilità",
            limit=10,
            offset=0,
        )
        if res["row_count"] != 1 or res["rows"][0][0] != 1:
            _fail(f"unexpected query result: {res}")

        conn.close()

        try:
            mgr.get_connection("default", "missing_user", readonly=True)
            _fail("readonly should fail when DB missing")
        except FileNotFoundError:
            pass

    print("OK: agent_db_acceptance_check passed")


if __name__ == "__main__":
    main()
