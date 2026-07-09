"""SSE event demultiplexer — routes plan/artifact side-channel events from the agent stream.

Usage
-----
    demux = StreamDemux(
        on_plan=my_plan_callback,
        on_artifact=my_artifact_callback,
        on_tool=my_tool_callback,
        on_token=my_token_callback,
    )
    # Inside the stream loop:
    demux.feed(chunk)  # classifies and dispatches; returns chunk unchanged
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


# Event-type categories for quick classification
_PLAN_TYPES = frozenset(
    {
        "plan_phase",
        "plan_error",
        "plan_progress",
        "plan_finalize",
        "plan_approved",
        "plan_rejected",
    }
)
_ARTIFACT_TYPES = frozenset(
    {
        "artifact_start",
        "artifact_content",
        "artifact_end",
        "artifact_pending",
    }
)
_TOOL_TYPES = frozenset({"tool_event"})
_TOKEN_TYPES = frozenset({"token", "reasoning"})
_CONTROL_TYPES = frozenset(
    {"keepalive", "done", "error", "stream_end", "context_length_error", "llm_error"}
)


class StreamDemux:
    """Classify outbound SSE chunks by type and dispatch to registered callbacks.

    All registered callbacks are optional.  Each receives the full event dict
    and its return value is ignored.  ``feed()`` always returns the original
    chunk (pass-through).

    Parameters
    ----------
    on_plan:
        Called for plan-lifecycle events (``plan_phase``, ``plan_error``, …
        and any ``orchestration_plan*`` type).
    on_artifact:
        Called for ``artifact_start``, ``artifact_content``, ``artifact_end``,
        ``artifact_pending``.
    on_tool:
        Called for ``tool_event`` chunks (the inner ``event`` dict is also
        accessible via ``chunk['event']``).
    on_token:
        Called for ``token`` and ``reasoning`` chunks.
    on_control:
        Called for control-flow chunks: ``keepalive``, ``done``, ``error``,
        ``stream_end``, ``context_length_error``, ``llm_error``.
    on_any:
        Called for *every* chunk before type-specific dispatch.
    """

    def __init__(
        self,
        *,
        on_plan: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_artifact: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_tool: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_token: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_control: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_any: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._on_plan = on_plan
        self._on_artifact = on_artifact
        self._on_tool = on_tool
        self._on_token = on_token
        self._on_control = on_control
        self._on_any = on_any

        # Accumulated tallies (read-only from outside)
        self._counts: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, chunk: Dict[str, Any]) -> Dict[str, Any]:
        """Classify *chunk*, dispatch to callbacks, return the chunk unchanged."""
        ctype = str(chunk.get("type") or "")

        # Tally
        self._counts[ctype] = self._counts.get(ctype, 0) + 1

        if self._on_any:
            self._on_any(chunk)

        if ctype.startswith("orchestration_plan") or ctype in _PLAN_TYPES:
            if self._on_plan:
                self._on_plan(chunk)
        elif ctype in _ARTIFACT_TYPES:
            if self._on_artifact:
                self._on_artifact(chunk)
        elif ctype in _TOOL_TYPES:
            if self._on_tool:
                self._on_tool(chunk)
        elif ctype in _TOKEN_TYPES:
            if self._on_token:
                self._on_token(chunk)
        elif ctype in _CONTROL_TYPES:
            if self._on_control:
                self._on_control(chunk)

        return chunk

    def counts(self) -> Dict[str, int]:
        """Return a snapshot of per-type event counts seen so far."""
        return dict(self._counts)

    def total(self) -> int:
        """Total number of events fed so far."""
        return sum(self._counts.values())

    def reset(self) -> None:
        """Reset all counters (e.g. between retries)."""
        self._counts.clear()
