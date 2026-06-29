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
        subs = self._subscribers.get(session_id)
        if not subs:
            logger.warning(
                "tool_event dropped (no subscriber): session=%s type=%s name=%s",
                (session_id or "")[:12],
                event.get("type"),
                event.get("name") or event.get("tool_name"),
            )
            return
        for q in subs:
            q.put_nowait(event)

tool_event_bus = SessionToolEventQueue()
