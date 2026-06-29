import threading
import logging
import time
from typing import Dict

logger = logging.getLogger("aion.stream_sync")
logger.setLevel(logging.INFO)


class StreamSync:
    """
    Singleton context for thread synchronization between the
    Agent thread (Haystack) and the Streaming thread (FastAPI/SSE).
    """

    _lock = threading.Lock()
    _events: Dict[str, threading.Event] = {}

    @classmethod
    def get_event(cls, session_id: str) -> threading.Event:
        with cls._lock:
            if session_id not in cls._events:
                evt = threading.Event()
                evt.set()  # Default: free to go
                cls._events[session_id] = evt
            return cls._events[session_id]

    @classmethod
    def mark_busy(cls, session_id: str):
        """Called by callback when tokens are being produced."""
        evt = cls.get_event(session_id)
        if evt.is_set():
            logger.info("SYNC: Session %s marked BUSY (clearing event)", session_id)
            evt.clear()

    @classmethod
    def mark_caught_up(cls, session_id: str):
        """Called by pipeline when it has consumed all current tokens."""
        evt = cls.get_event(session_id)
        if not evt.is_set():
            logger.info("SYNC: Session %s marked CAUGHT_UP (setting event)", session_id)
            evt.set()

    @classmethod
    def wait_for_sync(cls, session_id: str, timeout: float = 10.0):
        """Called by tools before execution to ensure they see the latest artifacts."""
        evt = cls.get_event(session_id)
        if not evt.is_set():
            logger.info(
                "SYNC: Tool in session %s waiting for stream catch-up (timeout=%s)...",
                session_id,
                timeout,
            )
            start = time.time()
            if not evt.wait(timeout):
                logger.warning(
                    "SYNC: Timeout waiting for stream sync in session %s after %ss",
                    session_id,
                    time.time() - start,
                )
            else:
                logger.info(
                    "SYNC: Session %s sync OK after %ss",
                    session_id,
                    time.time() - start,
                )

    @classmethod
    def purge(cls, session_id: str):
        """Clean up when a request turn finishes."""
        with cls._lock:
            if session_id in cls._events:
                logger.info("SYNC: Purged stream sync event for session %s", session_id)
                try:
                    cls._events[
                        session_id
                    ].set()  # Free any waiting thread before purging
                except Exception:
                    pass
                cls._events.pop(session_id)
