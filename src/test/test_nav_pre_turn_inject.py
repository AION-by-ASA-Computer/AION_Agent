"""MemPalace pre-turn inject is opt-in."""

from __future__ import annotations

import os

from src.memory.project_memory_scope import nav_pre_turn_inject_enabled


def test_nav_pre_turn_inject_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AION_MEMPALACE_NAV_PRE_TURN_INJECT", raising=False)
    assert nav_pre_turn_inject_enabled() is False


def test_nav_pre_turn_inject_enabled_when_set(monkeypatch) -> None:
    monkeypatch.setenv("AION_MEMPALACE_NAV_PRE_TURN_INJECT", "1")
    assert nav_pre_turn_inject_enabled() is True
