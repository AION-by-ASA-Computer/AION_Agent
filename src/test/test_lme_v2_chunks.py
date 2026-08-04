"""Tests for trajectory chunk structure after full-retention ingest."""

from __future__ import annotations

from src.benchmarks.longmemeval_v2.prepare import trajectory_text_chunks


def test_header_note_always_includes_goal():
    traj = {
        "id": "abc123",
        "goal": "Offboard user Sean",
        "outcome": "failure",
        "start_url": "https://example.service-now.com/home",
        "states": [{"step": 0, "url": "https://x", "action": "click", "thought": "open"}],
    }
    chunks = trajectory_text_chunks(traj, max_chunks=100)
    header = next(c for c in chunks if "header" in c)
    assert "abc123" in header
    assert "Offboard user Sean" in header
    assert "failure" in header
    assert "start_url" in header


def test_step_note_includes_url_action_thought():
    traj = {
        "id": "t1",
        "goal": "g",
        "states": [
            {
                "step": 2,
                "url": "https://emp.service-now.com/incident",
                "action": "click Submit",
                "thought": "submit the form",
                "accessibility_tree": "menuitem 'Reports', visible",
            }
        ],
    }
    chunks = trajectory_text_chunks(traj, max_chunks=50)
    step = next(c for c in chunks if "step=2" in c and "url:" in c)
    assert "incident" in step
    assert "Submit" in step
    assert "submit the form" in step
