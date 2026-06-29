import json
import logging
import os
import threading
from typing import Any, Dict, List

from src.chart_payload import normalize_chart_dict

logger = logging.getLogger("aion.chart_queue")

_CHART_TTL = int(os.getenv("AION_CHART_QUEUE_TTL_SEC", "3600"))
_NS = (os.getenv("AION_REDIS_NAMESPACE") or "aion").strip(":")


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


class SessionChartQueue:
    """Charts per session: Redis list when URL set, else in-memory dict."""

    _queues: Dict[str, List[Dict[str, Any]]] = {}
    _lock = threading.Lock()
    _redis = None

    def _get_redis(self):
        if self._redis is False:
            return None
        if self._redis is not None:
            return self._redis
        r = _sync_redis()
        if r is None:
            self._redis = False
            return None
        try:
            r.ping()
        except Exception:
            if os.getenv("AION_REDIS_FALLBACK_LOCAL", "1").lower() in (
                "1",
                "true",
                "yes",
            ):
                self._redis = False
                return None
            raise
        self._redis = r
        return self._redis

    @classmethod
    def push(cls, session_id: str, data: Any):
        """Pushes a chart (dict or ChartData object) to the queue."""
        inst = cls()

        # Convert ChartData object to serializable dict immediately
        if hasattr(data, "dataframe") and hasattr(data, "query"):
            serialized = {
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
            serialized = data if isinstance(data, dict) else {"query": "", "data": []}

        if (
            isinstance(serialized, dict)
            and "query" in serialized
            and "data" in serialized
        ):
            serialized = normalize_chart_dict(serialized)

        r = inst._get_redis()
        if r is None:
            with cls._lock:
                if session_id not in cls._queues:
                    cls._queues[session_id] = []
                cls._queues[session_id].append(serialized)
            return
        try:
            key = _chart_key(session_id)
            r.rpush(key, json.dumps(serialized, default=str))
            r.expire(key, _CHART_TTL)
        except Exception as e:
            logger.warning("chart Redis push failed, using memory: %s", e)
            with cls._lock:
                if session_id not in cls._queues:
                    cls._queues[session_id] = []
                cls._queues[session_id].append(serialized)

    @classmethod
    def push_serialized(cls, session_id: str, data: Dict[str, Any]):
        """Legacy alias for push."""
        cls.push(session_id, data)

    @classmethod
    def flush(cls, session_id: str) -> List[Any]:
        inst = cls()
        r = inst._get_redis()
        mem = []
        with cls._lock:
            mem = cls._queues.pop(session_id, [])
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
    def get_serialized(cls, session_id: str) -> List[Dict[str, Any]]:
        """Consumes the queue and returns list of chart dicts."""
        return cls.flush(session_id)


chart_queue = SessionChartQueue()
