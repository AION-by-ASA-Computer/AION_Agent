# mcp_servers/agent_db/server.py
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .db_manager import AgentDBManager
from .export_engine import ExportEngine
from .ingestion.normalizers import normalize_date, normalize_decimal
from .ltm_notifier import post_structured_drawer_sync
from .query_engine import QueryEngine, apply_schema_table_prefix, logical_table_map
from .schema_registry import SchemaRegistry
from .safety import is_readonly_query, validate_name
from .type_mapper import map_aion_to_sqlite

app = Server("agent_db")
logger = logging.getLogger("aion.agent_db.server")
manager = AgentDBManager(
    root_dir=os.getenv("AION_AGENT_DB_ROOT", "data/agent_dbs"),
)
export_engine = ExportEngine()

_LTM_THRESHOLD = int(os.getenv("AION_AGENT_DB_LTM_SYNC_THRESHOLD", "10"))
_MAX_SIZE_MB = int(os.getenv("AION_AGENT_DB_MAX_SIZE_MB", "2048"))
_MAX_TABLES_PER_USER = int(os.getenv("AION_AGENT_DB_MAX_TABLES_PER_USER", "50"))
_MAX_ROWS_PER_TABLE = int(os.getenv("AION_AGENT_DB_MAX_ROWS_PER_TABLE", "500000"))
_QUERY_TIMEOUT_MS = int(os.getenv("AION_AGENT_DB_QUERY_TIMEOUT_MS", "5000"))
_MAX_EXPORT_ROWS = int(os.getenv("AION_AGENT_DB_MAX_EXPORT_ROWS", "100000"))
_BACKUP_ON_DROP = os.getenv("AION_AGENT_DB_BACKUP_ON_DROP", "1").lower() in ("1", "true", "yes", "on")
_DATE_LOCALE = (os.getenv("AION_AGENT_DB_DATE_LOCALE", "it_IT") or "it_IT").lower()
_DECIMAL_LOCALE = (os.getenv("AION_AGENT_DB_DECIMAL_LOCALE", "IT") or "IT").upper()

_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9\-_]{4,128}$")
_STRICT_IDENTITY = os.getenv("AION_AGENT_DB_STRICT_IDENTITY", "1").lower() in ("1", "true", "yes", "on")


def _workspace_export_path(conversation_id: str, stem: str, suffix: str) -> Path:
    base = Path(os.getenv("AION_DATA_DIR", "data")).resolve()
    root = base / "sessions" / conversation_id / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_stem = re.sub(r"[^a-zA-Z0-9_\-.]", "_", stem)[:80] or "export"
    return root / f"{safe_stem}_{ts}.{suffix}"


async def _notify_structured(key: str, content: str) -> None:
    await asyncio.to_thread(post_structured_drawer_sync, content, key)


def _db_path(tenant_id: str, user_id: str) -> Path:
    return Path(manager.get_db_path(tenant_id, user_id))


def _db_size_bytes(tenant_id: str, user_id: str) -> int:
    p = _db_path(tenant_id, user_id)
    return p.stat().st_size if p.exists() else 0


def _check_db_size_limit(tenant_id: str, user_id: str) -> None:
    if _MAX_SIZE_MB <= 0:
        return
    cur = _db_size_bytes(tenant_id, user_id)
    cap = _MAX_SIZE_MB * 1024 * 1024
    if cur > cap:
        raise ValueError(
            f"Agent DB size limit exceeded ({cur} bytes > {_MAX_SIZE_MB} MB). "
            "Increase AION_AGENT_DB_MAX_SIZE_MB or archive/export data."
        )


def _check_table_limit(conn, table_to_create: bool = False) -> None:
    if _MAX_TABLES_PER_USER <= 0:
        return
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM _aion_schema_registry WHERE archived_at IS NULL")
    current = int(cursor.fetchone()[0])
    if current + (1 if table_to_create else 0) > _MAX_TABLES_PER_USER:
        raise ValueError(
            f"Max tables per user reached ({_MAX_TABLES_PER_USER}). "
            "Archive unused tables before creating new ones."
        )


