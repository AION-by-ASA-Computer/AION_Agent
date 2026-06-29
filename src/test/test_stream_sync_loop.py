"""Regression: legacy stream loop must always call queue.get(), not only when caught-up."""

from pathlib import Path


def test_legacy_stream_loop_queue_get_outside_proactive_sync_if():
    text = Path("src/agent_pipeline.py").read_text(encoding="utf-8")
    marker = "if queue.empty() and not is_streaming:"
    idx = text.find(marker)
    assert idx != -1, "proactive sync guard missing"
    # Next substantive line after mark_caught_up should be queue.get at same indent as `if`
    snippet = text[idx : idx + 400]
    assert "StreamSync.mark_caught_up" in snippet
    after = snippet.split("StreamSync.mark_caught_up", 1)[1]
    # queue.get must appear before any deeper-only branch closes the if-block incorrectly
    get_pos = after.find("chunk = await queue.get()")
    assert get_pos != -1
    between = after[:get_pos]
    # No extra dedent that would put get() still inside if (if body uses 4 more spaces)
    lines_between = [ln for ln in between.splitlines() if ln.strip()]
    for ln in lines_between:
        assert "if " not in ln or "queue.empty" in ln
