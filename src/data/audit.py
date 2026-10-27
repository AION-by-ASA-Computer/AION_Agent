"""Audit delle azioni admin sensibili (tabella ``audit_log``).

Best-effort: un errore di scrittura non deve bloccare l'operazione.
Non inserire mai segreti (password, token, link) nel ``payload``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from .engine import get_async_session_maker
from .models import AuditLog

logger = logging.getLogger("aion.data.audit")


async def record_admin_action(
    *,
    tenant_id: str,
    actor: Optional[str],
    operation: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        async with get_async_session_maker()() as session:
            session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor=actor or "system",
                    operation=operation,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    payload=json.dumps(payload, ensure_ascii=False)
                    if payload
                    else None,
                )
            )
            await session.commit()
    except Exception as e:  # pragma: no cover - solo log
        logger.warning("audit %s non registrato: %s", operation, e)
