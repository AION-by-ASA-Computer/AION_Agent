"""Live store for charts produced during a chat turn.

The ``charts`` MCP tools return ``{"query": ..., "data": [...]}`` payloads; the
MCP wrapper in ``src/main.py`` intercepts them, normalizes them and pushes them
here, then emits a ``chart`` tool event so chat-ui renders the chart immediately
(mid-stream). This store is the *live* layer:

* Redis list ``{ns}:charts:{session_id}`` when ``AION_REDIS_URL`` is set (TTL
  ``AION_CHART_QUEUE_TTL_SEC``, refreshed on every push), otherwise an in-process
  dict with the same TTL semantics.
* Reads used by chat-ui (``peek``) are **non destructive**: a reload during or
  shortly after a turn still finds the charts.
* ``flush`` keeps the legacy destructive contract of
  ``GET /sessions/{id}/charts`` and the non-streaming ``/v1/chat`` JSON response.

Durable storage is SQLite (``session_charts``, see ``src/charts_store.py``),
written by the agent pipeline at the end of the SSE turn.
"""

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from src.chart_payload import normalize_chart_dict

logger = logging.getLogger("aion.chart_queue")

_CHART_TTL = int(os.getenv("AION_CHART_QUEUE_TTL_SEC", "3600"))
_NS = (os.getenv("AION_REDIS_NAMESPACE") or "aion").strip(":")
# Safety cap for the in-memory fallback (Redis is bounded by TTL only).
_MEM_MAX_PER_SESSION = 200


def _chart_key(session_id: str) -> str:
    return f"{_NS}:charts:{session_id}"


