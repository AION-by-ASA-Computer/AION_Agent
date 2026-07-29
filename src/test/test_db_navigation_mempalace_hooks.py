"""Unit tests for MemPalace navigation hooks."""

from __future__ import annotations

import json

from src.memory.project_memory_scope import project_wing, room_hints_from_query
from src.runtime.db_navigation_mempalace_hooks import (
    _build_nav_drawer_content,
    _format_inject_block,
    _parse_search_hits,
    profile_wants_mempalace_navigation,
)


def test_project_wing_slug():
    assert project_wing("vendite") == "wing_proj_vendite"
    assert project_wing("Alibr DB") == "wing_proj_alibr_db"


def test_room_hints_join():
    hints = room_hints_from_query("join testate_ordini con movimenti")
    assert "join_paths" in hints


def test_parse_search_hits_json():
    raw = json.dumps(
        {
            "results": [
                {
                    "text": "JOIN via cod_cliente",
                    "similarity": 0.91,
                    "wing": "wing_proj_default",
                    "room": "join_paths",
                }
            ]
        }
    )
    hits = _parse_search_hits(raw)
    assert len(hits) == 1
    assert hits[0][0] == 0.91


def test_format_inject_block():
    block = _format_inject_block(
        "default",
        [(0.9, "Use testate_ordini for orders", "wing_proj_default", "entry_points")],
    )
    assert "MemPalace navigation" in block
    assert "wing_proj_default" in block


def test_build_nav_drawer_join_ok():
    room, content = _build_nav_drawer_content(
        user_request="ordini cliente",
        sql="SELECT * FROM testate_ordini_clienti t JOIN dettagli_ordini_clienti d ON t.id = d.id_testata",
        ok=True,
        output_preview="[]",
        error_hint="",
    )
    assert room == "join_paths"
    assert "testate_ordini_clienti" in content


def test_build_nav_drawer_pitfall():
    room, content = _build_nav_drawer_content(
        user_request="sscc",
        sql="SELECT 1 FROM movimenti_automa m JOIN toc t ON m.id = t.id",
        ok=False,
        output_preview="",
        error_hint="0 rows",
    )
    assert room == "pitfalls"
    assert "0 rows" in content


def test_profile_wants_postgres():
    assert profile_wants_mempalace_navigation("postgres_metadata_assistant")
