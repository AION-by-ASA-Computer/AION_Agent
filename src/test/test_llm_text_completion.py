from src.benchmarks.longmemeval_v2.query import normalize_actual_answer, score_answer
from src.memory.llm_extract import _env_disable_flag, _text_completion_generation_kwargs


def test_text_completion_disables_thinking_by_default(monkeypatch):
    monkeypatch.delenv("AION_TEXT_COMPLETION_DISABLE_REASONING", raising=False)
    kwargs = _text_completion_generation_kwargs(128)
    assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_text_completion_force_disable_overrides_env(monkeypatch):
    monkeypatch.setenv("AION_TEXT_COMPLETION_DISABLE_REASONING", "0")
    kwargs = _text_completion_generation_kwargs(128, disable_reasoning=True)
    assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_env_disable_flag_parses_zero():
    import os

    os.environ["AION_TEST_DISABLE"] = "0"
    try:
        assert _env_disable_flag("AION_TEST_DISABLE", default=True) is False
    finally:
        os.environ.pop("AION_TEST_DISABLE", None)


def test_normalize_boxed_answer():
    assert normalize_actual_answer("foo \\boxed{Reports;Problems}") == "Reports;Problems"


def test_score_multi_part_expected():
    exp = "Incident Mobile, Incident Portal, My Open Incidents"
    act = "Incident Mobile, Incident Portal, My Open Incidents"
    assert score_answer(exp, act) == 1.0


def test_score_single_letter():
    from src.benchmarks.longmemeval_v2.query import explain_score, score_answer

    assert score_answer("D", "D") == 1.0
    assert score_answer("D", "\\boxed{D}") == 1.0
    assert explain_score("Reports;Problems", "Problems; Assignments")["reason"] == (
        "partial_or_wrong_multi_part"
    )
    assert explain_score("300", "UNKNOWN")["reason"] == "llm_answered_unknown"
