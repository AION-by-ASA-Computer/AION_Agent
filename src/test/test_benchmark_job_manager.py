"""Tests for benchmark job helpers."""

from src.benchmarks.job_manager import new_run_id


def test_new_run_id_prefix():
    rid = new_run_id("test")
    assert rid.startswith("test_")
