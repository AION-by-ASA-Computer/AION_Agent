import os
import sqlite3
import io
import csv
import json
import hmac
import time
import base64
import hashlib
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from pydantic import BaseModel, Field

from mcp_servers.agent_db.db_manager import AgentDBManager
from mcp_servers.agent_db.schema_registry import SchemaRegistry
from mcp_servers.agent_db.safety import validate_name, is_readonly_query
from .auth_login import require_admin_role

router = APIRouter(
    tags=["admin-agent-db"],
    # Mountato con prefisso /admin/agent-db in src/api/main.py.
    # Le route ereditano la guard "admin role".
    dependencies=[Depends(require_admin_role)],
)
manager = AgentDBManager(root_dir=os.getenv("AION_AGENT_DB_ROOT", "data/agent_dbs"))
_STRICT_ADMIN_IDENTITY = os.getenv("AION_AGENT_DB_ADMIN_STRICT_IDENTITY", "1").lower() in ("1", "true", "yes", "on")
_ALLOW_ADMIN_SQL_WRITE = os.getenv("AION_AGENT_DB_ADMIN_SQL_WRITE", "0").lower() in ("1", "true", "yes", "on")
_EMBED_SECRET = os.getenv("AION_AGENT_DB_EMBED_SECRET") or os.getenv("AION_AGENT_DB_INTERNAL_SECRET") or "aion-db-embed"

class UserDBStats(BaseModel):
    user_id: str
    schema_count: int
    table_count: int
    row_count: int
    size_bytes: int
    last_modified: Optional[str]


class RowPayload(BaseModel):
    row: Dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = "default"


class TableCreatePayload(BaseModel):
    tenant_id: str = "default"
    description: str = ""
    columns: List[Dict[str, Any]] = Field(default_factory=list)


class RenameTablePayload(BaseModel):
    tenant_id: str = "default"
    new_table_name: str
    description: Optional[str] = None


class AddColumnPayload(BaseModel):
    tenant_id: str = "default"
    column: Dict[str, Any]


class SqlQueryPayload(BaseModel):
    tenant_id: str = "default"
    query: str
    allow_write: bool = False
    limit: int = 200


class ImportPayload(BaseModel):
    tenant_id: str = "default"
    format: str = "json"  # json|csv
    content: str
    mode: str = "append"  # append|replace


class SchemaPayload(BaseModel):
    tenant_id: str = "default"
    schema_name: str


def _resolve_table(conn: sqlite3.Connection, schema_name: str, table_name: str) -> tuple[SchemaRegistry, Dict[str, Any]]:
    registry = SchemaRegistry(conn)
    schema_name = validate_name(schema_name, "Schema name")
    table_name = validate_name(table_name, "Table name")
    detail = registry.describe_table(schema_name, table_name)
    if not detail:
        raise HTTPException(status_code=404, detail="Table not found")
    return registry, detail


