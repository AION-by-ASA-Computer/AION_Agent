"""Cached LLM endpoint health check (GET /models)."""
from __future__ import annotations

import logging
import os
import time
from typing import Optional, Tuple

import requests

logger = logging.getLogger("aion.llm_health")

_cache_at: float = 0.0
_cache_ok: bool = True
_cache_msg: str = ""


def _cache_ttl_sec() -> float:
    try:
        return float(os.getenv("AION_LLM_HEALTH_CACHE_SEC", "45"))
    except ValueError:
        return 45.0


def _ping_llm(url: str, key: str) -> Tuple[bool, str]:
    try:
        endpoint = url.rstrip("/") + "/models"
        headers: dict[str, str] = {}
        if key and key != "placeholder-token":
            headers["Authorization"] = f"Bearer {key}"
        requests.get(endpoint, headers=headers, timeout=3.0)
        return True, ""
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logger.error("LLM connection check failed for %s: %s", url, e)
        return (
            False,
            "Connectivity error: unable to reach the model endpoint "
            f"({url}). Check network connection and that the server is running.",
        )
    except Exception as e:
        logger.warning("Unexpected LLM ping error: %s — proceeding", e)
        return True, ""


def check_llm_connection(url: str, key: str) -> Tuple[bool, str]:
    """Return cached health when fresh; otherwise ping and update cache."""
    global _cache_at, _cache_ok, _cache_msg
    now = time.monotonic()
    ttl = _cache_ttl_sec()
    if _cache_at > 0 and (now - _cache_at) < ttl and _cache_ok:
        return True, ""
    ok, msg = _ping_llm(url, key)
    _cache_at = now
    _cache_ok = ok
    _cache_msg = msg
    return ok, msg


def reset_llm_health_cache() -> None:
    """Clear cache (tests)."""
    global _cache_at, _cache_ok, _cache_msg
    _cache_at = 0.0
    _cache_ok = True
    _cache_msg = ""
