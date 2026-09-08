"""Validate Mnemos bench datasets."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "config_std" / "benchmarks" / "mnemos_recall.json"
FULL = ROOT / "config_std" / "benchmarks" / "mnemos_recall_full.json"
ADVERSARIAL = ROOT / "config_std" / "benchmarks" / "mnemos_recall_adversarial.json"


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
        assert "expected_substrings" in case, (
            f"{case.get('id')}: missing expected_substrings"
        )


@pytest.mark.parametrize("path,min_cases", [(SMOKE, 6), (FULL, 60), (ADVERSARIAL, 40)])
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


def test_adversarial_dataset_categories():
    payload = _load(ADVERSARIAL)
    cats = {c.get("category") for c in payload["cases"]}
    expected = {
        "alias_coref",
        "true_paraphrase",
        "temporal_validity",
        "contradiction",
        "recency_rank",
        "importance_rank",
        "cross_scope",
        "scale_recall",
        "precision_noise",
    }
    assert expected.issubset(cats)


_STOPWORDS = frozenset(
    """
    a an and are as at be been by can did do does for from had has have how i in
    is it its me my of on or our so than that the their them there they this to
    us was we were what when where which who whom why will with you your
    """.split()
)


def _content_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS}


def test_true_paraphrase_cases_share_no_content_token_with_target():
    """Guards the invariant that makes the category meaningful.

    The original full dataset had a `semantic_paraphrase` category that passed
    100% with embeddings disabled, because its queries reused the notes' own
    words. Without this check the adversarial suite would drift the same way.
    """
    payload = _load(ADVERSARIAL)
    for case in payload["cases"]:
        if case.get("category") != "true_paraphrase":
            continue
        target = case["setup_notes"][0]
        content = target["content"] if isinstance(target, dict) else target
        overlap = _content_tokens(case["query"]) & _content_tokens(content)
        assert not overlap, (
            f"{case['id']}: query reuses target tokens {sorted(overlap)}"
        )
