"""Tests for session chart payload normalization."""

import os

import pytest

from src.chart_payload import (
    CHART_KINDS,
    chart_kind_feature_enabled,
    normalize_chart_dict,
)


def test_normalize_defaults():
    d = normalize_chart_dict({"query": "q", "data": [{"index": 1, "a": 2.0}]})
    assert d["chart_kind"] == "line"
    assert d["x_key"] == "index"


def test_normalize_bar_and_series():
    d = normalize_chart_dict(
        {
            "query": "q",
            "chart_kind": "bar",
            "x_key": "index",
            "series_keys": ["a", "ghost"],
            "data": [{"index": "t1", "a": 1, "b": 2}],
        }
    )
    assert d["chart_kind"] == "bar"
    assert d["series_keys"] == ["a"]


def test_unknown_kind_fallback():
    d = normalize_chart_dict(
        {"query": "q", "chart_kind": "pie", "data": [{"index": 0, "v": 1}]}
    )
    assert d["chart_kind"] == "line"


def test_feature_flag_forces_line(monkeypatch):
    monkeypatch.setenv("AION_CHART_KIND_ENABLED", "0")
    # module may have cached env at import — re-read pattern: chart_kind_feature_enabled reads os each time
    d = normalize_chart_dict(
        {
            "query": "q",
            "chart_kind": "bar",
            "stacked": True,
            "series_keys": ["a"],
            "data": [{"index": 0, "a": 1}],
        }
    )
    assert d["chart_kind"] == "line"
    assert "series_keys" not in d


def test_chart_kinds_set():
    assert "line" in CHART_KINDS
    assert "area" in CHART_KINDS
    assert "bar" in CHART_KINDS
