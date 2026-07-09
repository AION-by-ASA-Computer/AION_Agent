import os
import sqlite3
import json
import sys

# Aggiungi root al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_servers.agent_db.db_manager import AgentDBManager
from mcp_servers.agent_db.schema_registry import SchemaRegistry


def seed():
    user_id = "user_test_admin"
    tenant_id = "default"

    manager = AgentDBManager()
    conn = manager.get_connection(tenant_id, user_id)
    manager.initialize_system_tables(conn)
    registry = SchemaRegistry(conn)

    schema_name = "contabilità"
    table_name = "fatture_fornitori"
    physical_name = manager.get_physical_table_name(schema_name, table_name)

    # Create table
    cursor = conn.cursor()
    cursor.execute(f'DROP TABLE IF EXISTS "{physical_name}"')
    cursor.execute(f"""
    CREATE TABLE "{physical_name}" (
        _id INTEGER PRIMARY KEY AUTOINCREMENT,
        _created_at TEXT DEFAULT (datetime('now')),
        _updated_at TEXT DEFAULT (datetime('now')),
        _conversation_id TEXT,
        _source TEXT,
        _archived_at TEXT,
        numero_fattura TEXT,
        data_emissione TEXT,
        fornitore TEXT,
        importo_totale REAL,
        stato TEXT
    )
    """)

    # Seed data
    fatture = [
        ("FT-2026-001", "2026-01-15", "Acme SRL", 1250.00, "pagata"),
        ("FT-2026-002", "2026-02-10", "Beta SpA", 890.50, "da_pagare"),
        ("FT-2026-003", "2026-03-05", "Gamma Snc", 2100.00, "da_pagare"),
        ("FT-2026-004", "2026-03-12", "Delta Co", 450.00, "contestata"),
        ("FT-2026-005", "2026-04-01", "Epsilon SAS", 320.00, "da_pagare"),
    ]

    cursor.executemany(
        f"""
        INSERT INTO "{physical_name}" (numero_fattura, data_emissione, fornitore, importo_totale, stato, _source)
        VALUES (?, ?, ?, ?, ?, 'seed:admin')
    """,
        fatture,
    )

    # Register
    registry.register_table(
        schema_name,
        table_name,
        physical_name,
        "Fatture ricevute dai fornitori nel 2026",
    )
    registry.register_columns(
        schema_name,
        table_name,
        [
            {"name": "numero_fattura", "type": "TEXT", "description": "Numero fattura"},
            {"name": "data_emissione", "type": "DATE", "description": "Data emissione"},
            {"name": "fornitore", "type": "TEXT", "description": "Fornitore"},
            {
                "name": "importo_totale",
                "type": "MONEY",
                "description": "Importo totale",
            },
            {"name": "stato", "type": "TEXT", "description": "Stato pagamento"},
        ],
    )

    cursor.execute(
        f"UPDATE _aion_schema_registry SET row_count = ? WHERE schema_name = ? AND table_name = ?",
        (len(fatture), schema_name, table_name),
    )
    registry.log_history("CREATE_TABLE", schema_name, table_name, "Seed initial table")
    registry.log_history(
        "INSERT_BATCH",
        schema_name,
        table_name,
        f"Seeded {len(fatture)} rows",
        rows_affected=len(fatture),
    )

    conn.commit()
    conn.close()
    print(
        f"Database per {user_id} inizializzato con successo in {manager.get_db_path(tenant_id, user_id)}"
    )


if __name__ == "__main__":
    seed()
