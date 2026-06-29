"""Intent normalization for SQL QueryMemory cross-question reuse."""

from __future__ import annotations

from src.memory.sql_query_memory.fingerprint import (
    build_save_metadata,
    normalize_request_intent,
    normalize_sql,
)


def test_normalize_device_person_intent() -> None:
    a = normalize_request_intent("Che pc ha Giuseppe La Rocca?")
    b = normalize_request_intent("Che pc ha Alessio Colombo?")
    assert a == b
    assert "<DEVICE_TYPE>" in a
    assert "<PERSON>" in a


def test_follow_up_intent() -> None:
    assert normalize_request_intent("Seriale?") == "<FOLLOW_UP_DETAIL>"
    assert normalize_request_intent("e il modello") == "<FOLLOW_UP_DETAIL>"


def test_build_save_metadata() -> None:
    intent, sql, meta = build_save_metadata(
        request_text="Che iPhone ha Luca D'Agostaro?",
        sql_text=(
            "SELECT d.serial FROM aion_assetmanager_2.Users u "
            "JOIN aion_assetmanager_2.Device d ON u.user_id = d.owner_id "
            "WHERE u.nome = 'Luca' AND u.cognome = 'D''Agostaro'"
        ),
    )
    assert intent
    assert "?" in sql
    assert "Device" in sql
    assert "aion_assetmanager_2" in meta.get("schemas", [])
    assert "Device" in meta.get("tables_used", [])
    assert meta.get("intent_template") == intent


def test_parameterized_sql_strips_literals() -> None:
    sql = normalize_sql("SELECT * FROM t WHERE id = 42 AND name = 'foo'")
    assert "42" not in sql
    assert "'foo'" not in sql
    assert "?" in sql
