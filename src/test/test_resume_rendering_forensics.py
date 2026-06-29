from src.chat_message_visibility import is_step_ui_visible
from src.chat_reasoning import coerce_reasoning_piece
from src.data.message_roles import looks_like_internal_content
from src.runtime.artifact_parser import (
    ArtifactEvent,
    MarkdownArtifactStreamParser,
    PlanTagInterceptorParser,
)


def test_coerce_reasoning_piece_non_string():
    assert coerce_reasoning_piece(None) == ""
    assert coerce_reasoning_piece("abc") == "abc"
    assert coerce_reasoning_piece({"a": 1}) == '{"a": 1}'


def test_step_visibility_filters_legacy_non_ui_message():
    hidden = {"type": "user_message", "metadata": {"role": "internal"}}
    shown_user = {"type": "user_message", "metadata": {"role": "user"}}
    shown_tool = {"type": "tool", "metadata": {"role": "internal"}}
    assert is_step_ui_visible(hidden) is False
    assert is_step_ui_visible(shown_user) is True
    assert is_step_ui_visible(shown_tool) is True


def test_plan_interceptor_handles_escaped_tags():
    p = PlanTagInterceptorParser(MarkdownArtifactStreamParser())
    events = p.feed(
        "&lt;plan&gt;# Plan\\n## Goal\\nG\\n## Tasks\\n- [ ] `t1` **T** (profile: p) (deps: none)\\n&lt;/plan&gt;"
    )
    assert any(e.event == ArtifactEvent.ARTIFACT_START for e in events)
    assert any(e.event == ArtifactEvent.ARTIFACT_END for e in events)


def test_internal_content_marker_detection():
    assert looks_like_internal_content("Role: Orchestrator\\nSkills and rules")
    assert not looks_like_internal_content("Hello, this is a normal user message")
