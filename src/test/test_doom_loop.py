"""Tests for doom loop detection."""

from src.runtime.doom_loop import DoomLoopTracker, check_doom_loop, reset_tracker


def test_doom_loop_triggers_on_third_identical():
    reset_tracker("sess-a")
    assert check_doom_loop("sess-a", "sandbox_read_file_chunk", {"offset_lines": 0}) is None
    assert check_doom_loop("sess-a", "sandbox_read_file_chunk", {"offset_lines": 0}) is None
    msg = check_doom_loop("sess-a", "sandbox_read_file_chunk", {"offset_lines": 0})
    assert msg is not None
    assert "Doom loop" in msg


def test_doom_loop_resets_on_different_args():
    t = DoomLoopTracker(threshold=3)
    assert t.record("edit", {"a": 1}) is None
    assert t.record("edit", {"a": 2}) is None
    assert t.record("edit", {"a": 3}) is None
