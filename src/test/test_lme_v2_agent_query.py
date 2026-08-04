"""Tests for benchmark agent scope binding (mocked pipeline)."""

from __future__ import annotations

import pytest

from src.benchmarks.env_config import apply_benchmark_isolation_env


@pytest.mark.asyncio
async def test_answer_question_with_agent_binds_scope(monkeypatch):
    monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "benchmark")
    apply_benchmark_isolation_env()

    captured: dict = {}

    class FakePipeline:
        def __init__(self, agent, session_id, profile_name, user_id):
            captured["user_id"] = user_id
            captured["session_id"] = session_id

        async def run_stream(self, question, sql_query_project=None):
            captured["project"] = sql_query_project
            yield {"type": "tool_event", "event": {"type": "tool_start", "name": "memory_recall"}}
            yield {"type": "final", "text": "\\boxed{Reports}"}

    async def fake_get_agent(profile_name, session_id, user_id, tenant_id="default"):
        captured["tenant_id"] = tenant_id
        return object(), profile_name

    monkeypatch.setattr("src.benchmarks.longmemeval_v2.agent_query.get_agent", fake_get_agent)
    monkeypatch.setattr("src.benchmarks.longmemeval_v2.agent_query.AgentPipeline", FakePipeline)

    from src.benchmarks.longmemeval_v2.agent_query import answer_question_with_agent

    pred, latency, dbg = await answer_question_with_agent(
        "Which module?",
        run_id="bench_test",
        profile_name="benchmark_memory",
        project_slug="lme_bench_test",
        session_id="bench_test_q1",
    )
    assert pred == "Reports"
    assert captured["project"] == "lme_bench_test"
    assert captured["user_id"] == "lme_v2_bench_test"
    assert captured["tenant_id"] == "benchmark"
    assert dbg["memory_recall_calls"] == 1