def _sync_redis():
    url = (os.getenv("AION_REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis as redis_sync

        return redis_sync.from_url(url, decode_responses=True)
    except Exception as e:
        logger.warning("sync Redis client unavailable: %s", e)
        return None


def new_chart_id() -> str:
    """Opaque id shared by the SSE event, the timeline segment and the DB row."""
    return str(uuid.uuid4())


def serialize_chart(
    data: Any,
    *,
    chart_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Turn a tool payload (dict or legacy ``ChartData`` object) into a UI-safe dict.

    The result always carries ``id`` (generated when missing) and, when known,
    ``tool_call_id`` so the UI can place the chart next to the tool step.
    """
    # Legacy Python tools pass a ChartData-like object with a pandas dataframe.
    if hasattr(data, "dataframe") and hasattr(data, "query"):
        serialized: Dict[str, Any] = {
            "query": data.query,
            "data": data.dataframe.reset_index().to_dict(orient="records"),
            "range_seconds": getattr(data, "range_seconds", 0),
            "step_seconds": getattr(data, "step_seconds", 0),
            "chart_kind": getattr(data, "chart_kind", None) or "line",
            "x_key": getattr(data, "x_key", None) or "index",
            "stacked": bool(getattr(data, "stacked", False)),
            "legend_off": bool(getattr(data, "legend_off", False)),
        }
        sk = getattr(data, "series_keys", None)
        if sk:
            serialized["series_keys"] = list(sk)
        yl = getattr(data, "y_label", None)
        if yl:
            serialized["y_label"] = str(yl)
    else:
        serialized = dict(data) if isinstance(data, dict) else {"query": "", "data": []}

    if "query" in serialized and "data" in serialized:
        serialized = normalize_chart_dict(serialized)

    serialized["id"] = str(chart_id or serialized.get("id") or new_chart_id())
    if tool_call_id:
        serialized["tool_call_id"] = str(tool_call_id)
    return serialized


class SessionChartQueue:
    """Charts per session: Redis list when URL set, else in-memory dict."""

    # session_id -> list of (pushed_at_monotonic, chart dict)
    _queues: Dict[str, List[tuple]] = {}
    _lock = threading.Lock()
    _redis = None

    def _get_redis(self):
        if self._redis is False:
            return None
        if self._redis is not None:
            return self._redis
        r = _sync_redis()
        if r is None:
            SessionChartQueue._redis = False
            return None
        try:
            r.ping()
        except Exception:
            if os.getenv("AION_REDIS_FALLBACK_LOCAL", "1").lower() in (
                "1",
                "true",
                "yes",
            ):
                SessionChartQueue._redis = False
                return None
            raise
        SessionChartQueue._redis = r
        return r

    # -- in-memory fallback helpers ------------------------------------------

    @classmethod
    def _mem_push(cls, session_id: str, chart: Dict[str, Any]) -> None:
        with cls._lock:
            items = cls._queues.setdefault(session_id, [])
            items.append((time.monotonic(), chart))
            if len(items) > _MEM_MAX_PER_SESSION:
                del items[: len(items) - _MEM_MAX_PER_SESSION]

    @classmethod
    def _mem_live(cls, session_id: str) -> List[Dict[str, Any]]:
        """Non-expired in-memory charts (drops expired ones as a side effect)."""
        now = time.monotonic()
        with cls._lock:
            items = [
                (ts, c)
                for ts, c in cls._queues.get(session_id, [])
                if now - ts <= _CHART_TTL
            ]
            if items:
                cls._queues[session_id] = items
            else:
                cls._queues.pop(session_id, None)
            return [c for _, c in items]

    # -- public API -----------------------------------------------------------

    @classmethod
    def push(
        cls,
        session_id: str,
        data: Any,
        *,
        chart_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Normalize and store a chart; returns the serialized dict (with ``id``)."""
        serialized = serialize_chart(data, chart_id=chart_id, tool_call_id=tool_call_id)
        r = cls()._get_redis()
        if r is None:
            cls._mem_push(session_id, serialized)
            return serialized
        try:
            key = _chart_key(session_id)
            r.rpush(key, json.dumps(serialized, default=str))
            r.expire(key, _CHART_TTL)
        except Exception as e:
            logger.warning("chart Redis push failed, using memory: %s", e)
            cls._mem_push(session_id, serialized)
        return serialized

    @classmethod
    def push_serialized(cls, session_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Legacy alias for push."""
        return cls.push(session_id, data)

    @classmethod
    def peek(cls, session_id: str) -> List[Dict[str, Any]]:
        """Return the live charts of a session without consuming them."""
        out: List[Dict[str, Any]] = []
        r = cls()._get_redis()
        if r is not None:
            try:
                for raw in r.lrange(_chart_key(session_id), 0, -1) or []:
                    try:
                        item = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(item, dict):
                        out.append(item)
            except Exception as e:
                logger.warning("chart Redis peek failed: %s", e)
        return out + cls._mem_live(session_id)

    @classmethod
    def flush(cls, session_id: str) -> List[Any]:
        """Destructive read (legacy contract): return and delete the live charts."""
        r = cls()._get_redis()
        mem = cls._mem_live(session_id)
        with cls._lock:
            cls._queues.pop(session_id, None)
        if r is None:
            return mem
        try:
            key = _chart_key(session_id)
            pipe = r.pipeline()
            pipe.lrange(key, 0, -1)
            pipe.delete(key)
            items, _ = pipe.execute()
            out: List[Any] = []
            for raw in items or []:
                try:
                    out.append(json.loads(raw))
                except Exception:
                    out.append({"raw": raw})
            return out + mem
        except Exception as e:
            logger.warning("chart Redis flush failed: %s", e)
            return mem

    @classmethod
    def clear(cls, session_id: str) -> None:
        """Drop every live chart of a session (conversation deleted)."""
        with cls._lock:
            cls._queues.pop(session_id, None)
        r = cls()._get_redis()
        if r is None:
            return
        try:
            r.delete(_chart_key(session_id))
        except Exception as e:
            logger.warning("chart Redis clear failed: %s", e)

    @classmethod
    def get_serialized(cls, session_id: str) -> List[Dict[str, Any]]:
        """Consumes the queue and returns list of chart dicts (legacy)."""
        return cls.flush(session_id)


chart_queue = SessionChartQueue()
