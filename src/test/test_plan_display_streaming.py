"""Streaming plan filter tests (mirrors chat-ui planDisplay.ts)."""

from src.runtime.plan_display import (
    feed_plan_aware_display,
    strip_plan_blocks_for_chat_display,
)


def test_chunked_plan_title_attribute_does_not_leak():
    phase = "none"
    pending = ""
    visible = ""
    chunks = [
        "Analisi\n<plan title",
        '="Documento Markdown — Novità Apple WWDC 2026"\n',
        "# Execution Plan\n## Goal\nG\n",
        "## Tasks\n- [ ] `task_01` **Research** (profile: -) (deps: none)\n</plan>\n",
    ]
    for piece in chunks:
        part, phase, pending = feed_plan_aware_display(piece, phase, pending)
        visible += part
    assert '="Documento' not in visible
    assert "task_01" not in visible
    assert "Analisi" in visible


def test_chunked_pseudo_plan_title_does_not_leak():
    phase = "none"
    pending = ""
    visible = ""
    chunks = [
        "plan title",
        '="WWDC 2026"\n## Goal\nG\n</plan>\n',
    ]
    for piece in chunks:
        part, phase, pending = feed_plan_aware_display(piece, phase, pending)
        visible += part
    assert "WWDC" not in visible
    assert '="WWDC' not in visible


def test_strip_orphan_title_fragment():
    raw = '="Documento Markdown — Novità Apple WWDC 2026"\n- [ ] `task_01`'
    assert strip_plan_blocks_for_chat_display(raw) == ""
