# mcp_servers/agent_db/safety.py
import re

# Allowed characters: alphanumeric, underscores, spaces, accented chars
ALLOWED_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_À-ÿ ]+$')

# SQL Reserved Keywords to block as table/column names
RESERVED_KEYWORDS = {
    "SELECT", "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
    "TABLE", "VIEW", "INDEX", "FROM", "WHERE", "JOIN", "UNION", "ALL",
    "AND", "OR", "NOT", "NULL", "IN", "LIKE", "BETWEEN", "EXISTS",
    "PRAGMA", "ATTACH", "DETACH", "BEGIN", "COMMIT", "ROLLBACK"
}

def validate_name(name: str, context: str = "Name") -> str:
    """Validates if a table or column name is safe."""
    if not name or len(name) > 63:
        raise ValueError(f"{context} must be between 1 and 63 characters.")
    
    if not ALLOWED_NAME_PATTERN.match(name):
        raise ValueError(f"{context} '{name}' contains invalid characters.")
    
    if name.upper() in RESERVED_KEYWORDS:
        raise ValueError(f"{context} '{name}' is a reserved SQL keyword.")
    
    if name.startswith("_aion_"):
        raise ValueError(f"{context} cannot start with '_aion_' (reserved for system).")
    
    return name

def is_readonly_query(query: str) -> bool:
    """Checks if the query is a safe single-statement read-only SELECT/WITH."""
    if not isinstance(query, str):
        return False
    clean_query = query.strip()
    if not clean_query:
        return False

    upper = clean_query.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return False

    # Block multi-statements and comment tricks.
    blocked_tokens = [
        ";",
        "--",
        "/*",
        "*/",
        " ATTACH ",
        " PRAGMA ",
        " INSERT ",
        " UPDATE ",
        " DELETE ",
        " DROP ",
        " CREATE ",
        " ALTER ",
        " REINDEX ",
        " VACUUM ",
    ]
    padded = f" {upper} "
    return not any(tok in padded for tok in blocked_tokens)
