"""Normalize SQL for structural dedup (fingerprint)."""

from __future__ import annotations

import hashlib
import re
from typing import List, Tuple

_WS = re.compile(r"\s+")
_COMMENT_LINE = re.compile(r"--[^\n]*")
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_SINGLE = re.compile(r"'([^']|'')*'")
_STRING_DOUBLE = re.compile(r'"([^"]|"")*"')
_NUMBER = re.compile(r"\b\d+(\.\d+)?\b")
_FROM_JOIN_TABLE = re.compile(
    r"\b(?:from|join)\s+(?:([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*)?([a-zA-Z_][a-zA-Z0-9_]*)",
    re.I,
)
_FROM_JOIN_SCHEMA = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)",
    re.I,
)

_DEVICE_WORDS = (
    "pc",
    "iphone",
    "ipad",
    "laptop",
    "telefono",
    "device",
    "smartphone",
    "macbook",
    "tablet",
    "monitor",
)
_FOLLOW_UP_INTENTS = frozenset(
    {
        "seriale",
        "serial",
        "modello",
        "model",
        "numero di serie",
        "serial number",
        "e il seriale",
        "e il modello",
    }
)


def normalize_request_text(text: str) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def normalize_request_intent(text: str) -> str:
    """Template NL intent with slots for cross-question SQL reuse."""
    s = normalize_request_text(text)
    if not s:
        return s
    compact = s.rstrip("?").strip()
    if compact in _FOLLOW_UP_INTENTS or compact.startswith("e il "):
        return "<FOLLOW_UP_DETAIL>"
    for device in _DEVICE_WORDS:
        if re.search(rf"\b{re.escape(device)}\b", s):
            s = re.sub(rf"\b{re.escape(device)}\b", "<DEVICE_TYPE>", s, count=1)
            break
    s = re.sub(
        r"\b(?:ha|has|uses|use|di|of|per|for)\s+[\w'\-]+(?:\s+[\w'\-]+){0,3}",
        "<PERSON>",
        s,
    )
    s = re.sub(r"['\"][^'\"]+['\"]", "<LITERAL>", s)
    s = _WS.sub(" ", s).strip()
    return s


def normalize_sql(sql: str) -> str:
    """Strip comments, replace literal values with ?, collapse whitespace.

    Identifier case is preserved (required for case-sensitive engines such as
    MySQL on Linux with mixed-case table names).
    """
    s = (sql or "").strip()
    s = _COMMENT_BLOCK.sub(" ", s)
    s = _COMMENT_LINE.sub(" ", s)
    s = _STRING_SINGLE.sub("?", s)
    s = _STRING_DOUBLE.sub("?", s)
    s = _NUMBER.sub("?", s)
    s = _WS.sub(" ", s)
    return s.strip()


def sql_fingerprint(sql: str) -> str:
    norm = normalize_sql(sql)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def extract_tables_from_sql(sql: str) -> List[str]:
    found: List[str] = []
    for m in _FROM_JOIN_TABLE.finditer(sql or ""):
        table = (m.group(2) or "").strip()
        if table and table not in found:
            found.append(table)
    return found[:12]


def extract_schemas_from_sql(sql: str) -> List[str]:
    found: List[str] = []
    for m in _FROM_JOIN_SCHEMA.finditer(sql or ""):
        schema = (m.group(1) or "").strip()
        if schema and schema not in found:
            found.append(schema)
    return found[:6]


def build_save_metadata(
    *,
    request_text: str,
    sql_text: str,
    extra: dict | None = None,
) -> Tuple[str, str, dict]:
    """Return (intent_template, parameterized_sql, metadata dict) for agent-driven saves."""
    intent_template = normalize_request_intent(request_text)
    parameterized_sql = normalize_sql(sql_text)
    meta = dict(extra or {})
    meta["intent_template"] = intent_template
    meta["schemas"] = extract_schemas_from_sql(sql_text)
    tables = extract_tables_from_sql(sql_text)
    if tables:
        meta["tables_used"] = tables
    return intent_template, parameterized_sql, meta
