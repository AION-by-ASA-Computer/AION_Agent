"""datasource_memory_protocol content checks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "config_std" / "skills" / "datasource_memory_protocol.md"


def test_protocol_requires_explore_ask_persist_flow() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "search → explore → ask → execute → persist → answer" in text.lower() or (
        "Search memory" in text and "Persist BEFORE" in text
    )
    assert "Ask the user" in text or "Ask **before**" in text
    assert "MUST persist" in text or "Persist BEFORE" in text
    assert "mempalace_add_drawer" in text
    assert "sql_memory_save" in text
    assert "asset_manager_navigation_map" not in text
    assert "db_navigation_map" not in text


def test_protocol_no_hardcoded_map_dependency() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "hardcoded schema map" in text.lower() or "no** hardcoded" in text.lower()
