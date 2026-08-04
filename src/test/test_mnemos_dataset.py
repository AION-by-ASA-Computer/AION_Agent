"""Validate Mnemos bench datasets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "config_std" / "benchmarks" / "mnemos_recall.json"
FULL = ROOT / "config_std" / "benchmarks" / "mnemos_recall_full.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_dataset(payload: dict, *, min_cases: int) -> None:
    cases = payload.get("cases") or []
    assert len(cases) >= min_cases
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for case in cases:
        assert case.get("setup_notes"), f"{case.get('id')}: missing setup_notes"
        assert case.get("query"), f"{case.get('id')}: missing query"
        assert case.get("expected_substrings"), f"{case.get('id')}: missing expected_substrings"


@pytest.mark.parametrize("path,min_cases", [(SMOKE, 6), (FULL, 60)])
def test_mnemos_dataset_schema(path: Path, min_cases: int):
    assert path.is_file(), f"missing {path}"
    payload = _load(path)
    _validate_dataset(payload, min_cases=min_cases)


def test_full_dataset_categories():
    payload = _load(FULL)
    cats = {c.get("category") for c in payload["cases"]}
    expected = {
        "fts_keyword",
        "fts_phrase",
        "scope_isolation",
        "semantic_paraphrase",
        "short_token",
        "noise_rejection",
        "disambiguation",
        "numeric_id",
        "url_context",
        "dense_corpus",
        "multi_hit",
    }
    assert expected.issubset(cats)
