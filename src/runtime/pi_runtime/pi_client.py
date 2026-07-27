"""HTTP client for the Pi Long Run worker."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from src.runtime.long_run_mode import pi_worker_secret, pi_worker_url

logger = logging.getLogger("aion.pi_client")

_HEALTH_CACHE: Dict[str, Any] = {"ok": False, "checked_at": 0.0}


def _headers() -> Dict[str, str]:
    secret = pi_worker_secret()
    h: Dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        h["X-Aion-Pi-Secret"] = secret
    return h


async def pi_worker_healthy(*, force: bool = False) -> bool:
    import time

    now = time.time()
    if not force and now - float(_HEALTH_CACHE.get("checked_at") or 0) < 5.0:
        return bool(_HEALTH_CACHE.get("ok"))

    url = f"{pi_worker_url()}/health"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(url, headers=_headers())
            ok = r.status_code == 200 and r.json().get("ok") is True
    except Exception as exc:
        logger.debug("Pi worker health check failed: %s", exc)
        ok = False
    _HEALTH_CACHE["ok"] = ok
    _HEALTH_CACHE["checked_at"] = now
    return ok


class PiWorkerClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or pi_worker_url()).rstrip("/")

    async def ensure_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{self.base_url}/sessions",
                headers=_headers(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {"ok": True}

    async def abort_session(self, session_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self.base_url}/sessions/{session_id}/abort",
                    headers=_headers(),
                )
        except Exception as exc:
            logger.debug("Pi abort failed session=%s: %s", session_id[:8], exc)

    async def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{self.base_url}/sessions/{session_id}/messages",
                headers=_headers(),
            )
            r.raise_for_status()
            data = r.json()
            return list(data.get("messages") or [])

    async def stream_prompt(
        self,
        session_id: str,
        message: str,
        *,
        stop_event: Any = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/sessions/{session_id}/prompt",
                headers=_headers(),
                json={"message": message},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                        await self.abort_session(session_id)
                        break
                    raw = (line or "").strip()
                    if not raw:
                        continue
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Pi worker invalid JSON line: %s", raw[:200])
