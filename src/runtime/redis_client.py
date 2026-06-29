"""
Redis singleton for chart queue, locks, rate limiting, cache.
Falls back to in-process implementations when Redis is unavailable and
AION_REDIS_FALLBACK_LOCAL=1.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional, Protocol, Union
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger("aion.redis")

_NS = (os.getenv("AION_REDIS_NAMESPACE") or "aion").strip(":")


class _LocalFallback:
    """Minimal in-process stand-in for dev single-process."""

    def __init__(self) -> None:
        self._lists: dict[str, list[str]] = {}
        self._kv: dict[str, tuple[Any, float | None]] = {}
        self._locks: dict[str, float] = {}

    async def ping(self) -> bool:
        return True

    async def rpush(self, key: str, *values: str) -> int:
        lst = self._lists.setdefault(key, [])
        lst.extend(values)
        return len(lst)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = self._lists.get(key, [])
        if end == -1:
            return lst[start:]
        return lst[start : end + 1]

    async def lpop(self, key: str) -> str | None:
        lst = self._lists.get(key, [])
        if not lst:
            return None
        val = lst.pop(0)
        if not lst and key in self._lists:
            del self._lists[key]
        return val

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if k in self._lists:
                del self._lists[k]
                n += 1
            if k in self._kv:
                del self._kv[k]
                n += 1
        return n

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        if nx and key in self._kv:
            return None
        exp_at = time.time() + ex if ex else None
        self._kv[key] = (value, exp_at)
        return True

    async def get(self, key: str) -> str | None:
        v = self._kv.get(key)
        if not v:
            return None
        val, exp_at = v
        if exp_at and time.time() > exp_at:
            del self._kv[key]
            return None
        return str(val)

    async def incr(self, key: str) -> int:
        cur = int((await self.get(key)) or "0")
        n = cur + 1
        await self.set(key, str(n), ex=None)
        return n


class SupportsRedis(Protocol):
    async def ping(self) -> bool: ...


_client: Any = None
_fallback_used = False
_redis_degraded = False
_redis_warn_once_keys: set[str] = set()


def _is_connection_error(exc: Exception) -> bool:
    try:
        from redis.exceptions import ConnectionError as RedisConnectionError

        if isinstance(exc, (ConnectionError, OSError, RedisConnectionError)):
            return True
    except ImportError:
        if isinstance(exc, (ConnectionError, OSError)):
            return True
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "connection refused",
            "connect call failed",
            "cannot connect",
            "connection reset",
            "broken pipe",
            "timed out",
        )
    )


def _log_redis_warning_once(key: str, msg: str, *args: object) -> None:
    if key in _redis_warn_once_keys:
        return
    _redis_warn_once_keys.add(key)
    logger.warning(msg, *args)


def _degrade_to_local_fallback(reason: str, exc: Exception | None = None) -> bool:
    """Switch to in-process fallback after Redis becomes unreachable."""
    global _client, _fallback_used, _redis_degraded
    if not _fallback_enabled() or isinstance(_client, _LocalFallback):
        return False
    if not _redis_degraded:
        detail = f" ({exc})" if exc else ""
        logger.warning(
            "Redis non raggiungibile (%s)%s: uso LocalFallback in-process. "
            "Avvia Redis o rimuovi AION_REDIS_URL per evitare questo messaggio.",
            reason,
            detail,
        )
    _client = _LocalFallback()
    _fallback_used = True
    _redis_degraded = True
    return True


def _handle_redis_error(operation: str, exc: Exception) -> None:
    if _degrade_to_local_fallback(operation, exc):
        return
    if _is_connection_error(exc):
        _log_redis_warning_once(
            f"redis:{operation}:conn",
            "Redis non raggiungibile per %s: %s",
            operation,
            exc,
        )
        return
    _log_redis_warning_once(
        f"redis:{operation}",
        "%s failed: %s",
        operation,
        exc,
    )


def _redis_url() -> str:
    return (os.getenv("AION_REDIS_URL") or "").strip()


def redis_url_for_logs(url: Optional[str] = None) -> str:
    """URL Redis per log/diagnostica (password mascherata)."""
    u = (url if url is not None else _redis_url()).strip()
    if not u:
        return "(AION_REDIS_URL unset)"
    try:
        p = urlparse(u)
        if p.password is not None:
            user = p.username or ""
            host = p.hostname or ""
            port = f":{p.port}" if p.port else ""
            auth = f"{user}:****@" if user else "****@"
            netloc = f"{auth}{host}{port}"
            p = p._replace(netloc=netloc)
        return urlunparse(p)
    except Exception:
        return "(invalid AION_REDIS_URL)"


def redis_using_fallback() -> bool:
    """True se get_redis() sta usando LocalFallback (non un server Redis reale)."""
    return bool(_fallback_used)


def _fallback_enabled() -> bool:
    return os.getenv("AION_REDIS_FALLBACK_LOCAL", "1").lower() in ("1", "true", "yes")


def get_redis() -> Union[Any, _LocalFallback]:
    """
    Return asyncio Redis client or LocalFallback.
    Call once at startup; safe to call repeatedly (singleton).
    """
    global _client, _fallback_used
    if _client is not None:
        return _client
    url = _redis_url()
    if not url:
        logger.info("AION_REDIS_URL unset — using LocalFallback for Redis operations")
        _client = _LocalFallback()
        _fallback_used = True
        return _client
    try:
        import redis.asyncio as redis  # type: ignore

        _client = redis.from_url(url, decode_responses=True)
        _fallback_used = False
        return _client
    except Exception as e:
        logger.warning(
            "Redis client init failed url=%s err=%s; fallback=%s",
            redis_url_for_logs(url),
            e,
            _fallback_enabled(),
        )
        if _fallback_enabled():
            _client = _LocalFallback()
            _fallback_used = True
            return _client
        raise


def redis_namespace_key(*parts: str) -> str:
    return ":".join([_NS, *parts])


async def redis_enqueue_session_event(
    session_id: str, event: dict, ttl_sec: int = 3600
) -> None:
    """Cross-process session event queue (Redis/list with LocalFallback support)."""
    import json as _json

    r = get_redis()
    key = redis_namespace_key("session_events", session_id)
    payload = _json.dumps(event, ensure_ascii=False)
    try:
        await r.rpush(key, payload)
        if hasattr(r, "expire"):
            await r.expire(key, max(60, int(ttl_sec)))
    except Exception as e:
        _handle_redis_error("redis_enqueue_session_event", e)


async def redis_drain_session_events(
    session_id: str, max_items: int = 50
) -> list[dict]:
    """Drain queued session events (FIFO)."""
    import json as _json

    r = get_redis()
    key = redis_namespace_key("session_events", session_id)
    out: list[dict] = []
    for _ in range(max(1, int(max_items))):
        try:
            raw = await r.lpop(key)
        except Exception as e:
            _handle_redis_error("redis_drain_session_events", e)
            break
        if not raw:
            break
        try:
            data = _json.loads(raw)
            if isinstance(data, dict):
                out.append(data)
        except Exception:
            continue
    return out


async def redis_ping_startup() -> bool:
    url = _redis_url()
    r = get_redis()
    try:
        if hasattr(r, "ping"):
            pong = await r.ping()
            if not pong:
                raise RuntimeError("PING returned falsey")
            if isinstance(r, _LocalFallback):
                logger.info(
                    "Redis: modalità LocalFallback (url=%s). Adatta a un singolo processo backend; "
                    "per più repliche imposta un AION_REDIS_URL condiviso.",
                    redis_url_for_logs(url),
                )
            return True
    except Exception as e:
        err = str(e)
        if (
            url
            and _fallback_enabled()
            and ("MISCONF" in err or "stop-writes-on-bgsave-error" in err)
        ):
            global _client, _fallback_used
            logger.warning(
                "Redis in errore RDB/disco (MISCONF): uso LocalFallback in-process. "
                "Per usare Redis: libera spazio disco o `redis-cli CONFIG SET "
                "stop-writes-on-bgsave-error no`; in dev puoi anche commentare AION_REDIS_URL."
            )
            _client = _LocalFallback()
            _fallback_used = True
            _redis_degraded = True
            return True
        if url and _fallback_enabled() and _is_connection_error(e):
            _degrade_to_local_fallback("ping all'avvio", e)
            return True
        logger.warning(
            "Redis ping at startup failed url=%s: %s", redis_url_for_logs(url), e
        )
        if url and not isinstance(r, _LocalFallback) and not _fallback_enabled():
            logger.error(
                "Redis non utilizzabile e AION_REDIS_FALLBACK_LOCAL disabilitato: "
                "Approva Piano / code sessione falliranno. Correggi AION_REDIS_URL oppure "
                "imposta AION_REDIS_FALLBACK_LOCAL=1 per sviluppo a processo singolo."
            )
    return isinstance(r, _LocalFallback)


async def redis_set_stream_cancel(conversation_id: str, ttl_sec: int = 120) -> None:
    """Signal the streaming pipeline to cancel (Redis or LocalFallback)."""
    r = get_redis()
    key = redis_namespace_key("cancel", conversation_id)
    try:
        await r.set(key, "1", ex=ttl_sec)
    except Exception as e:
        _handle_redis_error("cancel flag", e)


async def redis_set_force_compact(conversation_id: str, ttl_sec: int = 600) -> None:
    """Next agent turn should force STM context compression (/compact)."""
    r = get_redis()
    key = redis_namespace_key("force_compact", conversation_id)
    try:
        await r.set(key, "1", ex=ttl_sec)
    except Exception as e:
        _handle_redis_error("force_compact", e)


async def redis_consume_force_compact(conversation_id: str) -> bool:
    """If /compact was requested, clear flag and return True."""
    r = get_redis()
    key = redis_namespace_key("force_compact", conversation_id)
    try:
        val = await r.get(key)
        if val:
            await r.delete(key)
            return True
    except Exception:
        pass
    return False


async def redis_consume_stream_cancel(conversation_id: str) -> bool:
    """If cancel was requested, clear the flag and return True."""
    r = get_redis()
    key = redis_namespace_key("cancel", conversation_id)
    try:
        val = await r.get(key)
        if val:
            await r.delete(key)
            return True
    except Exception:
        pass
    return False


def _stream_active_key(conversation_id: str) -> str:
    return redis_namespace_key("stream_active", conversation_id)


async def redis_set_stream_active(
    conversation_id: str,
    *,
    assistant_message_id: str,
    user_message_id: str,
    profile_name: str = "",
    ttl_sec: int = 7200,
) -> None:
    """Mark an in-flight /chat SSE turn (survives client disconnect / page reload)."""
    import json
    import time

    r = get_redis()
    key = _stream_active_key(conversation_id)
    payload = json.dumps(
        {
            "assistant_message_id": assistant_message_id,
            "user_message_id": user_message_id,
            "profile_name": profile_name,
            "started_at": time.time(),
        }
    )
    try:
        await r.set(key, payload, ex=ttl_sec)
    except Exception as e:
        _handle_redis_error("stream_active set", e)


async def redis_get_stream_active(conversation_id: str) -> Optional[dict]:
    """Return stream metadata dict if a turn is still running, else None."""
    import json

    r = get_redis()
    key = _stream_active_key(conversation_id)
    try:
        raw = await r.get(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def redis_clear_stream_active(conversation_id: str) -> None:
    r = get_redis()
    key = _stream_active_key(conversation_id)
    try:
        await r.delete(key)
    except Exception as e:
        _handle_redis_error("stream_active clear", e)


@asynccontextmanager
async def session_lock(session_id: str, ttl_sec: int = 600) -> AsyncIterator[bool]:
    """
    Best-effort distributed lock using SET NX EX.
    On LocalFallback, no-op yield True.
    """
    r = get_redis()
    key = redis_namespace_key("lock", session_id)
    if isinstance(r, _LocalFallback):
        yield True
        return
    token = str(time.time())
    ok = await r.set(key, token, nx=True, ex=ttl_sec)
    try:
        yield bool(ok)
    finally:
        if ok:
            try:
                await r.delete(key)
            except Exception:
                pass


async def rate_limiter_check(
    bucket_key: str,
    limit: int,
    window_sec: int,
) -> tuple[bool, int, int, int]:
    """
    Fixed window counter. Returns (allowed, remaining, reset_epoch, limit).
    """
    r = get_redis()
    k = redis_namespace_key("rl", bucket_key)
    reset = int(time.time()) // window_sec
    fk = f"{k}:{reset}"
    if isinstance(r, _LocalFallback):
        n = int((await r.get(fk)) or "0")
        if n >= limit:
            return False, 0, (reset + 1) * window_sec, limit
        await r.set(fk, str(n + 1), ex=window_sec + 2)
        return True, max(0, limit - n - 1), (reset + 1) * window_sec, limit
    try:
        pipe = r.pipeline()
        pipe.incr(fk)
        pipe.expire(fk, window_sec + 1)
        res = await pipe.execute()
        n = int(res[0])
        allowed = n <= limit
        rem = max(0, limit - n) if allowed else 0
        return allowed, rem, (reset + 1) * window_sec, limit
    except Exception as e:
        logger.debug("rate_limiter_check degraded: %s", e)
        return True, limit, int(time.time()) + window_sec, limit


async def cache_get(key: str) -> Optional[str]:
    r = get_redis()
    k = redis_namespace_key("cache", key)
    try:
        v = await r.get(k)
        return str(v) if v is not None else None
    except Exception:
        return None


async def cache_set(key: str, value: str, ttl_sec: int = 300) -> None:
    r = get_redis()
    k = redis_namespace_key("cache", key)
    try:
        await r.set(k, value, ex=ttl_sec)
    except Exception:
        pass


def redis_status() -> dict[str, Any]:
    """Returns connection and fallback info for admin dashboard."""
    r = get_redis()
    url = _redis_url()
    return {
        "connected": not _fallback_used,
        "fallback_active": _fallback_used,
        "type": "LocalFallback" if _fallback_used else "Redis asyncio",
        "url": redis_url_for_logs(url) if url else "N/A",
        "namespace": _NS,
    }
