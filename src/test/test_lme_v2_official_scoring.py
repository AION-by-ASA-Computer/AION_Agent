"""Tests for the official LongMemEval-V2 eval_function scoring."""

from __future__ import annotations

import asyncio

import pytest

from src.benchmarks.longmemeval_v2.scoring import (
    extract_choice_letters,
    normalize_phrase,
    parse_eval_function,
    score_case,
    split_phrases,
)

PHRASE_SET = (
    "norm_phrase_set_match|lower=true|normalize_hyphen=true"
    "|strip_punct=true|separators=,;|require_non_empty=true"
)
PHRASE_SET_ORDERED = (
    "norm_phrase_set_match_ordered|lower=true|normalize_hyphen=true"
    "|strip_punct=true|separators=;|require_non_empty=true"
)
MC = "mc_choice_match|require_non_empty=true"
MC_SET = "mc_choice_set_match|require_non_empty=true"
ABSTENTION = "llm_abstention_checker|require_non_empty=true"


def run(coro):
    return asyncio.run(coro)


def score(expected: str, actual: str, spec: str, *, question: str = "q", raw: str = ""):
    return run(
        score_case(
            question=question,
            expected=expected,
            actual=actual,
            eval_function=spec,
            raw_actual=raw,
        )
    )


def test_parse_eval_function():
    family, opts = parse_eval_function(PHRASE_SET)
    assert family == "norm_phrase_set_match"
    assert opts["separators"] == ",;"
    assert opts["lower"] == "true"
    assert parse_eval_function("") == ("", {})


def test_normalize_phrase_handles_hyphen_and_punctuation():
    assert normalize_phrase("Change-request") == "change request"
    assert normalize_phrase("5 \u2013 Planning") == "5 planning"
    assert normalize_phrase("Developer Laptop (Mac)") == "developer laptop mac"
    assert normalize_phrase("`risk level`") == "risk level"


def test_split_phrases_uses_declared_separators():
    assert split_phrases("a, b; c", ",;") == ["a", "b", "c"]
    assert split_phrases("a, b; c", ";") == ["a b", "c"]


def test_phrase_set_requires_full_set():
    """The 01307e07 regression: a partial answer used to score 1.0."""
    partial = score(
        "Incident Mobile, Incident Portal, My Open Incidents",
        "Incident Mobile, Incident Portal",
        PHRASE_SET,
    )
    assert partial["score"] == 0.0
    assert partial["reason"] == "phrase_set_under_answered"
    assert partial["missing_phrases"] == ["my open incidents"]

    full = score(
        "Incident Mobile, Incident Portal, My Open Incidents",
        "My Open Incidents, Incident Portal, Incident Mobile",
        PHRASE_SET,
    )
    assert full["score"] == 1.0
    assert full["reason"] == "phrase_set_match"


def test_phrase_set_flags_over_answering():
    result = score("Reports", "Reports, Problems", PHRASE_SET)
    assert result["score"] == 0.0
    assert result["reason"] == "phrase_set_over_answered"
    assert result["extra_phrases"] == ["problems"]


def test_phrase_set_ordered_is_order_sensitive():
    assert (
        score("Reports;Problems", "Reports; Problems", PHRASE_SET_ORDERED)["score"]
        == 1.0
    )
    reversed_answer = score("Reports;Problems", "Problems;Reports", PHRASE_SET_ORDERED)
    assert reversed_answer["score"] == 0.0
    assert reversed_answer["reason"] == "phrase_list_mismatch"


def test_phrase_set_tolerates_formatting_differences():
    result = score(
        "Developer Laptop (Mac); Development Laptop (PC)",
        "developer laptop (mac), development laptop (pc)",
        PHRASE_SET,
    )
    assert result["score"] == 1.0


def test_unknown_answer_scores_zero_with_clear_reason():
    result = score("Class", "UNKNOWN", PHRASE_SET)
    assert result["score"] == 0.0
    assert result["reason"] == "llm_answered_unknown"