def _normalize_row_values(row: Dict[str, Any], col_types: Dict[str, str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        ctype = (col_types.get(k) or "").upper()
        if v is None:
            out[k] = v
            continue
        if ctype in ("DATE", "DATETIME"):
            nv = normalize_date(v)
            out[k] = nv
            continue
        if ctype in ("REAL", "MONEY", "PERCENT"):
            # normalize_decimal already handles both EU and US separators.
            nv = normalize_decimal(v)
            out[k] = nv if nv is not None else v
            continue
        out[k] = v
    return out


def _coerce_json_array(value: Any, field_name: str) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        parsed = json.loads(s)
        if not isinstance(parsed, list):
            raise ValueError(f"{field_name} must be a JSON array")
        return parsed
    raise ValueError(f"{field_name} must be an array or JSON-array string")


def _resolve_effective_identity(arguments: Dict[str, Any]) -> tuple[str, str]:
    """
    Resolve user/tenant for agent_db calls.

    Tool arguments are overwritten by the API host before stdio (session-bound identity).
    Subprocess env is fixed at MCP worker spawn and can be stale under user-pool workers,
    so injected arguments take precedence when present.
    """
    env_uid = (os.getenv("AION_CURRENT_USER_ID") or "").strip()
    env_tid = (os.getenv("AION_CURRENT_TENANT_ID") or "").strip()
    arg_uid = (arguments.get("user_id") or "").strip()
    arg_tid = (arguments.get("tenant_id") or "").strip() or "default"

    if arg_uid:
        effective_uid = arg_uid
        effective_tid = arg_tid
        if _STRICT_IDENTITY and env_uid and env_uid != arg_uid:
            logger.info(
                "agent_db identity: using injected user_id=%s (subprocess env had %s)",
                arg_uid,
                env_uid,
            )
        if _STRICT_IDENTITY and env_tid and env_tid != arg_tid:
            logger.info(
                "agent_db identity: using injected tenant_id=%s (subprocess env had %s)",
                arg_tid,
                env_tid,
            )
        return effective_uid, effective_tid

    effective_uid = env_uid
    effective_tid = env_tid or arg_tid or "default"
    if not effective_uid:
        raise ValueError("Missing effective user identity for agent_db call")
    return effective_uid, effective_tid


def _enable_query_timeout(conn, timeout_ms: int):
    if timeout_ms <= 0:
        return None
    started = time.monotonic()
    budget_sec = timeout_ms / 1000.0

    def _progress() -> int:
        if (time.monotonic() - started) > budget_sec:
            return 1
        return 0

    conn.set_progress_handler(_progress, 1000)
    return _progress


@app.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="agent_db_list_schemas",
            description=(
                "List schemas and tables for this user's Agent DB (SQLite per user). "
                "Prefer calling early when handling structured data; user_id is injected automatically."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "tenant_id": {"type": "string", "default": "default"},
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="agent_db_describe_table",
            description="Inspect columns and optional sample rows for schema.table.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "schema_name": {"type": "string"},
                    "table_name": {"type": "string"},
                    "include_sample": {"type": "boolean", "default": True},
                    "tenant_id": {"type": "string", "default": "default"},
                },
                "required": ["user_id", "schema_name", "table_name"],
            },
        ),
        Tool(
            name="agent_db_create_table",
            description=(
                "Create a logical table; physical name is schema_name__table_name. "
                "After creation, prefer agent_db_query with schema_name so logical "
                "table names in SQL map automatically."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "schema_name": {"type": "string"},
                    "table_name": {"type": "string"},
                    "description": {"type": "string"},
                    "columns": {
                        "anyOf": [
                            {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "type": {
                                            "type": "string",
                                            "enum": [
                                                "TEXT",
                                                "INTEGER",
                                                "REAL",
                                                "BOOLEAN",
                                                "DATE",
                                                "DATETIME",
                                                "JSON",
                                                "MONEY",
                                                "PERCENT",
                                                "UUID",
                                            ],
                                        },
                                        "nullable": {"type": "boolean", "default": True},
                                        "default": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["name", "type"],
                                },
                            },
                            {"type": "string", "description": "JSON array string of ColumnDef objects"},
                        ]
                    },
                    "tenant_id": {"type": "string", "default": "default"},
                },
                "required": ["user_id", "schema_name", "table_name", "description", "columns"],
            },
        ),
        Tool(
            name="agent_db_alter_table",
            description=(
                "Alter metadata or schema: ADD_COLUMN (requires column_def), "
                "RENAME_TABLE (new_name), MODIFY_DESCRIPTION (new_description)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "schema_name": {"type": "string"},
                    "table_name": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": ["ADD_COLUMN", "RENAME_TABLE", "MODIFY_DESCRIPTION"],
                    },
                    "column_def": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string"},
                            "nullable": {"type": "boolean"},
                            "default": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                    "new_name": {"type": "string"},
                    "new_description": {"type": "string"},
                    "tenant_id": {"type": "string", "default": "default"},
                },
                "required": ["user_id", "schema_name", "table_name", "operation"],
            },
        ),
        Tool(
            name="agent_db_insert_batch",
            description=(
                "Insert many rows. Keys must match user columns. "
                "Use validate_only=true to check rows without writing. "
                "conversation_id is injected when omitted."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "schema_name": {"type": "string"},
                    "table_name": {"type": "string"},
                    "rows": {
                        "anyOf": [
                            {"type": "array", "items": {"type": "object"}},
                            {"type": "string", "description": "JSON array string of row objects"},
                        ]
                    },
                    "rows_json": {"type": "string", "description": "Optional JSON array string fallback"},
                    "source": {"type": "string", "default": "agent:direct"},
                    "conversation_id": {"type": "string"},
                    "validate_only": {"type": "boolean", "default": False},
                    "tenant_id": {"type": "string", "default": "default"},
                },
                "required": ["user_id", "schema_name", "table_name", "rows"],
            },
        ),
        Tool(
            name="agent_db_query",
            description=(
                "Read-only SELECT or WITH. Pass schema_name to rewrite logical "
                "table names (e.g. FROM fatture) to quoted physical tables "
                "(schema__fatture). Uses a read-only SQLite connection."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "query": {"type": "string"},
                    "schema_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                    "offset": {"type": "integer", "default": 0},
                    "tenant_id": {"type": "string", "default": "default"},
                },
                "required": ["user_id", "query"],
            },
        ),
        Tool(
            name="agent_db_drop_table",
            description="Archive (default) or physically drop a table when confirm=true.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "schema_name": {"type": "string"},
                    "table_name": {"type": "string"},
                    "confirm": {"type": "boolean"},
                    "archive_instead": {"type": "boolean", "default": True},
                    "tenant_id": {"type": "string", "default": "default"},
                },
                "required": ["user_id", "schema_name", "table_name", "confirm"],
            },
        ),
        Tool(
            name="agent_db_create_view",
            description=(
                "Create a SQLite view; select_sql must be read-only SELECT/WITH. "
                "Pass schema_name to rewrite logical table names inside select_sql."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "schema_name": {"type": "string"},
                    "view_name": {"type": "string"},
                    "description": {"type": "string"},
                    "select_sql": {"type": "string"},
                    "tenant_id": {"type": "string", "default": "default"},
                },
                "required": ["user_id", "schema_name", "view_name", "select_sql"],
            },
        ),
        Tool(
            name="agent_db_export",
            description=(
                "Export user columns to csv, json, or xlsx. "
                "If conversation_id is set (sandbox session id), file is written under "
                "data/sessions/<id>/workspace/ and relative_path is returned."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "schema_name": {"type": "string"},
                    "table_name": {"type": "string"},
                    "format": {"type": "string", "enum": ["csv", "json", "xlsx"]},
                    "conversation_id": {"type": "string"},
                    "tenant_id": {"type": "string", "default": "default"},
                },
                "required": ["user_id", "schema_name", "table_name", "format"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    user_id, tenant_id = _resolve_effective_identity(arguments)

    conn = None
    try:
        conn = manager.get_connection(tenant_id, user_id)
        manager.initialize_system_tables(conn)
        registry = SchemaRegistry(conn)
        _check_db_size_limit(tenant_id, user_id)

        if name == "agent_db_list_schemas":
            schemas = registry.list_schemas()
            return [TextContent(type="text", text=json.dumps({"schemas": schemas}, indent=2))]

        if name == "agent_db_describe_table":
            schema_name = arguments.get("schema_name")
            table_name = arguments.get("table_name")
            include_sample = arguments.get("include_sample", True)
            details = registry.describe_table(schema_name, table_name)
            if not details:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": f"Table '{schema_name}.{table_name}' not found."}),
                    )
                ]

            if include_sample:
                cursor = conn.cursor()
                cursor.execute(f'SELECT * FROM "{details["physical_name"]}" LIMIT 3')
                rows = cursor.fetchall()
                details["sample"] = [dict(r) for r in rows]

            return [TextContent(type="text", text=json.dumps(details, indent=2))]

        if name == "agent_db_create_table":
            schema_name = validate_name(arguments.get("schema_name"), "Schema name")
            table_name = validate_name(arguments.get("table_name"), "Table name")
            description = arguments.get("description")
            columns = arguments.get("columns")
            columns = _coerce_json_array(columns, "columns")
            _check_table_limit(conn, table_to_create=True)

            physical_name = manager.get_physical_table_name(schema_name, table_name)

            col_defs = []
            for col in columns:
                name_val = validate_name(col["name"], "Column name")
                type_val = map_aion_to_sqlite(col["type"])
                null_val = "NULL" if col.get("nullable", True) else "NOT NULL"
                default_val = f"DEFAULT {col['default']}" if col.get("default") else ""
                col_defs.append(f'"{name_val}" {type_val} {null_val} {default_val}'.strip())

            col_defs.extend(
                [
                    "_id INTEGER PRIMARY KEY AUTOINCREMENT",
                    "_created_at TEXT NOT NULL DEFAULT (datetime('now'))",
                    "_updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
                    "_conversation_id TEXT",
                    "_source TEXT",
                    "_archived_at TEXT",
                ]
            )

            ddl = f'CREATE TABLE "{physical_name}" ({", ".join(col_defs)});'

            cursor = conn.cursor()
            cursor.execute(ddl)

            trigger_sql = f'''
            CREATE TRIGGER "{physical_name}_updated_at"
            AFTER UPDATE ON "{physical_name}"
            BEGIN
                UPDATE "{physical_name}" SET _updated_at = datetime('now') WHERE _id = NEW._id;
            END;
            '''
            cursor.execute(trigger_sql)

            registry.register_table(schema_name, table_name, physical_name, description)
            registry.register_columns(schema_name, table_name, columns)
            registry.log_history("CREATE_TABLE", schema_name, table_name, json.dumps({"ddl": ddl}))
            conn.commit()
            _check_db_size_limit(tenant_id, user_id)

            col_txt = ", ".join(f"{c['name']} ({c['type']})" for c in columns)
            await _notify_structured(
                f"{user_id}::{schema_name}::{table_name}",
                (
                    f"[structured_data] Schema: {schema_name} | Tabella: {table_name}\n"
                    f"Columns: {col_txt}\nRows: 0 | Table creation completed."
                ),
            )

            return [
                TextContent(
                    type="text",
                    text=json.dumps({"ok": True, "physical_name": physical_name}, indent=2),
                )
            ]

        if name == "agent_db_alter_table":
            schema_name = arguments.get("schema_name")
            table_name = arguments.get("table_name")
            operation = arguments.get("operation")

            details = registry.describe_table(schema_name, table_name)
            if not details:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": f"Table '{schema_name}.{table_name}' not found."}),
                    )
                ]

            physical_name = details["physical_name"]
            cursor = conn.cursor()

            if operation == "ADD_COLUMN":
                col = arguments.get("column_def") or {}
                col_name = validate_name(col["name"], "Column name")
                col_type = map_aion_to_sqlite(col["type"])
                cursor.execute(f'ALTER TABLE "{physical_name}" ADD COLUMN "{col_name}" {col_type}')
                cursor.execute(
                    "SELECT COALESCE(MAX(ordinal_pos), -1) FROM _aion_schema_columns "
                    "WHERE schema_name = ? AND table_name = ?",
                    (schema_name, table_name),
                )
                next_ord = int(cursor.fetchone()[0]) + 1
                cursor.execute(
                    """
                    INSERT INTO _aion_schema_columns
                    (schema_name, table_name, column_name, physical_name, column_type,
                     nullable, default_value, description, ordinal_pos, is_system)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        schema_name,
                        table_name,
                        col_name,
                        col_name,
                        col.get("type", "TEXT"),
                        1 if col.get("nullable", True) else 0,
                        col.get("default"),
                        col.get("description"),
                        next_ord,
                    ),
                )
                registry.log_history(
                    "ADD_COLUMN",
                    schema_name,
                    table_name,
                    json.dumps({"column": col_name, "type": col.get("type")}),
                )
            elif operation == "RENAME_TABLE":
                new_name = validate_name(arguments.get("new_name"), "New table name")
                new_physical = manager.get_physical_table_name(schema_name, new_name)
                cursor.execute(f'ALTER TABLE "{physical_name}" RENAME TO "{new_physical}"')
                cursor.execute(
                    "UPDATE _aion_schema_registry SET table_name = ?, physical_name = ?, "
                    "updated_at = datetime('now') WHERE schema_name = ? AND table_name = ?",
                    (new_name, new_physical, schema_name, table_name),
                )
                cursor.execute(
                    "UPDATE _aion_schema_columns SET table_name = ? WHERE schema_name = ? AND table_name = ?",
                    (new_name, schema_name, table_name),
                )
                registry.log_history(
                    "RENAME_TABLE",
                    schema_name,
                    new_name,
                    json.dumps({"old_table": table_name, "new_table": new_name}),
                )
            elif operation == "MODIFY_DESCRIPTION":
                nd = arguments.get("new_description") or ""
                cursor.execute(
                    "UPDATE _aion_schema_registry SET description = ?, updated_at = datetime('now') "
                    "WHERE schema_name = ? AND table_name = ?",
                    (nd, schema_name, table_name),
                )
                registry.log_history(
                    "MODIFY_DESCRIPTION",
                    schema_name,
                    table_name,
                    json.dumps({"description": nd}),
                )

            conn.commit()
            _check_db_size_limit(tenant_id, user_id)
            return [TextContent(type="text", text=json.dumps({"ok": True}))]

        if name == "agent_db_insert_batch":
            schema_name = arguments.get("schema_name")
            table_name = arguments.get("table_name")
            rows = arguments.get("rows") or []
            if not rows and arguments.get("rows_json"):
                rows = _coerce_json_array(arguments.get("rows_json"), "rows_json")
            else:
                rows = _coerce_json_array(rows, "rows")
            source = arguments.get("source", "agent:direct")
            conv_id = arguments.get("conversation_id")
            validate_only = arguments.get("validate_only", False)

            if not rows:
                return [TextContent(type="text", text=json.dumps({"ok": True, "inserted": 0}))]

            details = registry.describe_table(schema_name, table_name)
            if not details:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": f"Table '{schema_name}.{table_name}' not found."}),
                    )
                ]

            physical_name = details["physical_name"]
            existing_rows = int(details.get("row_count") or 0)
            if _MAX_ROWS_PER_TABLE > 0 and (existing_rows + len(rows)) > _MAX_ROWS_PER_TABLE:
                raise ValueError(
                    f"Max rows per table exceeded: existing={existing_rows}, "
                    f"incoming={len(rows)}, limit={_MAX_ROWS_PER_TABLE}"
                )
            allowed = {c["column_name"] for c in details["columns"]}
            col_types = {c["column_name"]: c.get("column_type", "TEXT") for c in details["columns"]}
            errors: List[Dict[str, Any]] = []
            for i, r in enumerate(rows):
                for k in r.keys():
                    if k not in allowed:
                        errors.append({"row_index": i, "error": f"unknown column '{k}'"})
            normalized_rows = [_normalize_row_values(r, col_types) for r in rows]

            if validate_only:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"ok": len(errors) == 0, "validate_only": True, "errors": errors}),
                    )
                ]

            if errors:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"ok": False, "errors": errors}),
                    )
                ]

            cols = list(normalized_rows[0].keys())
            placeholders = ", ".join(["?" for _ in cols] + ["?", "?"])
            insert_cols = ", ".join([f'"{c}"' for c in cols] + ["_conversation_id", "_source"])

            sql = f'INSERT INTO "{physical_name}" ({insert_cols}) VALUES ({placeholders})'

            data = []
            for r in normalized_rows:
                row_data = [r.get(c) for c in cols]
                row_data.extend([conv_id, source])
                data.append(row_data)

            cursor = conn.cursor()
            cursor.executemany(sql, data)

            cursor.execute(
                "UPDATE _aion_schema_registry SET row_count = row_count + ?, "
                "updated_at = datetime('now') WHERE schema_name = ? AND table_name = ?",
                (len(rows), schema_name, table_name),
            )
            registry.log_history(
                "INSERT_BATCH",
                schema_name,
                table_name,
                json.dumps({"count": len(rows), "source": source}),
                conversation_id=conv_id,
                rows_affected=len(rows),
            )

            cursor.execute(
                "SELECT row_count FROM _aion_schema_registry WHERE schema_name = ? AND table_name = ?",
                (schema_name, table_name),
            )
            new_total = int(cursor.fetchone()[0])
            conn.commit()
            _check_db_size_limit(tenant_id, user_id)

            if len(rows) >= _LTM_THRESHOLD:
                await _notify_structured(
                    f"{user_id}::{schema_name}::{table_name}",
                    (
                        f"[structured_data] Schema: {schema_name} | Tabella: {table_name}\n"
                        f"Inserite {len(rows)} righe (batch). Nuovo totale stimato: {new_total}."
                    ),
                )

            return [
                TextContent(
                    type="text",
                    text=json.dumps({"ok": True, "inserted": len(rows), "new_row_count": new_total}),
                )
            ]

        if name == "agent_db_query":
            query = arguments.get("query")
            schema_name = arguments.get("schema_name")
            limit = int(arguments.get("limit", 100))
            offset = int(arguments.get("offset", 0))
            conn.close()
            conn = None

            try:
                conn_ro = manager.get_connection(tenant_id, user_id, readonly=True)
            except FileNotFoundError as e:
                return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

            try:
                _enable_query_timeout(conn_ro, _QUERY_TIMEOUT_MS)
                engine = QueryEngine(conn_ro)
                result = engine.execute_query(query, schema_name, limit=limit, offset=offset)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            finally:
                conn_ro.set_progress_handler(None, 0)
                conn_ro.close()

        if name == "agent_db_drop_table":
            schema_name = arguments.get("schema_name")
            table_name = arguments.get("table_name")
            confirm = arguments.get("confirm")
            archive_instead = arguments.get("archive_instead", True)

            if not confirm:
                return [TextContent(type="text", text="Error: Confirmation required for DROP TABLE.")]

            details = registry.describe_table(schema_name, table_name)
            if not details:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": f"Table '{schema_name}.{table_name}' not found."}),
                    )
                ]

            cursor = conn.cursor()
            if archive_instead:
                cursor.execute(
                    "UPDATE _aion_schema_registry SET archived_at = datetime('now') "
                    "WHERE schema_name = ? AND table_name = ?",
                    (schema_name, table_name),
                )
            else:
                backup_payload = None
                if _BACKUP_ON_DROP:
                    try:
                        cursor.execute(f'SELECT * FROM "{details["physical_name"]}" LIMIT 200')
                        snap_rows = [dict(r) for r in cursor.fetchall()]
                        backup_payload = {
                            "backup_rows": snap_rows,
                            "backup_rows_count": len(snap_rows),
                            "backup_truncated": True,
                        }
                    except Exception:
                        backup_payload = {"backup_error": "snapshot_failed"}
                cursor.execute(f'DROP TABLE "{details["physical_name"]}"')
                cursor.execute(
                    "DELETE FROM _aion_schema_registry WHERE schema_name = ? AND table_name = ?",
                    (schema_name, table_name),
                )
                cursor.execute(
                    "DELETE FROM _aion_schema_columns WHERE schema_name = ? AND table_name = ?",
                    (schema_name, table_name),
                )
                registry.log_history(
                    "DROP_TABLE",
                    schema_name,
                    table_name,
                    json.dumps(backup_payload or {"backup_rows_count": 0}),
                )

            conn.commit()
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"ok": True, "action": "archived" if archive_instead else "dropped"}),
                )
            ]

        if name == "agent_db_create_view":
            schema_name = validate_name(arguments.get("schema_name"), "Schema name")
            view_name = validate_name(arguments.get("view_name"), "View name")
            description = arguments.get("description") or ""
            select_sql = (arguments.get("select_sql") or "").strip()
            if not is_readonly_query(select_sql):
                return [
                    TextContent(type="text", text=json.dumps({"error": "select_sql must be SELECT or WITH only"}))
                ]

            mapping = logical_table_map(conn, schema_name)
            rewritten = apply_schema_table_prefix(select_sql, mapping)
            physical_view = manager.get_physical_table_name(schema_name, view_name)

            cursor = conn.cursor()
            cursor.execute(f'DROP VIEW IF EXISTS "{physical_view}"')
            cursor.execute(f'CREATE VIEW "{physical_view}" AS {rewritten}')
            cursor.execute(
                """
                INSERT INTO _aion_views_registry (schema_name, view_name, physical_name, description, select_sql)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(schema_name, view_name) DO UPDATE SET
                    physical_name = excluded.physical_name,
                    description = excluded.description,
                    select_sql = excluded.select_sql
                """,
                (schema_name, view_name, physical_view, description, rewritten),
            )
            registry.log_history(
                "CREATE_VIEW",
                schema_name,
                view_name,
                json.dumps({"select_sql": rewritten}),
            )
            conn.commit()
            return [
                TextContent(type="text", text=json.dumps({"ok": True, "physical_name": physical_view}))
            ]

        if name == "agent_db_export":
            schema_name = arguments.get("schema_name")
            table_name = arguments.get("table_name")
            fmt = arguments.get("format")
            conversation_id = (arguments.get("conversation_id") or "").strip()

            details = registry.describe_table(schema_name, table_name)
            if not details:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": f"Table '{schema_name}.{table_name}' not found."}),
                    )
                ]

            cursor = conn.cursor()
            user_cols = [c["column_name"] for c in details["columns"]]
            col_list = ", ".join([f'"{c}"' for c in user_cols])
            cursor.execute(
                f'SELECT {col_list} FROM "{details["physical_name"]}" WHERE _archived_at IS NULL'
            )
            rows = cursor.fetchall()
            data_rows = [list(r) for r in rows]
            if _MAX_EXPORT_ROWS > 0 and len(data_rows) > _MAX_EXPORT_ROWS:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "error": (
                                    f"Export limit exceeded: {len(data_rows)} rows > "
                                    f"AION_AGENT_DB_MAX_EXPORT_ROWS ({_MAX_EXPORT_ROWS})"
                                )
                            }
                        ),
                    )
                ]

            stem = f"{schema_name}__{table_name}"

            if fmt == "csv":
                body = export_engine.export_to_csv(user_cols, data_rows)
                if conversation_id and _SESSION_ID_RE.match(conversation_id):
                    path = _workspace_export_path(conversation_id, stem, "csv")
                    path.write_text(body, encoding="utf-8")
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "ok": True,
                                    "format": "csv",
                                    "rows_exported": len(data_rows),
                                    "relative_path": str(path.resolve()),
                                },
                                indent=2,
                            ),
                        )
                    ]
                return [TextContent(type="text", text=body)]

            if fmt == "json":
                body = export_engine.export_to_json(user_cols, data_rows)
                if conversation_id and _SESSION_ID_RE.match(conversation_id):
                    path = _workspace_export_path(conversation_id, stem, "json")
                    path.write_text(body, encoding="utf-8")
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "ok": True,
                                    "format": "json",
                                    "rows_exported": len(data_rows),
                                    "relative_path": str(path.resolve()),
                                },
                                indent=2,
                            ),
                        )
                    ]
                return [TextContent(type="text", text=body)]

            try:
                xlsx_bytes = export_engine.export_to_xlsx(user_cols, data_rows)
            except ImportError as e:
                return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

            if conversation_id and _SESSION_ID_RE.match(conversation_id):
                path = _workspace_export_path(conversation_id, stem, "xlsx")
                path.write_bytes(xlsx_bytes)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "ok": True,
                                "format": "xlsx",
                                "rows_exported": len(data_rows),
                                "relative_path": str(path.resolve()),
                            },
                            indent=2,
                        ),
                    )
                ]

            import base64

            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "ok": True,
                            "format": "xlsx",
                            "rows_exported": len(data_rows),
                            "content_base64": base64.b64encode(xlsx_bytes).decode("ascii"),
                            "hint": "Decode base64 if conversation_id not provided for workspace write.",
                        },
                        indent=2,
                    ),
                )
            ]

        return [TextContent(type="text", text=json.dumps({"error": f"unknown tool {name}"}))]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(main())
