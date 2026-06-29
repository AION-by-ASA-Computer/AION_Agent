"""Legacy /plan slash must not auto-register orchestration plans."""
from __future__ import annotations

import pytest

from src.runtime.slash import SlashContext, slash_router


@pytest.mark.anyio
async def test_slash_plan_does_not_emit_orchestration_events():
    ctx = SlashContext(
        raw="/plan Build a Word report",
        conversation_id="sess-test-001",
        user_id="u1",
        profile_name="generic_assistant",
    )
    result = await slash_router.route("/plan Build a Word report", ctx)
    assert result.handled is True
    assert result.sse_events is None
    assert "removed" in (result.message or "").lower()
    assert "Plan" in (result.message or "")
