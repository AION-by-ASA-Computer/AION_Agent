"""Per-turn guard rails: tool/output/reasoning budgets and no-progress timeout."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from src.runtime.turn_budget import TurnBudget


@dataclass
class StopDecision:
    should_stop: bool = False
    reason: str = ""
    user_message: str = ""
    stop_reason: str = "completed"


@dataclass
class TurnGuardState:
    reasoning_chars: int = 0
    reasoning_events: int = 0
    tool_events: int = 0
    tool_calls: int = 0
    stream_events: int = 0
    control_events: int = 0
    output_events: int = 0
    output_chars: int = 0
    last_progress_at: float = field(default_factory=time.time)
    reasoning_guard_logged: bool = False
    reasoning_no_tool_warned: bool = False
    stop_reason: str = "completed"


class TurnGuards:
    """Loads env budgets once per turn and evaluates hard-stop conditions."""

    def __init__(
        self,
        *,
        message_source: str = "user_input",
        loop_time_fn=None,
        budget: Optional["TurnBudget"] = None,
        reasoning_effort: Optional[str] = None,
    ) -> None:
        from src.runtime.turn_budget import TurnBudget

        self.state = TurnGuardState()
        self._loop_time = loop_time_fn or time.time
        tb = budget or TurnBudget.load(
            message_source=message_source,
            reasoning_effort=reasoning_effort,
        )
        self.turn_timeout = tb.turn_timeout
        self.max_reasoning_chars = tb.max_reasoning_chars
        self.max_reasoning_events = tb.max_reasoning_events
        self.max_tool_events = tb.max_tool_events
        self.max_tool_calls = tb.max_tool_calls
        self.max_stream_events = tb.max_stream_events
        self.max_control_events = int(
            os.getenv("AION_CONTROL_EVENTS_MAX_PER_TURN", "300")
        )
        self.max_output_events = int(os.getenv("AION_OUTPUT_EVENTS_MAX_PER_TURN", "0"))
        self.max_output_chars = int(os.getenv("AION_OUTPUT_CHARS_MAX_PER_TURN", "0"))
        self.no_progress_timeout = tb.no_progress_timeout
        self._turn_budget = tb
        self.min_reasoning_chars_without_tool = int(
            os.getenv("AION_AGENT_MIN_REASONING_CHARS_WITHOUT_TOOL", "2500")
        )
        self.max_reasoning_events_without_tool = int(
            os.getenv("AION_AGENT_MAX_REASONING_WITHOUT_TOOL", "0")
        )
        self.reasoning_hard_stop = os.getenv(
            "AION_REASONING_HARD_STOP", "0"
        ).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self._turn_started_at = self._loop_time()

    def touch_progress(self) -> None:
        self.state.last_progress_at = self._loop_time()

    def check_turn_timeout(self) -> StopDecision:
        if self._loop_time() - self._turn_started_at > self.turn_timeout:
            self.state.stop_reason = "turn_timeout"
            return StopDecision(
                should_stop=True,
                reason="turn_timeout",
                user_message=f"Turn stopped: timeout ({int(self.turn_timeout)}s).",
                stop_reason="turn_timeout",
            )
        return StopDecision()

    def check_no_progress(self) -> StopDecision:
        if (
            self.no_progress_timeout > 0
            and self._loop_time() - self.state.last_progress_at
            > self.no_progress_timeout
        ):
            self.state.stop_reason = "no_progress"
            return StopDecision(
                should_stop=True,
                reason="no_progress",
                user_message=f"Turn stopped: no progress for {int(self.no_progress_timeout)}s.",
                stop_reason="no_progress",
            )
        return StopDecision()

    def on_stream_event(self) -> Optional[StopDecision]:
        self.state.stream_events += 1
        if (
            self.max_stream_events > 0
            and self.state.stream_events > self.max_stream_events
        ):
            self.state.stop_reason = "stream_events"
            return StopDecision(
                should_stop=True,
                reason="stream_events",
                user_message=(
                    f"Turn stopped: too many stream events "
                    f"({self.state.stream_events}/{self.max_stream_events})."
                ),
                stop_reason="stream_events",
            )
        return None

    def on_control_event(self) -> Optional[StopDecision]:
        self.state.control_events += 1
        if (
            self.max_control_events > 0
            and self.state.control_events > self.max_control_events
        ):
            self.state.stop_reason = "control_events"
            return StopDecision(
                should_stop=True,
                reason="control_events",
                user_message="Turn stopped: too many control events in this turn.",
                stop_reason="control_events",
            )
        return None

    def on_tool_start(self) -> Optional[StopDecision]:
        self.state.tool_calls += 1
        if self.max_tool_calls > 0 and self.state.tool_calls > self.max_tool_calls:
            self.state.stop_reason = "tool_calls"
            return StopDecision(
                should_stop=True,
                reason="tool_calls",
                user_message=(
                    f"Turn stopped: too many tool calls "
                    f"({self.state.tool_calls}/{self.max_tool_calls})."
                ),
                stop_reason="tool_calls",
            )
        return None

    def on_tool_event(self) -> Optional[StopDecision]:
        self.state.tool_events += 1
        if self.max_tool_events > 0 and self.state.tool_events > self.max_tool_events:
            self.state.stop_reason = "tool_events"
            return StopDecision(
                should_stop=True,
                reason="tool_events",
                user_message=(
                    f"Turn stopped: too many tool events "
                    f"({self.state.tool_events}/{self.max_tool_events})."
                ),
                stop_reason="tool_events",
            )
        return None

    def metrics_dict(self) -> Dict[str, Any]:
        s = self.state
        return {
            "reasoning_chars": s.reasoning_chars,
            "reasoning_events": s.reasoning_events,
            "tool_calls": s.tool_calls,
            "tool_events": s.tool_events,
            "stream_events": s.stream_events,
            "stop_reason": s.stop_reason,
        }