def _valid_embed_token(user_id: str, token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        uid, exp_s, sig = raw.rsplit(":", 2)
        if uid != user_id:
            return False
        exp = int(exp_s)
        if exp < int(time.time()):
            return False
        payload = f"{uid}:{exp}"
        expected = hmac.new(_EMBED_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False


def _enforce_admin_identity(user_id: str, x_aion_user_id: Optional[str], x_aion_embed_token: Optional[str] = None) -> None:
    if not _STRICT_ADMIN_IDENTITY:
        return
    if isinstance(x_aion_user_id, str) and x_aion_user_id and x_aion_user_id != user_id:
        raise HTTPException(status_code=403, detail="identity_mismatch: user path and header differ")
    if isinstance(x_aion_user_id, str) and x_aion_user_id == user_id:
        return
    if _valid_embed_token(user_id, x_aion_embed_token):
        return
    raise HTTPException(status_code=403, detail="forbidden: missing valid identity proof")


def _quote_identifier(name: str, context: str) -> str:
    return f"\"{validate_name(name, context)}\""


@router.post("/{user_id}/schemas")
async def create_schema(
    user_id: str,
    payload: SchemaPayload,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        conn = manager.get_connection(payload.tenant_id, user_id)
        manager.initialize_system_tables(conn)
        schema_name = validate_name(payload.schema_name, "Schema name")
        # Logical schema bootstrap entry for UI discovery.
        conn.execute(
            "INSERT OR IGNORE INTO _aion_schema_history (schema_name, table_name, operation, payload, rows_affected) VALUES (?, ?, ?, ?, ?)",
            (schema_name, "_schema", "ADMIN_CREATE_SCHEMA", "{}", 0),
        )
        conn.commit()
        conn.close()
        return {"ok": True, "schema_name": schema_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{user_id}/schemas/{schema_name}")
async def drop_schema(
    user_id: str,
    schema_name: str,
    tenant_id: str = "default",
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        schema_name = validate_name(schema_name, "Schema name")
        conn = manager.get_connection(tenant_id, user_id)
        manager.initialize_system_tables(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name, physical_name FROM _aion_schema_registry WHERE schema_name = ? AND archived_at IS NULL",
            (schema_name,),
        )
        for row in cur.fetchall():
            conn.execute(f"DROP TABLE IF EXISTS \"{row['physical_name']}\"")
            conn.execute(
                "UPDATE _aion_schema_registry SET archived_at = datetime('now') WHERE schema_name = ? AND table_name = ?",
                (schema_name, row["table_name"]),
            )
            conn.execute(
                "DELETE FROM _aion_schema_columns WHERE schema_name = ? AND table_name = ?",
                (schema_name, row["table_name"]),
            )
        conn.execute(
            "INSERT INTO _aion_schema_history (schema_name, table_name, operation, payload, rows_affected) VALUES (?, ?, ?, ?, ?)",
            (schema_name, "_schema", "ADMIN_DROP_SCHEMA", "{}", 0),
        )
        conn.commit()
        conn.close()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/overview", response_model=List[UserDBStats])
async def get_agent_db_overview(tenant_id: str = "default"):
    tenant_dir = os.path.join(manager.root_dir, tenant_id)
    if not os.path.exists(tenant_dir):
        return []
    
    stats = []
    for filename in os.listdir(tenant_dir):
        if filename.endswith(".db"):
            user_id = filename[:-3]
            db_path = os.path.join(tenant_dir, filename)
            
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                
                # Check if system tables exist
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_aion_schema_registry'")
                if not cursor.fetchone():
                    conn.close()
                    continue
                
                cursor.execute("SELECT COUNT(DISTINCT schema_name) as sc, COUNT(*) as tc, SUM(row_count) as rc FROM _aion_schema_registry WHERE archived_at IS NULL")
                row = cursor.fetchone()
                
                cursor.execute("SELECT MAX(updated_at) FROM _aion_schema_registry")
                last_upd = cursor.fetchone()[0]
                
                stats.append(UserDBStats(
                    user_id=user_id,
                    schema_count=row['sc'] or 0,
                    table_count=row['tc'] or 0,
                    row_count=row['rc'] or 0,
                    size_bytes=os.path.getsize(db_path),
                    last_modified=last_upd
                ))
                conn.close()
            except Exception as e:
                # Log error and skip this DB
                print(f"Error reading DB {db_path}: {e}")
                continue
                
    return stats


@router.get("/debug/identity")
async def get_agent_db_identity_debug(
    user_id: str = Query(..., description="Expected user id"),
    tenant_id: str = Query("default", description="Expected tenant id"),
):
    """
    Diagnostic endpoint to verify which DB path admin side resolves for identity.
    """
    db_path = manager.get_db_path(tenant_id, user_id)
    return {
        "effective_user_id": user_id,
        "effective_tenant_id": tenant_id,
        "agent_db_root": manager.root_dir,
        "db_path": db_path,
        "db_exists": os.path.exists(db_path),
        "db_size_bytes": os.path.getsize(db_path) if os.path.exists(db_path) else 0,
    }

@router.get("/{user_id}/detail")
async def get_agent_db_detail(
    user_id: str,
    tenant_id: str = "default",
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        conn = manager.get_connection(tenant_id, user_id, readonly=True)
        registry = SchemaRegistry(conn)
        schemas = registry.list_schemas()
        
        # Add column info for each table
        for schema in schemas:
            for table in schema['tables']:
                table_detail = registry.describe_table(schema['schema_name'], table['table_name'])
                if table_detail:
                    table['columns'] = table_detail['columns']
                    table['physical_name'] = table_detail['physical_name']
        
        # Get history
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM _aion_schema_history ORDER BY performed_at DESC LIMIT 50")
        history = [dict(r) for r in cursor.fetchall()]
        
        conn.close()
        return {
            "user_id": user_id,
            "schemas": schemas,
            "history": history
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{user_id}/{schema_name}/{table_name}/preview")
async def get_table_preview(
    user_id: str,
    schema_name: str,
    table_name: str,
    tenant_id: str = "default",
    include_system: bool = False,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        conn = manager.get_connection(tenant_id, user_id, readonly=True)
        _, detail = _resolve_table(conn, schema_name, table_name)
            
        physical_name = detail['physical_name']
        cursor = conn.cursor()
        # Only select user columns
        user_cols = [c['column_name'] for c in detail['columns']]
        if include_system:
            user_cols = ["_id"] + user_cols
        col_list = ", ".join([f"\"{c}\"" for c in user_cols])
        
        cursor.execute(f"SELECT {col_list} FROM \"{physical_name}\" WHERE _archived_at IS NULL LIMIT 10")
        rows = [dict(r) for r in cursor.fetchall()]
        
        conn.close()
        return {
            "columns": user_cols,
            "rows": rows
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}/{schema_name}/{table_name}/rows")
async def list_table_rows(
    user_id: str,
    schema_name: str,
    table_name: str,
    tenant_id: str = "default",
    page: int = 1,
    page_size: int = 25,
    sort_by: Optional[str] = None,
    sort_dir: str = "asc",
    q: Optional[str] = None,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        conn = manager.get_connection(tenant_id, user_id, readonly=True)
        _, detail = _resolve_table(conn, schema_name, table_name)
        physical_name = detail["physical_name"]
        columns = [c["column_name"] for c in detail["columns"]]
        safe_page = max(page, 1)
        safe_size = min(max(page_size, 1), 200)
        offset = (safe_page - 1) * safe_size

        where = "_archived_at IS NULL"
        params: List[Any] = []
        if q:
            search_parts = [f"CAST(\"{c}\" AS TEXT) LIKE ?" for c in columns]
            where += f" AND ({' OR '.join(search_parts)})"
            params.extend([f"%{q}%"] * len(columns))

        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM \"{physical_name}\" WHERE {where}", params)
        total = int(cursor.fetchone()[0])

        order_col = "_id"
        if sort_by and sort_by in set(columns + ["_id", "_created_at", "_updated_at"]):
            order_col = sort_by
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
        sql = (
            f"SELECT _id, {', '.join([f'\"{c}\"' for c in columns])} "
            f"FROM \"{physical_name}\" WHERE {where} "
            f"ORDER BY \"{order_col}\" {direction} LIMIT ? OFFSET ?"
        )
        cursor.execute(sql, params + [safe_size, offset])
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return {
            "columns": ["_id"] + columns,
            "rows": rows,
            "page": safe_page,
            "page_size": safe_size,
            "total": total,
            "total_pages": (total + safe_size - 1) // safe_size,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{user_id}/{schema_name}/tables/{table_name}")
async def create_table(
    user_id: str,
    schema_name: str,
    table_name: str,
    payload: TableCreatePayload,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        conn = manager.get_connection(payload.tenant_id, user_id)
        manager.initialize_system_tables(conn)
        registry = SchemaRegistry(conn)
        schema_name = validate_name(schema_name, "Schema name")
        table_name = validate_name(table_name, "Table name")
        columns = payload.columns or []
        if not columns:
            raise HTTPException(status_code=400, detail="columns is required")

        physical_name = manager.get_physical_table_name(schema_name, table_name)
        col_defs: List[str] = []
        reg_cols: List[Dict[str, Any]] = []
        for c in columns:
            cname = validate_name(c.get("name"), "Column name")
            ctype = str(c.get("type") or "TEXT").upper()
            nullable = bool(c.get("nullable", True))
            col_defs.append(f"\"{cname}\" {ctype} {'NULL' if nullable else 'NOT NULL'}")
            reg_cols.append({"name": cname, "type": ctype, "nullable": nullable, "description": c.get("description")})
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
        conn.execute(f"CREATE TABLE \"{physical_name}\" ({', '.join(col_defs)})")
        conn.execute(
            f"CREATE TRIGGER \"{physical_name}_updated_at\" AFTER UPDATE ON \"{physical_name}\" "
            f"BEGIN UPDATE \"{physical_name}\" SET _updated_at = datetime('now') WHERE _id = NEW._id; END;"
        )
        registry.register_table(schema_name, table_name, physical_name, payload.description or "")
        registry.register_columns(schema_name, table_name, reg_cols)
        registry.log_history("ADMIN_CREATE_TABLE", schema_name, table_name, json.dumps({"columns": reg_cols}))
        conn.commit()
        conn.close()
        return {"ok": True, "schema_name": schema_name, "table_name": table_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{user_id}/{schema_name}/tables/{table_name}/rename")
async def rename_table(
    user_id: str,
    schema_name: str,
    table_name: str,
    payload: RenameTablePayload,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        conn = manager.get_connection(payload.tenant_id, user_id)
        registry, detail = _resolve_table(conn, schema_name, table_name)
        new_table_name = validate_name(payload.new_table_name, "New table name")
        new_physical = manager.get_physical_table_name(validate_name(schema_name, "Schema name"), new_table_name)
        old_physical = detail["physical_name"]
        conn.execute(f"ALTER TABLE \"{old_physical}\" RENAME TO \"{new_physical}\"")
        registry.register_table(schema_name, new_table_name, new_physical, payload.description or detail.get("description") or "")
        conn.execute(
            "UPDATE _aion_schema_columns SET table_name = ? WHERE schema_name = ? AND table_name = ?",
            (new_table_name, schema_name, table_name),
        )
        conn.execute(
            "UPDATE _aion_schema_registry SET archived_at = datetime('now') WHERE schema_name = ? AND table_name = ? AND physical_name = ?",
            (schema_name, table_name, old_physical),
        )
        registry.log_history("ADMIN_RENAME_TABLE", schema_name, table_name, json.dumps({"to": new_table_name}))
        conn.commit()
        conn.close()
        return {"ok": True, "new_table_name": new_table_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{user_id}/{schema_name}/{table_name}/columns")
async def add_column(
    user_id: str,
    schema_name: str,
    table_name: str,
    payload: AddColumnPayload,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        conn = manager.get_connection(payload.tenant_id, user_id)
        registry, detail = _resolve_table(conn, schema_name, table_name)
        col = payload.column or {}
        cname = validate_name(col.get("name"), "Column name")
        ctype = str(col.get("type") or "TEXT").upper()
        conn.execute(f"ALTER TABLE \"{detail['physical_name']}\" ADD COLUMN \"{cname}\" {ctype}")
        cols = detail["columns"] + [{"column_name": cname, "column_type": ctype, "nullable": True, "description": col.get("description")}]
        reg_cols = [{"name": c["column_name"], "type": c["column_type"], "nullable": bool(c.get("nullable", True)), "description": c.get("description")} for c in cols]
        registry.register_columns(schema_name, table_name, reg_cols)
        registry.log_history("ADMIN_ADD_COLUMN", schema_name, table_name, json.dumps({"column": cname, "type": ctype}))
        conn.commit()
        conn.close()
        return {"ok": True, "column": cname}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{user_id}/{schema_name}/tables/{table_name}")
async def drop_table(
    user_id: str,
    schema_name: str,
    table_name: str,
    tenant_id: str = "default",
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        conn = manager.get_connection(tenant_id, user_id)
        registry, detail = _resolve_table(conn, schema_name, table_name)
        physical = detail["physical_name"]
        conn.execute(f"DROP TABLE IF EXISTS \"{physical}\"")
        conn.execute(
            "UPDATE _aion_schema_registry SET archived_at = datetime('now') WHERE schema_name = ? AND table_name = ?",
            (schema_name, table_name),
        )
        conn.execute(
            "DELETE FROM _aion_schema_columns WHERE schema_name = ? AND table_name = ?",
            (schema_name, table_name),
        )
        registry.log_history("ADMIN_DROP_TABLE", schema_name, table_name, json.dumps({"physical": physical}))
        conn.commit()
        conn.close()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{user_id}/sql")
async def execute_sql(
    user_id: str,
    payload: SqlQueryPayload,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        query = (payload.query or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="query is required")
        write_mode = bool(payload.allow_write and _ALLOW_ADMIN_SQL_WRITE)
        if not write_mode and not is_readonly_query(query):
            raise HTTPException(status_code=400, detail="Only SELECT/WITH allowed in read-only mode")
        if write_mode and ";" in query.strip().rstrip(";"):
            raise HTTPException(status_code=400, detail="Only single-statement SQL is allowed")
        conn = manager.get_connection(payload.tenant_id, user_id, readonly=not write_mode)
        cur = conn.cursor()
        cur.execute(query)
        if query.upper().startswith(("SELECT", "WITH")):
            rows = [dict(r) for r in cur.fetchmany(max(payload.limit, 1))]
            cols = list(rows[0].keys()) if rows else []
            conn.close()
            return {"mode": "read", "columns": cols, "rows": rows}
        changed = cur.rowcount
        conn.execute(
            "INSERT INTO _aion_schema_history (schema_name, table_name, operation, payload, rows_affected) VALUES (?, ?, ?, ?, ?)",
            ("_sql", "_sql", "ADMIN_SQL_WRITE", json.dumps({"query": query[:500]}), int(changed or 0)),
        )
        conn.commit()
        conn.close()
        return {"mode": "write", "rows_affected": changed}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}/{schema_name}/{table_name}/export")
async def export_table(
    user_id: str,
    schema_name: str,
    table_name: str,
    tenant_id: str = "default",
    format: str = "json",
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        conn = manager.get_connection(tenant_id, user_id, readonly=True)
        _, detail = _resolve_table(conn, schema_name, table_name)
        cols = [c["column_name"] for c in detail["columns"]]
        cur = conn.cursor()
        cur.execute(
            f"SELECT {', '.join([f'\"{c}\"' for c in cols])} FROM \"{detail['physical_name']}\" WHERE _archived_at IS NULL"
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        if format == "csv":
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=cols)
            writer.writeheader()
            writer.writerows(rows)
            return {"format": "csv", "content": buf.getvalue()}
        return {"format": "json", "rows": rows}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{user_id}/{schema_name}/{table_name}/import")
async def import_table(
    user_id: str,
    schema_name: str,
    table_name: str,
    payload: ImportPayload,
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
    x_aion_embed_token: Optional[str] = Header(None, alias="X-AION-Embed-Token"),
):
    try:
        _enforce_admin_identity(user_id, x_aion_user_id, x_aion_embed_token)
        conn = manager.get_connection(payload.tenant_id, user_id)
        registry, detail = _resolve_table(conn, schema_name, table_name)
        cols = [c["column_name"] for c in detail["columns"]]
        if payload.format == "csv":
            parsed = list(csv.DictReader(io.StringIO(payload.content)))
        else:
            parsed = json.loads(payload.content)
            if not isinstance(parsed, list):
                raise HTTPException(status_code=400, detail="json content must be array of rows")
        if payload.mode == "replace":
            conn.execute(f"UPDATE \"{detail['physical_name']}\" SET _archived_at = datetime('now'), _source = 'admin:replace'")
        inserted = 0
        for row in parsed:
            clean = {k: row.get(k) for k in cols if k in row}
            if not clean:
                continue
            names = list(clean.keys())
            vals = [clean[k] for k in names]
            conn.execute(
                f"INSERT INTO \"{detail['physical_name']}\" ({', '.join([f'\"{c}\"' for c in names])}, _source) VALUES ({', '.join(['?']*len(names))}, ?)",
                vals + ["admin:import"],
            )
            inserted += 1
        registry.log_history("ADMIN_IMPORT", schema_name, table_name, json.dumps({"rows": inserted, "mode": payload.mode}))
        conn.commit()
        conn.close()
        return {"ok": True, "inserted": inserted}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{user_id}/{schema_name}/{table_name}/rows")
async def insert_table_row(user_id: str, schema_name: str, table_name: str, payload: RowPayload):
    try:
        conn = manager.get_connection(payload.tenant_id, user_id)
        registry, detail = _resolve_table(conn, schema_name, table_name)
        physical_name = detail["physical_name"]
        allowed_cols = {c["column_name"] for c in detail["columns"]}
        row = payload.row or {}
        if not row:
            raise HTTPException(status_code=400, detail="Row payload is empty")
        unknown = [k for k in row.keys() if k not in allowed_cols]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown columns: {', '.join(unknown)}")

        cols = list(row.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_sql = ", ".join([f"\"{c}\"" for c in cols])
        values = [row[c] for c in cols]
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO \"{physical_name}\" ({col_sql}, _source) VALUES ({placeholders}, ?)",
            values + ["admin:manual"],
        )
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return {"ok": True, "_id": new_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{user_id}/{schema_name}/{table_name}/rows/{row_id}")
async def update_table_row(
    user_id: str,
    schema_name: str,
    table_name: str,
    row_id: int,
    payload: RowPayload,
):
    try:
        conn = manager.get_connection(payload.tenant_id, user_id)
        _, detail = _resolve_table(conn, schema_name, table_name)
        physical_name = detail["physical_name"]
        allowed_cols = {c["column_name"] for c in detail["columns"]}
        row = payload.row or {}
        if not row:
            raise HTTPException(status_code=400, detail="Row payload is empty")
        unknown = [k for k in row.keys() if k not in allowed_cols]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown columns: {', '.join(unknown)}")

        assignments = ", ".join([f"\"{k}\" = ?" for k in row.keys()])
        values = list(row.values()) + [row_id]
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE \"{physical_name}\" SET {assignments}, _source = ? WHERE _id = ? AND _archived_at IS NULL",
            list(row.values()) + ["admin:update", row_id],
        )
        conn.commit()
        changed = cursor.rowcount
        conn.close()
        return {"ok": True, "updated": changed}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{user_id}/{schema_name}/{table_name}/rows/{row_id}")
async def delete_table_row(user_id: str, schema_name: str, table_name: str, row_id: int, tenant_id: str = "default"):
    try:
        conn = manager.get_connection(tenant_id, user_id)
        _, detail = _resolve_table(conn, schema_name, table_name)
        physical_name = detail["physical_name"]
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE \"{physical_name}\" SET _archived_at = datetime('now'), _source = ? WHERE _id = ? AND _archived_at IS NULL",
            ("admin:delete", row_id),
        )
        conn.commit()
        changed = cursor.rowcount
        conn.close()
        return {"ok": True, "deleted": changed}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{user_id}/integrity")
async def get_db_integrity(user_id: str, tenant_id: str = "default"):
    try:
        conn = manager.get_connection(tenant_id, user_id, readonly=True)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        
        cursor.execute("PRAGMA foreign_key_check")
        fk_errors = [dict(r) for r in cursor.fetchall()]
        
        # Schema vs Registry check
        registry = SchemaRegistry(conn)
        schemas = registry.list_schemas()
        registry_tables = []
        for s in schemas:
            for t in s['tables']:
                registry_tables.append(t['physical_name'])
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_aion_%' AND name NOT LIKE 'sqlite_%'")
        actual_tables = [r[0] for r in cursor.fetchall()]
        
        orphans = [t for t in actual_tables if t not in registry_tables]
        missing = [t for t in registry_tables if t not in actual_tables]
        
        conn.close()
        return {
            "integrity_check": integrity,
            "foreign_key_errors": fk_errors,
            "orphan_tables": orphans,
            "missing_tables": missing,
            "is_healthy": integrity == "ok" and not fk_errors and not orphans and not missing
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

