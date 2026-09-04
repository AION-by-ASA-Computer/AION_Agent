"""Focused tests: current date is always injected into the runtime context."""

from __future__ import annotations

from datetime import datetime

import pytest


# ---------------------------------------------------------------------------
# 1. current_date_context() contains today's date
# ---------------------------------------------------------------------------


def test_current_date_context_contains_today():
    from src.runtime.current_date import current_date_context

    now = datetime.now().astimezone()
    ctx = current_date_context()

    assert now.strftime("%Y-%m-%d") in ctx, "ISO date must appear in context string"
    assert now.strftime("%Y") in ctx, "Year must appear in context string"
    assert now.strftime("%B") in ctx, "Month name must appear in context string"


def test_current_date_context_no_training_cutoff_language():
    """The preamble must explicitly warn against using training-data years."""
    from src.runtime.current_date import current_date_context

    ctx = current_date_context()
    assert "training" in ctx.lower()


def test_current_date_context_recurring_events_guidance():
    """The preamble must instruct the model to use the current year for recurring events."""
    from src.runtime.current_date import current_date_context

    now = datetime.now().astimezone()
    ctx = current_date_context()

    # Recurring-event guidance must mention the current year edition
    assert now.strftime("%Y") in ctx
    # Must reference recurring event types
    assert any(
        keyword in ctx.lower()
        for keyword in ("world cup", "olympics", "champions league", "recurring")
    ), "Preamble must mention recurring events to prevent training-data year confusion"


# ---------------------------------------------------------------------------
# 2. deep_research re-exports current_date_context from the shared utility
# ---------------------------------------------------------------------------


def test_deep_research_reexports_current_date_context():
    from src.research.deep_research import current_date_context as dr_fn
    from src.runtime.current_date import current_date_context as rt_fn

    assert dr_fn is rt_fn, (
        "deep_research.current_date_context must be the same object as "
        "src.runtime.current_date.current_date_context"
    )


# ---------------------------------------------------------------------------
# 3. _augment_user_input() prepends date context as the first block
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_augment_includes_date_when_enabled(monkeypatch):
    """Date block appears at the start of augmented output."""
    monkeypatch.setenv("AION_RUNTIME_DATE_CONTEXT", "1")
    # Disable other blocks to keep the test focused
    monkeypatch.setenv("AION_MEMORY_OPERATIONAL_SUMMARY", "0")
    monkeypatch.setenv("AION_MEMORY_WORKSPACE_MANIFEST", "0")
    monkeypatch.setenv("AION_ORCHESTRATION_CONTEXT", "0")

    from src.agent_pipeline import AgentPipeline

    pipeline = AgentPipeline(
        agent=None, session_id="sess-date-test", profile_name="aion_std"
    )

    result = await pipeline._augment_user_input("What won the 2026 World Cup?")

    now = datetime.now().astimezone()
    assert now.strftime("%Y-%m-%d") in result, (
        "Augmented input must contain today's ISO date"
    )
    assert "runtime context" in result.lower(), "Must use the runtime context wrapper"
    assert result.endswith("What won the 2026 World Cup?"), (
        "Original user input must appear at the end"
    )


@pytest.mark.anyio
async def test_augment_skips_date_when_disabled(monkeypatch):
    """Date block is absent when AION_RUNTIME_DATE_CONTEXT=0."""
    monkeypatch.setenv("AION_RUNTIME_DATE_CONTEXT", "0")
    monkeypatch.setenv("AION_MEMORY_OPERATIONAL_SUMMARY", "0")
    monkeypatch.setenv("AION_MEMORY_WORKSPACE_MANIFEST", "0")
    monkeypatch.setenv("AION_ORCHESTRATION_CONTEXT", "0")

    from src.agent_pipeline import AgentPipeline

    pipeline = AgentPipeline(
        agent=None, session_id="sess-date-off", profile_name="aion_std"
    )

    result = await pipeline._augment_user_input("hello")

    assert result == "hello", "All augmentation disabled → original input unchanged"
