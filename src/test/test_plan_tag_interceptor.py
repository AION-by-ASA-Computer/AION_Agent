from src.runtime.artifact_parser import (
    ArtifactEvent,
    MarkdownArtifactStreamParser,
    PlanTagInterceptorParser,
)


def _events_to_types(events):
    return [e.event for e in events]


def test_plan_is_intercepted_with_markdown_strategy_parser():
    parser = PlanTagInterceptorParser(MarkdownArtifactStreamParser())
    events = []
    events.extend(parser.feed("Intro\n<plan>\n# Plan\n## Goal\nTest\n"))
    events.extend(
        parser.feed(
            "## Tasks\n- [ ] `t1` **Task** (profile: p) (deps: -)\n</plan>\nTail"
        )
    )

    types = _events_to_types(events)
    assert ArtifactEvent.ARTIFACT_START in types
    assert ArtifactEvent.ARTIFACT_CONTENT in types
    assert ArtifactEvent.ARTIFACT_END in types

    start = next(e for e in events if e.event == ArtifactEvent.ARTIFACT_START)
    end = next(e for e in events if e.event == ArtifactEvent.ARTIFACT_END)
    assert start.artifact_type == "plan"
    assert start.artifact_id
    assert "# Plan" in end.content
    assert "Tail" in "".join(e.content for e in events if e.event == ArtifactEvent.TEXT)


def test_pseudo_plan_title_opener_is_intercepted():
    parser = PlanTagInterceptorParser(MarkdownArtifactStreamParser())
    events = []
    events.extend(
        parser.feed(
            'plan title="WWDC 2026"\n# Execution Plan\n## Goal\nG\n## Tasks\n'
            "- [ ] `task_01` **Research** (profile: -) (deps: none)\n</plan>\n"
        )
    )
    events.extend(parser.flush())

    types = _events_to_types(events)
    assert ArtifactEvent.ARTIFACT_START in types
    assert ArtifactEvent.ARTIFACT_END in types
    end = next(e for e in events if e.event == ArtifactEvent.ARTIFACT_END)
    assert "## Goal" in end.content


def test_chunked_plan_title_tokens_are_not_forwarded_as_text():
    parser = PlanTagInterceptorParser(MarkdownArtifactStreamParser())
    text_events = []
    chunks = [
        "<plan title",
        '="Documento Markdown — Novità Apple WWDC 2026"\n# Execution Plan\n',
        "## Goal\nG\n## Tasks\n- [ ] `task_01` **R** (profile: -) (deps: none)\n</plan>\n",
    ]
    for chunk in chunks:
        for ev in parser.feed(chunk):
            if ev.event == ArtifactEvent.TEXT and ev.content:
                text_events.append(ev.content)
        assert parser.is_suppressing_tokens()
    for ev in parser.flush():
        if ev.event == ArtifactEvent.TEXT and ev.content:
            text_events.append(ev.content)

    joined = "".join(text_events)
    assert '="Documento' not in joined
    assert "task_01" not in joined


def test_unclosed_plan_is_closed_on_flush():
    parser = PlanTagInterceptorParser(MarkdownArtifactStreamParser())
    events = []
    events.extend(parser.feed('<plan identifier="p1">\n# Plan\n## Goal\nG\n'))
    events.extend(parser.flush())

    assert any(
        e.event == ArtifactEvent.ARTIFACT_START and e.artifact_id == "p1"
        for e in events
    )
    assert any(
        e.event == ArtifactEvent.ARTIFACT_END and e.artifact_id == "p1" for e in events
    )