def test_missing_reference_and_empty_prediction():
    assert score("", "anything", PHRASE_SET)["reason"] == "missing_reference"
    assert score("Class", "", PHRASE_SET)["reason"] == "empty_prediction"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("\\boxed{G}", ["G"]),
        ("G", ["G"]),
        ("The answer is D.", ["D"]),
        ("\\boxed{A,B,F}", ["A", "B", "F"]),
        ("no letter here at all", []),
    ],
)
def test_extract_choice_letters(text, expected):
    assert extract_choice_letters(text) == expected


def test_mc_choice_match():
    assert score("G", "\\boxed{G}", MC, raw="\\boxed{G}")["score"] == 1.0
    wrong = score("B", "D", MC, raw="\\boxed{D}")
    assert wrong["score"] == 0.0
    assert wrong["reason"] == "mc_mismatch"
    assert wrong["expected_choices"] == ["B"]
    assert wrong["actual_choices"] == ["D"]


def test_mc_choice_set_match_is_order_insensitive():
    assert (
        score("A,B,F", "\\boxed{F, A, B}", MC_SET, raw="\\boxed{F, A, B}")["score"]
        == 1.0
    )
    assert score("A,B,F", "\\boxed{A, B}", MC_SET, raw="\\boxed{A, B}")["score"] == 0.0


def test_mc_scorer_handles_boolean_gold():
    """11 rows reuse mc_choice_match for true/false answers, not letters."""
    assert score("false", "\\boxed{false}", MC, raw="\\boxed{false}")["score"] == 1.0
    assert score("true", "\\boxed{True}", MC, raw="\\boxed{True}")["score"] == 1.0
    wrong = score("false", "\\boxed{true}", MC, raw="\\boxed{true}")
    assert wrong["score"] == 0.0
    assert wrong["reason"] == "literal_mismatch"


def test_none_is_a_legitimate_gold_answer():
    """Two rows expect the literal answer "none"; it must not be read as a refusal."""
    assert score("none", "none", PHRASE_SET)["score"] == 1.0
    missed = score("Class", "none", PHRASE_SET)
    assert missed["score"] == 0.0
    assert missed["reason"] == "phrase_set_mismatch"


def test_mc_reports_missing_letter():
    result = score("G", "I cannot determine this", MC, raw="I cannot determine this")
    assert result["reason"] == "no_choice_letter_found"


def test_llm_judge_can_be_disabled(monkeypatch):
    monkeypatch.setenv("AION_LME_V2_LLM_JUDGE", "0")
    result = score(
        "There is no fifth button there.",
        "The fifth button is Save.",
        ABSTENTION,
    )
    assert result["score"] == 0.0
    assert result["reason"] == "llm_judge_disabled"


def test_llm_judge_parses_verdict(monkeypatch):
    monkeypatch.setenv("AION_LME_V2_LLM_JUDGE", "1")
    calls = []

    async def fake_llm(system, user, **kwargs):
        calls.append((system, user))
        return {"raw_text": "CORRECT"}

    monkeypatch.setattr(
        "src.benchmarks.longmemeval_v2.scoring.complete_text_async_detailed",
        fake_llm,
    )
    result = score(
        "There is no fifth button there.",
        "There is no fifth button on that field.",
        ABSTENTION,
    )
    assert result["score"] == 1.0
    assert result["reason"] == "llm_judge_correct"
    assert "false premise" in calls[0][0].lower()


def test_llm_judge_survives_outage(monkeypatch):
    monkeypatch.setenv("AION_LME_V2_LLM_JUDGE", "1")

    async def boom(system, user, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(
        "src.benchmarks.longmemeval_v2.scoring.complete_text_async_detailed",
        boom,
    )
    result = score("no such field", "no such field", ABSTENTION)
    assert result["score"] == 0.0
    assert result["reason"] == "llm_judge_error"
