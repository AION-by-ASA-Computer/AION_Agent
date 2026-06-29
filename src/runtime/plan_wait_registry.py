"""Wait registry piani orchestrazione (Redis / LocalFallback polling)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from src.runtime.redis_client import get_redis, redis_namespace_key, redis_url_for_logs

logger = logging.getLogger("aion.plan_wait")


def _key(plan_id: str) -> str:
    return redis_namespace_key("orch", "plan", plan_id)


async def set_pending(
    plan_id: str,
    *,
    session_id: str,
    user_id: str,
    draft: Dict[str, Any],
    ttl_sec: int,
) -> bool:
    """Persiste lo stato pending su Redis (o LocalFallback). False = Approva Piano non potrà risolvere il piano."""
    r = get_redis()
    payload = {
        "state": "pending",
        "session_id": session_id,
        "user_id": user_id,
        "draft": draft,
        "updated_at": time.time(),
    }
    key = _key(plan_id)
    try:
        blob = json.dumps(payload, ensure_ascii=False, default=str)
        await r.set(key, blob, ex=max(ttl_sec + 120, 300))
        return True
    except Exception as e:
        logger.error(
            "plan_wait set_pending FAILED plan_id=%s session=%s redis=%s err=%s",
            plan_id,
            session_id,
            redis_url_for_logs(),
            e,
            exc_info=True,
        )
        return False


async def wait_for_resolution(plan_id: str, *, poll_sec: float, timeout_sec: float) -> Dict[str, Any]:
    r = get_redis()
    key = _key(plan_id)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            raw = await r.get(key)
        except Exception as e:
            logger.warning("plan_wait poll: %s", e)
            await asyncio.sleep(poll_sec)
            continue
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await asyncio.sleep(poll_sec)
                continue
            st = data.get("state")
            if st in ("approved", "rejected", "timeout"):
                return data
        await asyncio.sleep(poll_sec)
    # mark timeout in redis (best effort)
    try:
        raw = await r.get(key)
        if raw:
            cur = json.loads(raw)
            cur["state"] = "timeout"
            cur["updated_at"] = time.time()
            await r.set(key, json.dumps(cur, ensure_ascii=False, default=str), ex=3600)
    except Exception:
        pass
    return {"state": "timeout", "plan": None, "reason": "AION_ORCH_PLAN_WAIT_TIMEOUT_SEC"}


async def resolve_plan(
    plan_id: str,
    *,
    session_id: str,
    approved: bool,
    approved_plan: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    r = get_redis()
    key = _key(plan_id)
    try:
        raw = await r.get(key)
    except Exception as e:
        logger.exception(
            "resolve_plan: Redis GET failed plan_id=%s session=%s redis=%s",
            plan_id,
            session_id,
            redis_url_for_logs(),
        )
        return {"ok": False, "error": "redis_unavailable", "detail": str(e)}
    if not raw:
        return {
            "ok": False,
            "error": "plan_not_found_or_expired",
            "detail": (
                "Nessuno stato pending per questo plan_id (scaduto, mai registrato, o Redis diverso da "
                "quello usato alla creazione del piano). Verifica AION_REDIS_URL, TTL, e che "
                "AION_REDIS_FALLBACK_LOCAL sia coerente tra riavvii se sviluppi senza Redis."
            ),
        }
    try:
        cur = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "corrupt_state"}
    if cur.get("session_id") != session_id:
        return {"ok": False, "error": "session_mismatch"}
    if cur.get("state") != "pending":
        return {"ok": False, "error": "not_pending"}
    if approved:
        final = approved_plan if approved_plan is not None else cur.get("draft")
        cur["state"] = "approved"
        cur["plan"] = final
    else:
        cur["state"] = "rejected"
        cur["reason"] = reason or "rejected"
    cur["updated_at"] = time.time()
    try:
        blob = json.dumps(cur, ensure_ascii=False, default=str)
        await r.set(key, blob, ex=3600)
    except Exception as e:
        logger.exception(
            "resolve_plan: Redis SET failed plan_id=%s session=%s redis=%s",
            plan_id,
            session_id,
            redis_url_for_logs(),
        )
        return {"ok": False, "error": "redis_write_failed", "detail": str(e)}
    return {"ok": True, "state": cur["state"], "plan": cur.get("plan")}
