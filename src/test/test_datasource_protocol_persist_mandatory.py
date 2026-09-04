"""datasource_memory_protocol content checks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "config_std" / "skills" / "datasource_memory_protocol.md"


def test_protocol_requires_explore_ask_persist_flow() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "memory_note" in text
    assert "memory_recall" in text
    assert "sql_memory_save" in text
    assert "asset_manager_navigation_map" not in text
    assert "db_navigation_map" not in text


def test_protocol_no_hardcoded_map_dependency() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "db_navigation_map" not in text
