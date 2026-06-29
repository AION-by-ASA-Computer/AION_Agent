"""Tests for legacy timeline reconstruction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.runtime.timeline_reconstruct import reconstruct_timeline_from_legacy


def test_reconstruct_interleaves_steps_and_artifacts_by_created_at():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    steps = [
        {
            "id": "s1",
            "name": "tool_a",
            "input": "{}",
            "output": "ok",
            "is_error": False,
            "metadata_json": None,
            "created_at": base + timedelta(seconds=2),
        },
    ]
    artifacts = [
        {
            "id": "a1",
            "storage_key": "workspace/x.html",
            "original_name": "x.html",
            "mime": "text/html",
            "kind": "artifact",
            "created_at": base + timedelta(seconds=1),
        },
    ]
    segs = reconstruct_timeline_from_legacy(
        reasoning="think",
        content="answer",
        steps=steps,
        artifacts=artifacts,
    )
    kinds = [s["kind"] for s in segs]
    assert kinds == ["reasoning", "artifact", "tool", "text"]


def test_reconstruct_reasoning_and_text_only():
    segs = reconstruct_timeline_from_legacy(
        reasoning="r", content="c", steps=[], artifacts=[]
    )
    assert [s["kind"] for s in segs] == ["reasoning", "text"]
