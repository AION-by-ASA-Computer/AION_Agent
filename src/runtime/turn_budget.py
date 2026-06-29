"""Unified turn budget policy (P1.4). Wraps TurnGuards for a single import point."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.runtime.turn.turn_guards import TurnGuardState


@dataclass
class TurnBudget:
    """Snapshot of per-turn limits loaded from environment."""

    turn_timeout: float
    max_tool_calls: int
    max_tool_events: int
    max_stream_events: int
    no_progress_timeout: float
    max_reasoning_chars: int
    max_reasoning_events: int

    @classmethod
    def load(
        cls,
        *,
        message_source: str = "user_input",
        reasoning_effort: Optional[str] = None,
    ) -> "TurnBudget":
        import os
        from src.runtime.reasoning_effort import effective_reasoning_effort

        # Prioritize os.getenv to allow dynamic test/runtime overrides
        max_tool_calls_raw = os.getenv("AION_TOOL_CALLS_MAX_PER_TURN")
        if max_tool_calls_raw is not None and max_tool_calls_raw.strip() != "":
            max_tool_calls = int(max_tool_calls_raw)
        else:
            try:
                from src.settings import get_settings

                max_tool_calls = int(get_settings().tool_calls_max_per_turn)
            except Exception:
                max_tool_calls = 24

        max_stream_events_raw = os.getenv("AION_STREAM_EVENTS_MAX_PER_TURN")
        if max_stream_events_raw is not None and max_stream_events_raw.strip() != "":
            max_stream_events = int(max_stream_events_raw)
        else:
            try:
                from src.settings import get_settings

                max_stream_events = int(get_settings().stream_events_max_per_turn)
            except Exception:
                max_stream_events = 0

        no_progress_timeout_raw = os.getenv("AION_NO_PROGRESS_TIMEOUT_SEC")
        if (
            no_progress_timeout_raw is not None
            and no_progress_timeout_raw.strip() != ""
        ):
            no_progress_timeout = float(no_progress_timeout_raw)
        else:
            try:
                from src.settings import get_settings

                no_progress_timeout = float(get_settings().no_progress_timeout_sec)
            except Exception:
                no_progress_timeout = 90.0

        if (message_source or "").strip() == "internal_trigger":
            try:
                from src.runtime.plan_execution import plan_exec_max_tool_calls

                cap = plan_exec_max_tool_calls()
                if max_tool_calls <= 0 or max_tool_calls > cap:
                    max_tool_calls = cap
            except Exception:
                pass

        # Resolve effort level (min, medium, max)
        effort = effective_reasoning_effort(reasoning_effort)

        # Base default limits from env
        base_chars = int(os.getenv("AION_REASONING_MAX_CHARS", "20000"))
        base_events = int(os.getenv("AION_REASONING_MAX_EVENTS", "240"))

        if effort == "min":
            max_reasoning_chars = int(os.getenv("AION_REASONING_MIN_CHARS", "2000"))
            max_reasoning_events = int(os.getenv("AION_REASONING_MIN_EVENTS", "30"))
        elif effort == "max":
            max_reasoning_chars = int(
                os.getenv("AION_REASONING_MAX_LEVEL_CHARS", str(base_chars * 2))
            )
            max_reasoning_events = int(
                os.getenv("AION_REASONING_MAX_LEVEL_EVENTS", str(base_events * 2))
            )
        else:  # medium / fallback
            max_reasoning_chars = base_chars
            max_reasoning_events = base_events

        return cls(
            turn_timeout=float(os.getenv("AION_AGENT_TURN_TIMEOUT", "600")),
            max_tool_calls=max_tool_calls,
            max_tool_events=int(os.getenv("AION_TOOL_EVENTS_MAX_PER_TURN", "60")),
            max_stream_events=max_stream_events,
            no_progress_timeout=no_progress_timeout,
            max_reasoning_chars=max_reasoning_chars,
            max_reasoning_events=max_reasoning_events,
        )

    def telemetry_fields(self, state: TurnGuardState) -> Dict[str, Any]:
        return {
            "turn_timeout": self.turn_timeout,
            "max_tool_calls": self.max_tool_calls,
            "tool_calls_used": state.tool_calls,
            "stop_reason": state.stop_reason,
        }
