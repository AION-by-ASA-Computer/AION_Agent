"""Unit tests for SQL normalization and fingerprint stability."""
from __future__ import annotations

from src.memory.sql_query_memory.fingerprint import (
    normalize_request_text,
    normalize_sql,
    sql_fingerprint,
)


def test_sql_fingerprint_ignores_literals_and_whitespace():
    a = "SELECT COUNT(*) FROM t WHERE id = 42 AND name = 'foo'"
    b = "SELECT   COUNT(*)   FROM t  WHERE id = 99 AND name = 'bar'  "
    assert sql_fingerprint(a) == sql_fingerprint(b)


def test_sql_fingerprint_distinguishes_identifier_case():
    a = "SELECT * FROM DeviceStatusHistory"
    b = "SELECT * FROM devicestatushistory"
    assert sql_fingerprint(a) != sql_fingerprint(b)


def test_sql_fingerprint_differs_on_structure():
    a = "SELECT a FROM t"
    b = "SELECT b FROM t JOIN u ON t.id = u.id"
    assert sql_fingerprint(a) != sql_fingerprint(b)


def test_normalize_request_collapses_case_and_spaces():
    assert normalize_request_text("  Quanti   Trasferimenti?  ") == "quanti trasferimenti?"


def test_normalize_sql_strips_comments():
    sql = "SELECT 1 -- line comment\n/* block */ FROM t"
    norm = normalize_sql(sql)
    assert "--" not in norm
    assert "/*" not in norm
    assert "SELECT" in norm


def test_normalize_sql_preserves_identifier_case():
    sql = (
        "SELECT d.device_id FROM aion_assetmanager_2.DeviceMovement dm "
        "JOIN aion_assetmanager_2.DeviceStatusHistory dsh ON dsh.movement_id = dm.movement_id "
        "WHERE dsh.status = 'Operativo'"
    )
    norm = normalize_sql(sql)
    assert "DeviceMovement" in norm
    assert "DeviceStatusHistory" in norm
    assert "devicemovement" not in norm
    assert "Operativo" not in norm
    assert "?" in norm
