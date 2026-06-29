from src.a2a.context_distill import distill_subagent_output


def test_distill_short_unchanged():
    s = "hello"
    assert distill_subagent_output(s, max_chars=100) == "hello"


def test_distill_long_truncates():
    s = "x" * 20000
    out = distill_subagent_output(s, max_chars=500)
    assert len(out) < len(s)
    assert "omissis" in out
