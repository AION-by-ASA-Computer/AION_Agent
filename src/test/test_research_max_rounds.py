"""max_rounds=0 from agent means env default, not zero iterations."""

from src.research.handler import _normalize_max_rounds, _normalize_max_time


def test_normalize_max_rounds_zero_uses_default(monkeypatch):
    monkeypatch.setenv("AION_DEEP_RESEARCH_MAX_ROUNDS", "8")
    assert _normalize_max_rounds(0) == 8
    assert _normalize_max_rounds(-1) == 8


def test_normalize_max_rounds_explicit(monkeypatch):
    monkeypatch.setenv("AION_DEEP_RESEARCH_MAX_ROUNDS", "8")
    assert _normalize_max_rounds(5) == 5


def test_normalize_max_time_zero_uses_default(monkeypatch):
    monkeypatch.setenv("AION_DEEP_RESEARCH_MAX_TIME", "600")
    assert _normalize_max_time(0) == 600
