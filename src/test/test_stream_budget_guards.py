from src.agent_pipeline import _chunk_counters
from src.runtime.reasoning_effort import effective_reasoning_effort, normalize_reasoning_effort


def test_chunk_counter_classification():
    assert _chunk_counters("tool_event") == (1, 0)
    assert _chunk_counters("stream_end") == (1, 0)
    assert _chunk_counters("token") == (0, 1)
    assert _chunk_counters("reasoning") == (0, 1)
    assert _chunk_counters("artifact_content") == (0, 1)
    assert _chunk_counters("unknown") == (0, 0)


def test_reasoning_default_is_medium(monkeypatch):
    monkeypatch.delenv("AION_DEFAULT_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("AION_THINKING_ENABLED", raising=False)
    assert normalize_reasoning_effort(None) == "medium"
    assert effective_reasoning_effort(None) == "medium"

