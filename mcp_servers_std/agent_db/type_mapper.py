# mcp_servers/agent_db/type_mapper.py

AION_TO_SQLITE = {
    "TEXT":    "TEXT",
    "INTEGER": "INTEGER",
    "REAL":    "REAL",
    "BOOLEAN": "INTEGER",  # SQLite doesn't have bool, uses 0/1
    "DATE":    "TEXT",     # ISO8601 string
    "DATETIME":"TEXT",     # ISO8601 with time
    "JSON":    "TEXT",     # Serialized JSON
    "UUID":    "TEXT",
    "MONEY":   "REAL",     # Alias for REAL
    "PERCENT": "REAL",     # Alias for REAL
}

# Unsupported types (agent receives clear error)
UNSUPPORTED = ["BLOB", "FLOAT4", "BYTEA", "ARRAY", "JSONB"]

def map_aion_to_sqlite(aion_type: str) -> str:
    """Maps AION semantic types to SQLite physical types."""
    upper_type = aion_type.upper()
    if upper_type in UNSUPPORTED:
        raise ValueError(f"Type '{aion_type}' is not supported in Agent DB.")
    
    return AION_TO_SQLITE.get(upper_type, "TEXT")  # Default to TEXT if unknown
