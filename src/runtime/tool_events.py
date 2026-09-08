import asyncio
import logging
from typing import Dict, Set

logger = logging.getLogger("aion.tool_events")


class SessionToolEventQueue:
    """
    Manages tool event queues for multiple sessions (Pub/Sub pattern).
    Each session has its own queue(s) of events.
    """

    def __init__(self):
        # session_id -> Set of asyncio.Queue
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue:
        """Create a new queue for a session and subscribe to events."""
        q = asyncio.Queue()
        if session_id not in self._subscribers:
            self._subscribers[session_id] = set()
        self._subscribers[session_id].add(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue):
        """Unsubscribe a queue from session events."""
        if session_id in self._subscribers:
            self._subscribers[session_id].discard(q)
            if not self._subscribers[session_id]:
                del self._subscribers[session_id]

    def put_event(self, session_id: str, event: dict):
        """Put an event into all queues subscribed to a session."""
        event_type = event.get("type")
        tool_name = event.get("name") or event.get("tool_name")
        call_id = event.get("id")

        if event_type in ("tool_start", "tool_end", "tool_error"):
            from src.runtime.context import get_context

            profile = (
                event.get("profile")
                or event.get("profile_name")
                or get_context().get("profile_name")
                or get_context().get("profile")
            )
            if not profile and session_id:
                try:
                    from src.runtime.turn_compaction import resolve_turn_runtime

                    rt = resolve_turn_runtime(session_id)
                    if isinstance(rt, dict):
                        profile = rt.get("profile_name")
                except Exception:
                    pass
            profile_str = profile or "default"

            if event_type == "tool_start":
                tool_input = (
                    event.get("input") if "input" in event else event.get("arguments")
                )
                logger.info(
                    "Tool execution started: session_id=%s profile=%s tool_name=%s call_id=%s input=%s",
                    session_id,
                    profile_str,
                    tool_name,
                    call_id,
                    tool_input,
                    extra={
                        "session_id": session_id,
                        "profile": profile_str,
                        "profile_name": profile_str,
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "event_type": event_type,
                    },
                )
            elif event_type == "tool_end":
                logger.info(
                    "Tool execution completed: session_id=%s profile=%s tool_name=%s call_id=%s",
                    session_id,
                    profile_str,
                    tool_name,
                    call_id,
                    extra={
                        "session_id": session_id,
                        "profile": profile_str,
                        "profile_name": profile_str,
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "event_type": event_type,
                    },
                )
            elif event_type == "tool_error":
                error_msg = event.get("error")
                logger.info(
                    "Tool execution failed: session_id=%s profile=%s tool_name=%s call_id=%s error=%s",
                    session_id,
                    profile_str,
                    tool_name,
                    call_id,
                    error_msg,
                    extra={
                        "session_id": session_id,
                        "profile": profile_str,
                        "profile_name": profile_str,
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "event_type": event_type,
                    },
                )

        subs = self._subscribers.get(session_id)
        if not subs:
            logger.warning(
                "tool_event dropped (no subscriber): session=%s type=%s name=%s",
                (session_id or "")[:12],
                event_type,
                tool_name,
            )
            return
        for q in subs:
            q.put_nowait(event)


tool_event_bus = SessionToolEventQueue()
