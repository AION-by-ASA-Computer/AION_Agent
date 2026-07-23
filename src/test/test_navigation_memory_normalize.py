"""Normalize MemPalace drawer rows for navigation-memory API."""

from src.memory.navigation_memory_service import (
    _normalize_drawer_row,
    drawer_content_max_chars,
)


def test_normalize_list_drawers_shape():
    raw = {
        "drawer_id": "drawer_wing_proj_am_entry_abc",
        "wing": "wing_proj_aion_am",
        "room": "entry_points",
        "content_preview": "Tabella ordini → join su clienti.id",
    }
    out = _normalize_drawer_row(raw)
    assert out["id"] == raw["drawer_id"]
    assert out["preview"] == raw["content_preview"]
    assert out["content"] == raw["content_preview"]
    assert out["room"] == "entry_points"


def test_normalize_search_shape():
    raw = {
        "text": "Percorso join pallet → magazzino",
        "wing": "wing_proj_aion_am",
        "room": "join_paths",
        "id": "drawer_x",
    }
    out = _normalize_drawer_row(raw)
    assert out["text"] == raw["text"]
    assert out["content"] == raw["text"]


def test_drawer_content_max_chars_allows_ui_edits_beyond_agent_guideline():
    assert drawer_content_max_chars() >= 20000
